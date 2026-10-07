import asyncio
import ipaddress
import json
import logging
import os
import sys
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..config import VOZONDA_MEDIA, VOZONDA_MODELS_DIR, VOZONDA_SECRETS_DIR
from ..env import env
from ..envfile import load_env_file

logger = logging.getLogger(__name__)

load_env_file()

_DEFAULT_RENDERER = Path(__file__).resolve().parent.parent / "render_vozonda.py"
_DEFAULT_MEDIA = Path(VOZONDA_MEDIA)

TTS_SCRIPT = env("TTS_SCRIPT", str(_DEFAULT_RENDERER))
TTS_PY = env("TTS_PY", sys.executable)
LLM_BASE = env("LLM_BASE", "http://127.0.0.1:30001/v1")
LLM_MODEL = env("LLM_MODEL", "qwen3.6-35b")
MEDIA_DIR = Path(env("MEDIA", str(_DEFAULT_MEDIA)))
HF_HOME = env("HF_HOME") or str(Path.home() / ".cache" / "vozonda" / "hf")


def _parse_json_env(name: str) -> list[dict]:
    raw = env(name, "")
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
        return [p for p in parsed if isinstance(p, dict)]
    except json.JSONDecodeError:
        return []


def llm_fallbacks() -> list[dict]:
    out = []
    for fb in _parse_json_env("LLM_FALLBACKS"):
        if not fb.get("base") or not fb.get("model"):
            continue
        fb = dict(fb)
        key_env = fb.pop("key_env", None)
        fb["key"] = os.environ.get(key_env, "") if key_env else ""
        out.append(fb)
    return out


NIM_BASE = "https://integrate.api.nvidia.com/v1"

# OpenCode models run through the local `opencode` CLI: its free tier refuses
# calls from outside OpenCode. Which models, and in which order, is the
# setting llm.opencode_models (bench of 2026-09-28: bench/runs/20260928-writers).
OPENCODE_BASE = "opencode:"

# An episode with uploaded files stays on the local model unless its tray
# allowed the cloud (VOZONDA-TRAY-PRIVACY): pipeline.run_job sets this from
# job['local_only'] for the whole run (script, insights, translation).
LOCAL_ONLY: ContextVar[bool] = ContextVar("vozonda_local_only", default=False)


def is_local_provider(prov: dict) -> bool:
    """True when the provider's base URL stays on this machine or LAN.

    A loopback or private address (the fetcher's _host_is_private logic);
    anything else, including names that do not resolve and schemes without a
    host (opencode: runs through a local CLI, but the models are cloud), is
    not local."""
    try:
        host = urlparse(str(prov.get("base") or "")).hostname or ""
    except ValueError:
        return False
    if not host:
        return False
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    if host.lower() == "localhost":
        return True
    try:
        from ..fetcher import _host_is_private

        return _host_is_private(host)
    except Exception:
        return False


def _setting(key: str) -> str:
    try:
        from ..settings_store import get_setting
        return (get_setting(key) or "").strip()
    except Exception:
        return ""


def opencode_bin() -> str:
    """Path of the opencode CLI: VOZONDA_OPENCODE_BIN, PATH, then nvm installs.

    The systemd unit's PATH has no nvm directory, so the nvm glob matters.
    """
    import shutil

    explicit = env("OPENCODE_BIN", "").strip()
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else ""
    found = shutil.which("opencode")
    if found:
        return found
    nvm = sorted(Path.home().glob(".nvm/versions/node/*/bin/opencode"))
    return str(nvm[-1]) if nvm else ""


def opencode_models() -> list[str]:
    """Ordered model ids: setting llm.opencode_models, then VOZONDA_OPENCODE_MODELS."""
    raw = _setting("llm.opencode_models") or env("OPENCODE_MODELS", "")
    return [m for m in raw.replace(",", " ").split() if m]


def nim_model() -> str:
    """NIM model id: setting llm.nim_model, then VOZONDA_NIM_MODEL."""
    return _setting("llm.nim_model") or env("NIM_MODEL", "").strip()


def nim_api_key() -> str:
    """NVIDIA NIM key: settings, then VOZONDA_NIM_API_KEY, then <secrets>/nvidia_nim_api.key."""
    stored = _setting("llm.nim_api_key")
    if stored:
        return stored
    explicit = env("NIM_API_KEY", "").strip()
    if explicit:
        return explicit
    key_file = VOZONDA_SECRETS_DIR / "nvidia_nim_api.key"
    try:
        return key_file.read_text().strip() if key_file.exists() else ""
    except OSError:
        return ""


def _engine_chain(engine: str) -> list[dict]:
    """Providers for one llm.engine value, in the order they are tried."""
    if engine in ("local", "qwen_vllm"):
        # 'qwen_vllm' is the pre-generic alias of 'local' (production still
        # stores it as llm.backup_engine); both are the user's own
        # OpenAI-compatible endpoint from VOZONDA_LLM_BASE / VOZONDA_LLM_MODEL
        chain = [{"name": "local", "base": LLM_BASE, "model": LLM_MODEL}]
        chain.extend(llm_fallbacks())
        return chain
    if engine == "kimi_nim":
        # opt-in cloud writer (bench 2026-09-25: met the dialog form the local
        # model ignored); the source text leaves the machine
        model = nim_model()
        return [{"name": "kimi_nim", "base": NIM_BASE, "model": model, "key": nim_api_key()}] if model else []
    if engine == "opencode":
        if not opencode_bin():
            return []
        return [{"name": "opencode", "base": OPENCODE_BASE, "model": m} for m in opencode_models()]
    if engine == "claude":
        api_key = _setting("llm.api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        model = _setting("llm.custom_model") or "claude-3-7-sonnet-20250219"
        return [{"name": "claude", "base": "https://api.anthropic.com/v1", "model": model, "key": api_key}]
    if engine == "custom":
        base = _setting("llm.custom_base") or LLM_BASE
        model = _setting("llm.custom_model") or LLM_MODEL
        return [{"name": "custom", "base": base, "model": model, "key": _setting("llm.api_key")}]
    return []


def llm_chain() -> list[dict]:
    """llm.engine's providers, then llm.backup_engine's (any engine can back up
    any other; the shared NIM queue was down for hours on 2026-09-28).

    While LOCAL_ONLY is set (an episode with uploaded files whose tray did not
    allow the cloud), every non-local provider is dropped, including the
    backup engine's: the whole run stays on this machine."""
    engine = _setting("llm.engine") or "local"
    chain = _engine_chain(engine)
    backup = _setting("llm.backup_engine")
    if backup and backup not in ("none", engine):
        chain += [p for p in _engine_chain(backup) if p not in chain]
    if LOCAL_ONLY.get():
        chain = [p for p in chain if is_local_provider(p)]
    return chain


def tts_fallbacks() -> list[dict]:
    out = []
    for fb in _parse_json_env("TTS_FALLBACKS"):
        if not fb.get("name"):
            continue
        fb = dict(fb)
        key_env = fb.pop("key_env", None)
        fb["key"] = os.environ.get(key_env, "") if key_env else ""
        out.append(fb)
    return out


_PROBE_TTL = 120
_probe_cache: dict[str, tuple[float, bool]] = {}


async def probe(name: str) -> bool:
    now = asyncio.get_event_loop().time()
    cached = _probe_cache.get(name)
    if cached and now - cached[0] < _PROBE_TTL:
        return cached[1]
    result = await _probe_uncached(name)
    _probe_cache[name] = (now, result)
    return result


async def _probe_uncached(name: str) -> bool:
    if name == "script_llm":
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(f"{LLM_BASE}/models")
                return r.status_code == 200 or bool(llm_fallbacks())
        except Exception:
            return bool(llm_fallbacks())
    if name == "qwen3_tts":
        local_ok = Path(TTS_SCRIPT).exists() and Path(TTS_PY).exists()
        if local_ok:
            # file existence says nothing about a broken venv; verify the
            # library actually imports in the renderer interpreter
            try:
                proc = await asyncio.create_subprocess_exec(
                    TTS_PY,
                    "-c",
                    "import qwen_tts",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout=20)
                except TimeoutError:
                    proc.kill()
                    return bool(tts_fallbacks())
                return proc.returncode == 0 or bool(tts_fallbacks())
            except Exception:
                return bool(tts_fallbacks())
        return bool(tts_fallbacks())
    if name == "kokoro":
        kokoro_url = env("KOKORO_URL", "")
        if kokoro_url:
            try:
                async with httpx.AsyncClient(timeout=3) as c:
                    r = await c.post(kokoro_url, json={"model": "kokoro", "input": "hi", "voice": "af_bella"})
                    if r.status_code == 200:
                        return True
            except Exception:
                logger.debug("kokoro http probe failed, using fallbacks", exc_info=True)
            return bool(tts_fallbacks())
        try:
            proc = await asyncio.create_subprocess_exec(
                TTS_PY, "-c", "import kokoro_onnx", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except TimeoutError:
                proc.kill()
                return bool(tts_fallbacks())
            return proc.returncode == 0 or bool(tts_fallbacks())
        except Exception:
            return bool(tts_fallbacks())
    return True


def _probe_installed_engines() -> list[dict]:
    """Probe which TTS engines are actually installed (#101)."""
    engines: list[dict] = []

    qwen_ok = False
    try:
        import qwen_tts  # noqa: F401
        import torch  # noqa: F401
        qwen_ok = True
    except ImportError:
        pass
    engines.append({
        "id": "qwen_tts",
        "label": "qwen3_tts (local, best quality)",
        "installed": qwen_ok,
        "fix": "uv sync --extra tts-qwen",
    })

    voxtral_key_file = VOZONDA_SECRETS_DIR / "mistral_api.key"
    voxtral_has_key = False
    try:
        voxtral_has_key = bool(voxtral_key_file.exists() and voxtral_key_file.read_text().strip())
    except Exception:
        voxtral_has_key = False
    voxtral_ok = bool(
        os.environ.get("MISTRAL_API_KEY")
        or os.environ.get("VOXTRAL_API_KEY")
        or voxtral_has_key
    )
    engines.append({
        "id": "voxtral",
        "label": "voxtral (Mistral EU, 30+ European voices & emotion tags)",
        "installed": voxtral_ok,
        "fix": f"echo 'your_key' > {VOZONDA_SECRETS_DIR / 'mistral_api.key'}",
    })

    piper_ok = False
    try:
        import piper  # noqa: F401
        piper_ok = True
    except ImportError:
        pass
    engines.append({
        "id": "piper",
        "label": "piper (CPU, multi-lingual open source)",
        "installed": piper_ok,
        "fix": "uv sync --extra tts-piper",
    })

    kokoro_ok = False
    kokoro_url = env("KOKORO_URL", "")
    try:
        import kokoro_onnx  # noqa: F401
        kokoro_ok = True
    except ImportError:
        pass
    if kokoro_url:
        kokoro_ok = True
    else:
        kokoro_model_paths = [
            Path(env("KOKORO_ONNX", str(VOZONDA_MODELS_DIR / "kokoro-v1.0.onnx"))),
        ]
        if any(p.exists() for p in kokoro_model_paths):
            kokoro_ok = True
    engines.append({
        "id": "kokoro",
        "label": "kokoro-82m (local ONNX, 82M expressive, 15-25x realtime)",
        "installed": kokoro_ok,
        "fix": "uv sync --extra tts-kokoro or set VOZONDA_KOKORO_URL=http://127.0.0.1:8880/v1/audio/speech",
    })

    metas = tts_engines()
    for entry in engines:
        meta = metas.get(entry["id"])
        if meta:
            entry.update(
                label=meta.label or entry["label"],
                ui_badge=meta.ui_badge,
                ui_fix_hint=meta.ui_fix_hint,
                license=meta.license,
                commercial_use=meta.commercial_use,
                renderer=meta.renderer,
            )
        entry.setdefault("license", "")
        entry.setdefault("commercial_use", True)
        entry.setdefault("ui_badge", "")
        entry.setdefault("ui_fix_hint", entry.get("fix", ""))
        entry.setdefault("fix", entry.get("ui_fix_hint", ""))
        entry.setdefault("renderer", "")
        entry["location"] = _location(meta)
        reason = engine_blocked_reason(entry["id"])
        if reason:
            entry.update(installed=False, fix=reason, ui_fix_hint=reason)
    for engine_id, meta in metas.items():          # engines added as plugins only
        if not any(e["id"] == engine_id for e in engines):
            engines.append({"id": engine_id, "label": meta.label,
                            "installed": not engine_blocked_reason(engine_id)
                                         and bool(getattr(_module_of(engine_id), "is_installed", lambda: True)()),
                            "fix": engine_blocked_reason(engine_id) or meta.ui_fix_hint,
                            "ui_fix_hint": engine_blocked_reason(engine_id) or meta.ui_fix_hint,
                            "ui_badge": meta.ui_badge,
                            "license": meta.license, "commercial_use": meta.commercial_use,
                            "renderer": meta.renderer, "location": _location(meta)})
    return engines


def _location(meta: object) -> str:
    """'cloud' when the engine sends text over the network (voxtral), else 'local'."""
    from ..plugins.types import Permission

    perms = getattr(meta, "permissions", frozenset()) or frozenset()
    return "cloud" if Permission.NETWORK in perms else "local"


def _module_of(engine_id: str):
    from ..plugins import registry
    try:
        return registry.get(engine_id)
    except KeyError:
        return None


from typing import Any

# A TTS engine is a provider module with META.renderer: adding one needs no
# edit here, in settings_store.py, voices.py or pipeline.py (the four places
# the engine list used to be hardcoded in).
EngineId = str
_engine_cache: dict[str, Any] = {}


def tts_engines(refresh: bool = False) -> dict[str, Any]:
    """Discovered TTS engines that can render: {engine id: PluginMeta}."""
    if _engine_cache and not refresh:
        return _engine_cache
    from ..plugins import registry
    from ..plugins.types import PluginKind
    try:
        registry.discover("vozonda_api.providers")
    except Exception:  # discovery is best effort; a broken module must not kill the API
        logger.debug("tts engine discovery failed, using cached engines", exc_info=True)
    found = {m.id: m for m in registry.all_meta(PluginKind.TTS_ENGINE) if getattr(m, "renderer", "")}
    _engine_cache.clear()
    _engine_cache.update(found)
    return _engine_cache


def engine_ids() -> set[str]:
    return set(tts_engines())


def billing_enabled() -> bool:
    return env("ENABLE_BILLING", "false").strip().lower() == "true"


def engine_blocked_reason(engine_id: str) -> str | None:
    """Why this engine may not be used right now (licence gate), else None."""
    meta = tts_engines().get(engine_id)
    if meta and billing_enabled() and not meta.commercial_use:
        return f"{engine_id} is licensed for non-commercial use only ({meta.license}); billing is enabled"
    return None


def kokoro_supports_language(language: str) -> bool:
    """True when a job language renders with Kokoro, else Piper covers it."""
    try:
        from .kokoro import KOKORO_SUPPORTED_LANGS
    except Exception:
        KOKORO_SUPPORTED_LANGS = frozenset({"en", "es", "fr", "it", "pt", "hi", "ja", "zh"})
    return (language or "").strip().lower() in KOKORO_SUPPORTED_LANGS


def resolve_voice_engine(engine: str, language: str) -> tuple[str, str | None]:
    """Effective TTS engine for a job language.

    Kokoro covers English and 7 more languages; anything else (de, nl,
    pl, ru, ...) renders with Piper when kokoro is the engine. 'auto'
    stays unresolved here: the caller detects the source language first,
    then applies the same rule. Returns (effective engine, log line or None).
    """
    lang = (language or "").strip().lower()
    if engine != "kokoro" or not lang or lang == "auto":
        return engine, None
    if kokoro_supports_language(lang):
        return engine, None
    return "piper", f"kokoro has no {lang}, using piper"

PROVIDER_CAPABILITIES: dict[str, dict[str, bool]] = {
    "voxtral": {
        "supports_instructions": True,
        "supports_emotion_instructions": True,
        "supports_paralinguistic_tags": True,
    },
    "qwen_tts": {
        "supports_instructions": True,
        "supports_emotion_instructions": True,
        "supports_paralinguistic_tags": False,
    },
    "piper": {
        "supports_instructions": False,
        "supports_emotion_instructions": False,
        "supports_paralinguistic_tags": False,
    },
    "kokoro": {
        "supports_instructions": False,
        "supports_emotion_instructions": False,
        "supports_paralinguistic_tags": False,
    },
}


def get_provider_capabilities(engine_id: EngineId | str | None) -> dict[str, bool]:
    """Return capability flags for a given voice provider seam."""
    if not engine_id:
        return {
            "supports_instructions": True,
            "supports_emotion_instructions": True,
            "supports_paralinguistic_tags": False,
        }
    return PROVIDER_CAPABILITIES.get(
        engine_id,
        {
            "supports_instructions": False,
            "supports_emotion_instructions": False,
            "supports_paralinguistic_tags": False,
        },
    )


def resolve_emotion_delivery(
    engine_id: EngineId | str | None,
    emotion: str | None = "neutral",
    style: str | None = None,
) -> dict[str, Any]:
    """Resolve unified emotion delivery directives across LLM and TTS seams."""
    caps = get_provider_capabilities(engine_id)
    emo = (emotion or "neutral").strip().lower()

    use_tags = bool(caps.get("supports_paralinguistic_tags", False))
    use_instruct = bool(caps.get("supports_emotion_instructions", False))

    # Prompt directive for LLM writing phase
    if use_tags:
        prompt_directive = (
            f"OVERALL EMOTIONAL REGISTER: Shape the dialogue energy and host interaction to be {emo}. "
            "You may include [laughs], [sighs], [gasps], [clears throat] tags naturally."
        )
    else:
        prompt_directive = (
            f"OVERALL EMOTIONAL REGISTER: Shape the dialogue energy and host interaction to be {emo}. "
            "TTS PROSE DIRECTIVE: Do not use bracketed tags like [laughs] or (sighs). "
            "Convey all emotional energy strictly through punctuation, phrasing, and pacing."
        )

    # Engine-tailored style directives for LLM prompt
    style_directive = ""
    if style == "true_crime":
        if use_tags:
            style_directive = (
                " STYLE ENGINE DIRECTIVE: Deliver atmospheric tension and deep suspense. "
                "You may use [gasps], [whisper], [sighs] to accentuate chilling reveals."
            )
        else:
            style_directive = (
                " STYLE ENGINE DIRECTIVE: Deliver atmospheric tension and deep suspense "
                "through dramatic pauses and terse punctuation. Do not use bracketed tags."
            )
    elif style == "tech_roast":
        if use_tags:
            style_directive = (
                " STYLE ENGINE DIRECTIVE: Deliver fast-paced witty banter and sarcasm. "
                "You may use [laughs], [chuckles], [sighs] on punchlines."
            )
        else:
            style_directive = (
                " STYLE ENGINE DIRECTIVE: Deliver fast-paced witty banter and sarcasm "
                "through deadpan timing and sharp wording. Do not use bracketed tags."
            )
    elif style == "meditation":
        if use_tags:
            style_directive = (
                " STYLE ENGINE DIRECTIVE: Deliver gentle ASMR soothing relaxation. "
                "You may use [whisper], [sighs] softly."
            )
        else:
            style_directive = (
                " STYLE ENGINE DIRECTIVE: Deliver gentle ASMR soothing relaxation "
                "through slow tempo and tranquil phrasing. Do not use bracketed tags."
            )
    elif style == "noir":
        if use_tags:
            style_directive = (
                " STYLE ENGINE DIRECTIVE: Deliver slow, gravelly noir delivery with weary cynicism. "
                "You may use [sighs], [clears throat], [whisper] on punchy pauses."
            )
        else:
            style_directive = (
                " STYLE ENGINE DIRECTIVE: Deliver slow, gravelly noir delivery with weary cynicism "
                "and atmospheric pauses. Do not use bracketed tags."
            )
    elif style == "trivia":
        if use_tags:
            style_directive = (
                " STYLE ENGINE DIRECTIVE: Deliver bright game-show energy. "
                "You may use [laughs], [chuckles], [cheers] on dramatic score reveals."
            )
        else:
            style_directive = (
                " STYLE ENGINE DIRECTIVE: Deliver bright game-show energy and fast-paced "
                "quizmaster banter. Do not use bracketed tags."
            )
    elif style == "courtroom":
        if use_tags:
            style_directive = (
                " STYLE ENGINE DIRECTIVE: Deliver courtroom drama and legal tension. "
                "You may use [gasps], [clears throat] on key objections."
            )
        else:
            style_directive = (
                " STYLE ENGINE DIRECTIVE: Deliver courtroom drama and legal tension "
                "through authoritative rhetoric and sharp pauses. Do not use bracketed tags."
            )
    elif style == "crisis_room":
        if use_tags:
            style_directive = (
                " STYLE ENGINE DIRECTIVE: Deliver high-stakes situation room urgency. "
                "You may use [sighs], [whisper] on high-pressure tactical decisions."
            )
        else:
            style_directive = (
                " STYLE ENGINE DIRECTIVE: Deliver high-stakes situation room urgency "
                "through rapid-fire telemetry and authoritative command cadence. Do not use bracketed tags."
            )

    if style_directive:
        prompt_directive += style_directive

    # Instruct text for TTS synthesis phase
    instruct_text: str | None = None
    if use_instruct:
        from ..styles import EMOTION_INSTRUCTS

        instruct_text = EMOTION_INSTRUCTS.get(emo) or None
        if emo == "neutral" and style:
            if style == "asmr":
                instruct_text = (
                    "Speak very softly and slowly, almost a whisper: intimate, "
                    "close to the microphone, with long calm pauses."
                )
            elif style == "futbol":
                instruct_text = (
                    "Speak fast, loud and rising, like a football commentator "
                    "shouting a goal: explosive excitement."
                )
            elif style == "true_crime":
                instruct_text = (
                    "Speak with atmospheric tension, deep suspense, and "
                    "deliberate dramatic pauses."
                )
            elif style == "tech_roast":
                instruct_text = (
                    "Speak with sharp wit, fast-paced banter, and a "
                    "sarcastic tone."
                )
            elif style == "meditation":
                instruct_text = (
                    "Speak in a gentle, soothing ASMR narration style with "
                    "a slow tempo."
                )
            elif style == "noir":
                instruct_text = (
                    "Speak with a weary, atmospheric noir cadence, deliberate "
                    "gravelly tone, and world-weary pauses."
                )
            elif style == "trivia":
                instruct_text = (
                    "Speak with bright, upbeat game-show energy, crisp "
                    "articulation, and lively competitive tempo."
                )
            elif style == "courtroom":
                instruct_text = (
                    "Speak with authoritative legal gravitas, sharp "
                    "courtroom cadence, and dramatic cross-examination tension."
                )
            elif style == "crisis_room":
                instruct_text = (
                    "Speak with situation-room urgency, controlled command "
                    "authority, and rapid-fire operational precision."
                )

    return {
        "supports_paralinguistic_tags": use_tags,
        "supports_emotion_instructions": use_instruct,
        "prompt_directive": prompt_directive,
        "instruct_text": instruct_text,
    }


def provider_list() -> list[dict]:
    """Return the pipeline stage provider list.

    Voice stage reflects reality: probes installed engines (#101).
    Script stage is always script_llm (streaming JSON lines).
    """
    engines = _probe_installed_engines()
    active_engine = next((e["id"] for e in engines if e["installed"]), "qwen3_tts")

    return [
        {"id": "source_http", "stage": "source", "default": True},
        {"id": "script_llm", "stage": "script", "default": True},
        {"id": active_engine, "stage": "voice", "default": True},
        {"id": "master_ffmpeg", "stage": "master", "default": True},
    ]
