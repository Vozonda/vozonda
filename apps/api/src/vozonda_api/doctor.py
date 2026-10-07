import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .providers import (
    HF_HOME,
    LLM_BASE,
    MEDIA_DIR,
    TTS_PY,
    llm_chain,
    llm_fallbacks,
    tts_fallbacks,
)


def _port_open(url: str, timeout: float = 2.0) -> bool:
    p = urlparse(url)
    host = p.hostname or "127.0.0.1"
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _is_local(base: str) -> bool:
    host = (urlparse(base).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "host.docker.internal") or host.endswith(".local")


def _llm_ok() -> tuple[bool, str]:
    """Is any provider of the configured chain (llm.engine, then llm.backup_engine) usable?

    It used to probe VOZONDA_LLM_BASE only, so a custom endpoint or a cloud writer was
    blocked whenever nothing listened on the default address (2026-10-01). Local
    endpoints are probed (port, then /models); a remote endpoint with a key is trusted
    here and its errors surface in the script stage."""
    try:
        chain = llm_chain()
    except Exception as exc:
        return False, f"LLM configuration unreadable: {exc}"
    if not chain:
        return False, (
            "no script writer configured: set llm.engine in the settings, start a local LLM "
            f"on {LLM_BASE} (Ollama, vLLM, llama.cpp) or point VOZONDA_LLM_BASE at one."
        )
    tried: list[str] = []
    for prov in chain:
        base = str(prov.get("base") or "")
        if not base:
            continue
        if not base.startswith(("http://", "https://")):
            return True, ""  # CLI-backed writer (opencode:); in the chain only when installed
        if not _is_local(base) and prov.get("key"):
            return True, ""
        if not _port_open(base):
            tried.append(f"{base} (nothing listening)")
            continue
        try:
            r = httpx.get(f"{base}/models", timeout=5)
            if r.status_code == 200:
                return True, ""
            tried.append(f"{base} (answered {r.status_code})")
        except Exception as exc:
            tried.append(f"{base} ({exc})")
    return False, (
        "no LLM reachable: " + "; ".join(tried) + ". Start your local LLM first (e.g. Ollama, vLLM, "
        "or llama.cpp), point VOZONDA_LLM_BASE at any OpenAI-compatible endpoint, or pick a cloud "
        "writer in the settings."
    )


def _tts_python_ok() -> tuple[bool, str]:
    p = Path(TTS_PY)
    if not p.exists():
        return False, (
            f"tts python not found at {TTS_PY}. "
            "Set VOZONDA_TTS_PY to a python that has qwen_tts + torch installed "
            "(see docs/install.md)."
        )
    return True, ""


def _ffmpeg_ok() -> tuple[bool, str]:
    if shutil.which("ffmpeg"):
        return True, ""
    return False, "ffmpeg not found in PATH. Install it: sudo apt install ffmpeg"


def _media_writable() -> tuple[bool, str]:
    try:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        probe = MEDIA_DIR / ".write-test"
        probe.write_text("x")
        probe.unlink()
        return True, ""
    except Exception as exc:
        return False, f"media dir {MEDIA_DIR} not writable: {exc}"


def _model_cache_hint() -> tuple[bool, str]:
    hf = Path(HF_HOME)
    if hf.exists():
        return True, ""
    return True, (
        f"note: model cache {hf} does not exist; "
        "first TTS job will download ~4GB from Hugging Face."
    )


# The package a local engine's renderer imports, and the extra that installs it.
# Engines not listed (cloud engines, plugins with their own checks) skip the deep check:
# until 2026-10-01 every engine was checked against qwen_tts, so a Kokoro-only install
# (the CPU default since 65408b4) had every job refused.
_ENGINE_PACKAGES: dict[str, tuple[str, str]] = {
    "qwen_tts": ("qwen_tts", "tts-qwen"),
    "qwen3_tts": ("qwen_tts", "tts-qwen"),
    "kokoro": ("kokoro_onnx", "tts-kokoro"),
    "piper": ("piper", "tts-piper"),
}
# A successful import check is reused for a while: it spawns the renderer interpreter
# and imports the engine (about 4 s with torch), and ran on EVERY job start.
_RENDERABLE_TTL = 600.0
_RENDERABLE_CACHE: dict[tuple[str, str], float] = {}


def _configured_tts_engine() -> str:
    try:
        from .settings_store import get_setting

        return str(get_setting("tts.engine") or "qwen_tts").strip()
    except Exception:
        return "qwen_tts"


def _tts_renderable() -> tuple[bool, str]:
    """Deep check: can the renderer interpreter import the CONFIGURED engine's package?

    File existence alone said healthy while every render crashed at model
    load (issue #18). A subprocess import catches broken venvs and missing
    deps without paying a full model load.
    """
    if not str(TTS_PY).strip() or not Path(TTS_PY).is_file():
        return True, ""  # _tts_python_ok already reports this with a hint
    pkg = _ENGINE_PACKAGES.get(_configured_tts_engine())
    if pkg is None:
        return True, ""
    module, extra = pkg
    key = (str(TTS_PY), module)
    checked = _RENDERABLE_CACHE.get(key)
    if checked is not None and time.monotonic() - checked < _RENDERABLE_TTL:
        return True, ""
    try:
        proc = subprocess.run(
            [TTS_PY, "-c", f"import {module}"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except OSError as exc:
        return False, f"cannot run the TTS interpreter {TTS_PY!r}: {exc}. Point VOZONDA_TTS_PY at a python executable."
    except subprocess.TimeoutExpired:
        return False, (
            f"importing {module} in {TTS_PY} hangs. "
            "The voice engine cannot render; fix or point VOZONDA_TTS_PY "
            "at a working python, or configure VOZONDA_TTS_FALLBACKS."
        )
    if proc.returncode == 0:
        _RENDERABLE_CACHE[key] = time.monotonic()
        return True, ""
    _RENDERABLE_CACHE.pop(key, None)
    stderr = proc.stderr.decode(errors="replace")
    tail = stderr.strip().splitlines()
    reason = tail[-1][:200] if tail else "unknown import error"

    # Map common failure modes to actionable hints
    hint = f"{module} does not import in {TTS_PY}: {reason}. "
    if "Permission denied" in reason or "Errno 13" in reason:
        hint += (
            "This is usually a cache-permission issue: "
            "chown -R $USER ~/.triton/cache ~/.cache/huggingface "
            "or run the job as the correct user."
        )
    elif "torch" in reason.lower() or "triton" in reason.lower():
        hint += f"Missing torch/triton. Fix: uv sync --extra {extra}"
    elif "ModuleNotFoundError" in reason or "No module named" in reason:
        hint += f"Missing package in the TTS venv. Fix: uv sync --extra {extra}"
    elif "timeout" in reason.lower() or "compile" in reason.lower():
        hint += (
            "Triton kernel compilation hanging. "
            "Set TRITON_CACHE_DIR to a writable cache dir and ensure it is writable."
        )
    else:
        hint += "Jobs will fail at the voice stage until fixed."
    return False, hint


def run_doctor() -> dict:
    from .providers import _probe_installed_engines

    checks = []
    for name, fn in [
        ("script_llm", _llm_ok),
        ("voice_engine", _tts_python_ok),
        ("voice_renderable", _tts_renderable),
        ("master_ffmpeg", _ffmpeg_ok),
        ("media_dir", _media_writable),
        ("model_cache", _model_cache_hint),
    ]:
        ok, hint = fn()
        checks.append({"id": name, "ok": ok, "hint": hint})

    # Add engine-specific info from the probe
    engines = _probe_installed_engines()
    for eng in engines:
        checks.append({
            "id": f"engine_{eng['id']}",
            "ok": eng["installed"],
            "optional": True,
            "hint": (
                f"{eng['label']} - {'installed' if eng['installed'] else 'not installed. ' + eng['fix']}"
            ),
        })

    # optional engines that are not installed must not mark a working install as broken
    return {"ok": all(c["ok"] for c in checks if not c.get("optional")), "checks": checks}


def blocking_problem() -> str | None:
    result = run_doctor()
    # engine_* checks are informational (installed or not): a missing
    # optional engine must never block a job. voice_engine already
    # covers the real blocking case (no tts at all).
    broken = [
        c
        for c in result["checks"]
        if not c["ok"] and c["id"] != "model_cache" and not c["id"].startswith("engine_")
    ]

    if any(c["id"] == "script_llm" and not c["ok"] for c in broken):
        names = [f.get("name") for f in llm_fallbacks()]
        if names:
            broken = [c for c in broken if c["id"] != "script_llm"]
            checks_note = f"script_llm: local down, will try fallbacks ({', '.join(names)})"
            checks_note and broken.append({"id": "script_llm-degraded", "ok": True, "hint": checks_note})

    if any(c["id"] == "voice_engine" and not c["ok"] for c in broken):
        names = [f.get("name") for f in tts_fallbacks()]
        if names:
            broken = [c for c in broken if c["id"] != "voice_engine"]
            note = f"voice_engine: local unavailable, will try cloud fallbacks ({', '.join(names)})"
            broken.append({"id": "voice_engine-degraded", "ok": True, "hint": note})

    hard = [c for c in broken if c.get("ok") is False or "degraded" not in c["id"]]
    if not hard:
        return None
    return "; ".join(f"{c['id']}: {c['hint']}" for c in hard)
