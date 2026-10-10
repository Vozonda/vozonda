import asyncio
import datetime
import hmac
import html as htmllib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import access
from . import budget as _budget
from .clips import (
    clip_description,
    clip_display_label,
    clip_filename,
    clip_quote_slug,
    clip_quote_snippet,
    clip_title,
    compute_clip_bounds,
    find_clip_file,
    get_audio_duration_sync,
    parse_clip_spec,
    slice_audio,
)
from .doctor import run_doctor
from .env import env
from .jobs import JobStore
from .pipeline import (
    EMOTIONS,
    LANGUAGES,
    NARRATION_PROMPT,
    TONES,
    _clean_src,
    _cleanup_job_output_files,
    _kill_job_subprocesses,
    resume_after_review,
    run_job,
)
from .providers import MEDIA_DIR
from .routers.billing import router as billing_router
from .routers.distribution import router as distribution_router
from .routers.feeds import router as feed_router
from .settings_store import (
    DEFAULT_BLOSSOM_SERVERS,
    DEFAULT_NOSTR_RELAYS,
    SETTING_RANGES,
    all_settings,
    get_node_v4v_address,
    get_setting,
    is_node_v4v_address_locked,
    public_settings,
    set_setting,
)
from .style_registry import all_style_docs, all_style_ids, all_style_meta, is_known_style
from .styles import SCRIPT_PROMPT, STYLE_TEMPLATES
from .version import BASE_VERSION, DISPLAY_VERSION, GIT_REV, __version__

# Nostr auth (NIP-07 / NIP-46 / npub) - ensure tables exist on import
try:
    from .nostr_auth import ensure_nostr_tables

    ensure_nostr_tables()
except Exception:
    logger.warning("nostr tables init failed at import", exc_info=True)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    store.fail_interrupted()
    # ensure billing tables exist (DUE-067)
    try:
        from .billing import init_billing_db

        init_billing_db()
    except Exception:
        logger.warning("billing tables init failed at startup", exc_info=True)
    # ensure watchlist table exists (same DB)
    try:
        from .watchlist import init_watchlist_db

        init_watchlist_db()
    except Exception:
        logger.warning("watchlist tables init failed at startup", exc_info=True)
    # ensure custom styles table exists (same DB)
    try:
        from .custom_styles import init_custom_styles_db

        init_custom_styles_db()
    except Exception:
        logger.warning("custom styles tables init failed at startup", exc_info=True)
    # source tray objects (VOZONDA-MULTI-SOURCE-TRAY): tables + hourly purge of unused ones
    purge_task: asyncio.Task | None = None
    try:
        from .sources import init_sources_db, purge_loop

        init_sources_db()
        purge_task = asyncio.create_task(purge_loop())
    except Exception:
        logger.warning("sources tables init failed at startup", exc_info=True)
    # start watchlist poller background task
    poll_task: asyncio.Task | None = None
    try:
        from .watchlist_poller import start_poller

        poll_task = asyncio.create_task(start_poller(store, tasks, listeners))
    except Exception:
        logger.warning("watchlist poller failed to start", exc_info=True)
        poll_task = None
    # warm the doctor cache in the background so the first /doctor request
    # is instant (the probe runs a subprocess import, seconds of work)
    async def _warm_doctor() -> None:
        global _doctor_cache, _doctor_cache_time
        try:
            _doctor_cache = await asyncio.to_thread(run_doctor)
            _doctor_cache_time = __import__("time").monotonic()
        except Exception:
            logger.debug("doctor cache warmup failed", exc_info=True)

    asyncio.create_task(_warm_doctor())
    # discover and register pipeline plugins (providers with META)
    from .plugins import registry as _plugin_registry

    _plugin_registry.discover()
    yield
    if purge_task is not None:
        purge_task.cancel()
    if poll_task is not None:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Vozonda", version=__version__, lifespan=_lifespan)
# Single-job concurrency gate - GPU/CPU resources on sparki are shared
_job_semaphore = asyncio.Semaphore(1)
_cors_env = env("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] or [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def remote_access(request: Request, call_next):
    """Deny remote requests by default; local use stays open (see access.py, GHSA-crq5-73gf-fv2h)."""
    remote = access.is_remote(request)
    authed = access.is_authed(request)
    access.request_remote.set(remote)
    access.request_authed.set(authed)
    if not remote or authed or request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    if access.is_public_path(path) or access.is_feed_path(path):
        return await call_next(request)
    ref = access.episode_ref(path) if request.method in ("GET", "HEAD") else None
    if ref is not None:
        if access.episode_media_allowed(request, ref):
            return await call_next(request)
        return JSONResponse({"detail": "not found"}, status_code=404)
    if env("ENABLE_BILLING", "false").strip().lower() == "true" and (
        path.startswith("/billing/") or request.headers.get("authorization")
        or "token" in request.query_params or "access_token" in request.query_params
    ):
        return await call_next(request)  # billing routes and customers' access tokens: the route checks them
    if not access.token():
        return JSONResponse({"detail": "remote access needs VOZONDA_TOKEN: set it, then sign in"}, status_code=503)
    return JSONResponse({"detail": "missing or invalid token"}, status_code=401)


class SessionIn(BaseModel):
    token: str


@app.get("/update-check")
async def update_check() -> dict:
    """Whether a newer release exists (checked against GitHub at most every six hours; setting
    update.check = "0" turns it off) and the command that installs it."""
    from . import updates

    return await updates.check()


@app.get("/auth/session")
async def session_status(request: Request) -> dict:
    """Whether this browser is signed in, and whether it has to be (the web UI asks on load)."""
    remote = access.is_remote(request)
    return {
        "authenticated": access.is_authed(request),
        "required": remote or bool(access.token()),
        "token_configured": bool(access.token()),
    }


@app.post("/auth/session")
async def session_login(body: SessionIn, request: Request) -> JSONResponse:
    """Exchange VOZONDA_TOKEN for an HttpOnly session cookie, so the web UI, its audio player and live
    updates are authorised without sending the token on every request."""
    tok = access.token()
    if not tok:
        raise HTTPException(503, "no VOZONDA_TOKEN configured")
    if not hmac.compare_digest(body.token.strip().encode(), tok.encode()):
        raise HTTPException(401, "wrong token")
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
    resp = JSONResponse({"ok": True})
    resp.set_cookie(access.SESSION_COOKIE, access.session_value(tok), max_age=access.SESSION_MAX_AGE,
                    httponly=True, samesite="strict", secure=https, path="/")
    return resp


@app.delete("/auth/session")
async def session_logout() -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(access.SESSION_COOKIE, path="/")
    return resp

store = JobStore()
tasks: dict[str, asyncio.Task] = {}
listeners: dict[str, list[asyncio.Queue]] = {}


class JobSourceIn(BaseModel):
    """One card of the source tray, as a job is started with it."""

    id: str = Field(description="source id from POST /sources or POST /sources/upload")
    role: str = Field(default="main", description="main (carries the episode) or context (background)")


class JobIn(BaseModel):
    """Input parameters for creating a new audio-overview episode."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://example.com/article",
                "style": "balanced",
                "format": "dialog",
                "tone": "neutral",
                "language": "auto",
                "hosts": 2,
                "target_minutes": 10,
            }
        }
    )

    url: str | None = Field(
        default=None,
        description="URL of an article, blog post, or webpage to convert into an episode",
    )
    text: str | None = Field(
        default=None,
        description="Raw text content to convert (used when url is not provided)",
    )
    style: str = Field(
        default="balanced",
        description="Narrative style: balanced, analytical, entertaining, concise, story",
    )
    format: str = Field(
        default="dialog",
        description="Output format: dialog (multi-voice) or narration (single voice)",
    )
    tone: str = Field(
        default="neutral",
        description="Speaking tone: neutral, enthusiastic, serious, calm",
    )
    language: str = Field(
        default="auto",
        description="Output language code (e.g. de, en) or auto to detect from source",
    )
    hosts: int = Field(
        default=2,
        description="Number of voice hosts (1, 2, or 3)",
    )
    explicit: bool = Field(
        default=False,
        description="Allow explicit content in the script when source material requires it",
    )
    voice: dict | None = Field(
        default=None,
        description='Per-job voice profile ({"A": "timbre_name", "B": "timbre_name"})',
    )
    digest: bool = Field(
        default=False,
        description="Create a multi-source digest episode from digest_sources",
    )
    digest_sources: list[str] | None = Field(
        default=None,
        description="List of 2-10 URLs to combine into a digest episode (requires digest=True)",
    )
    research_mode: bool = Field(
        default=False,
        description="Auto-discover linked sources from the primary URL (2-10 URLs)",
    )
    access_token: str | None = Field(
        default=None,
        description="Billing access token required when the service is hosted with billing enabled",
    )
    show_name: str | None = Field(
        default=None,
        description="Podcast show name for RSS feed metadata",
    )
    show_author: str | None = Field(
        default=None,
        description="Podcast show author for RSS feed metadata",
    )
    show_category: str | None = Field(
        default=None,
        description="Podcast show category for RSS feed metadata",
    )
    target_minutes: float | None = Field(
        default=None,
        description="Desired episode length in minutes (1-60) or use length preset",
    )
    length: str | None = Field(
        default=None,
        description="Episode length preset (short, medium, long) as alternative to target_minutes",
    )
    focus: str | None = Field(
        default=None,
        description="What the hosts should dig into - steers emphasis, adds no facts",
    )
    review_script: bool = Field(
        default=False,
        description="Pause after script generation so the script can be reviewed and edited before voice",
    )
    combine: bool = Field(
        default=False,
        description="2+ sources: one conversation across them (compose default) instead of a digest",
    )
    callback_url: str | None = Field(
        default=None,
        description="Webhook URL where a POST notification is sent when the job completes",
    )
    sources: list[JobSourceIn] | None = Field(
        default=None,
        description="Source tray: ids from POST /sources (read and ready), each with a role "
        "(main carries the episode, context is background). Replaces url/text/digest_sources",
    )
    allow_cloud_for_uploads: bool = Field(
        default=False,
        description="The tray's uploaded files may be sent to a cloud script model. "
        "Without it, an episode with uploads is written by the local model only.",
    )

    @field_validator("language")
    @classmethod
    def _language_code(cls, v: str) -> str:
        """Store the code: the cast and voices key on it, the prompt only on the name.

        "German" used to pass through, giving a German script read by the
        English cast (2026-09-28).
        """
        from .pipeline import LANGUAGES

        key = (v or "auto").strip().lower()
        if key in LANGUAGES:
            return key
        by_name = {name.lower(): code for code, name in LANGUAGES.items() if code != "auto"}
        if key in by_name:
            return by_name[key]
        raise ValueError(f"language must be auto or one of {sorted(c for c in LANGUAGES if c != 'auto')} "
                         f"(or its English name), got {v!r}")

    @field_validator("callback_url")
    @classmethod
    def validate_callback_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if len(v) > 2048:
            raise ValueError("callback_url exceeds 2048 characters")
        from urllib.parse import urlparse

        p = urlparse(v)
        if p.scheme not in ("http", "https") or not p.netloc:
            raise ValueError("callback_url must have http or https scheme")
        return v


def _clean_voice(v: dict | None) -> dict:
    from .voices import normalize_voice

    return normalize_voice(v)


@app.get("/llms.txt", include_in_schema=False)
async def llms_txt() -> PlainTextResponse:
    """Machine-readable API overview for agents (llms.txt)."""
    p = Path(__file__).resolve().parent / "llms.txt"
    return PlainTextResponse(p.read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


def _write_auth_required() -> bool:
    """A token is mandatory once vozonda is reachable beyond localhost or bills money."""
    return access.install_exposed()


async def require_write_auth(authorization: str | None = Header(None)) -> None:
    """Mutating endpoints demand the VOZONDA_TOKEN bearer.

    Local single-user default (no token, loopback, billing off) stays open so the
    web UI, which sends no credentials, keeps working. Without a token but with
    billing on or a non-loopback bind it fails closed: before this, anyone who
    could reach the API could top up balances and mint access tokens.
    """
    token = env("TOKEN", "")
    if not token:
        # a request through a reverse proxy counts as remote too (GHSA-crq5-73gf-fv2h)
        if _write_auth_required() or access.request_remote.get():
            raise HTTPException(503, "write auth not configured: set VOZONDA_TOKEN")
        return
    if access.request_authed.get():  # the web UI's session cookie
        return
    if not hmac.compare_digest((authorization or "").encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, "missing or invalid token")


def _validate_access_token(access_token: str | None = None, request: Request | None = None) -> dict | None:
    """Validate access token and return user info if provided.

    Returns user info dict or None if no token or billing disabled.
    Raises HTTPException if token is invalid.
    
    Accepts token from:
    - access_token parameter (body or query)
    - ?token=... query parameter (simple bookmark fallback)
    - Authorization: Bearer header (checked by require_write_auth)
    """
    # Check query parameter fallback (?token=...) for simple bookmarks
    token = access_token
    if not token and request:
        token = request.query_params.get("token")
    
    if not token:
        return None

    if env("ENABLE_BILLING", "false").lower() != "true":
        return None

    try:
        from .billing import validate_token

        token_info = validate_token(token)
        return token_info
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).debug("billing validate_token failed: %s", e)
        raise HTTPException(401, "invalid or inactive access token")


def _check_watchlist_access(token_info: dict | None) -> str:
    """Check if user has watchlist access (hosted tier).
    
    Returns user_id if access granted.
    Raises HTTPException 402 if billing enabled but user lacks hosted tier.
    Returns None if no token or billing disabled (self-hosted = free access).
    """
    if not token_info:
        # No token provided - self-hosted users get free access
        return None
    
    user_id = token_info["user_id"]
    
    # Check if billing is enabled
    if env("ENABLE_BILLING", "false").lower() != "true":
        # Billing disabled - self-hosted, free access
        return None
    
    # Billing enabled - check tier
    try:
        from .billing import user_has_watchlist_access
        
        if not user_has_watchlist_access(user_id):
            raise HTTPException(
                402,
                "Watchlist is a Hosted tier feature. Upgrade your account to use watchlist automation. "
                "Manual episode creation (1:1) remains free. See #122 (Digest Mode) and #123 (Advanced Settings Gate)."
            )
    except HTTPException:
        raise
    except Exception:
        # If billing check fails, deny access for safety
        raise HTTPException(503, "Unable to verify watchlist access")
    
    return user_id


@app.get("/providers")
async def providers() -> dict:
    """List available TTS + LLM providers with health + installation status (#101, #237)."""
    from .providers import LLM_BASE, _probe_installed_engines, llm_fallbacks

    engines = _probe_installed_engines()

    # Probe LLM engine
    llm_installed = False
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{LLM_BASE}/models")
            llm_installed = r.status_code == 200 or bool(llm_fallbacks())
    except Exception:
        llm_installed = bool(llm_fallbacks())

    engines.append({
        "id": "local",
        "label": "Local model (your endpoint)",
        "installed": llm_installed,
        "fix": "set VOZONDA_LLM_BASE to your OpenAI-compatible endpoint",
    })

    active = [e for e in engines if e["installed"]]
    return {
        "providers": engines,
        "active": [e["id"] for e in active],
        "default": "qwen_tts" if active else None,
    }



def _tts_installed() -> dict[str, bool]:
    """Installed state of TTS engines, the same answer /providers gives.

    The plugin registry calls a plugin without probe() healthy, and most engine
    providers only define is_installed(); until 2026-09-25 the plugins drawer
    showed chatterbox and higgs as healthy with no venv on disk.
    """
    from . import providers as _providers

    try:
        return {e["id"]: bool(e.get("installed")) for e in _providers._probe_installed_engines()}
    except Exception:
        return {}


# A TTS plugin without META.renderer cannot be picked as voice engine
# (providers.tts_engines skips it), so the drawer must not call it healthy.
_NO_RENDERER_HINT = "stub without a renderer: cannot be selected as voice engine yet"


@app.get("/plugins")
async def list_plugins() -> dict:
    """List discovered plugins with metadata, health probe and enabled state (DUE-078)."""
    from .plugins import registry as _reg

    if len(_reg) == 0:
        _reg.discover()
    plugins: list[dict[str, object]] = []
    installed = _tts_installed()
    for pid in _reg.ids():
        try:
            meta = _reg.get(pid).META
        except KeyError:
            continue
        healthy = installed[pid] if pid in installed else await _reg.probe(pid)
        fix_hint = meta.ui_fix_hint
        if meta.kind.value == "tts_engine" and not meta.renderer:
            healthy, fix_hint = False, _NO_RENDERER_HINT
        plugins.append({
            "id": meta.id,
            "kind": meta.kind.value,
            "label": meta.label,
            "version": meta.version,
            "enabled": _reg.is_enabled(pid),
            "healthy": healthy,
            "ui_badge": meta.ui_badge,
            "ui_fix_hint": fix_hint,
            "permissions": sorted([p.value for p in meta.permissions]),
            "supports_instructions": meta.supports_instructions,
            "supports_emotion_instructions": meta.supports_emotion_instructions,
            "supports_paralinguistic_tags": meta.supports_paralinguistic_tags,
        })
    return {"plugins": plugins}


@app.post("/plugins/{plugin_id}/toggle", dependencies=[Depends(require_write_auth)])
async def toggle_plugin(plugin_id: str) -> dict:
    """Toggle a plugin enabled state (DUE-078)."""
    from .plugins import registry as _reg

    if len(_reg) == 0:
        _reg.discover()
    if not _reg.has(plugin_id):
        raise HTTPException(404, f"unknown plugin {plugin_id!r}")
    try:
        new_state = _reg.toggle(plugin_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    meta = _reg.get(plugin_id).META
    installed = _tts_installed()
    healthy = installed[plugin_id] if plugin_id in installed else await _reg.probe(plugin_id)
    if meta.kind.value == "tts_engine" and not meta.renderer:
        healthy = False
    return {
        "id": plugin_id,
        "enabled": new_state,
        "healthy": healthy,
        "label": meta.label,
        "kind": meta.kind.value,
    }


@app.get("/tts/engine")
async def get_tts_engine() -> dict:
    """Return the currently configured TTS engine (#124)."""
    from .settings_store import get_setting

    try:
        engine = get_setting("tts.engine") or "qwen_tts"
    except Exception:
        engine = "qwen_tts"
    return {"engine": engine}


@app.put("/tts/engine", dependencies=[Depends(require_write_auth)])
async def put_tts_engine(body: dict) -> dict:
    """Switch the TTS engine at runtime and invalidate the probe cache (#124)."""
    from .settings_store import SETTING_KEYS, get_setting, set_setting

    engine = str(body.get("value", ""))
    if "tts.engine" not in SETTING_KEYS:
        raise HTTPException(404, "unknown setting key: tts.engine")
    try:
        set_setting("tts.engine", engine)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    # Invalidate the doctor cache: clear the _probe_cache so the next
    # /providers call re-probes the system for the new engine.
    from .providers import _probe_cache

    _probe_cache.clear()

    return {"engine": get_setting("tts.engine")}


@app.get("/llm/engine")
async def get_llm_engine() -> dict:
    """Return the currently configured LLM engine (#237)."""
    from .settings_store import get_setting

    try:
        engine = get_setting("llm.engine") or "local"
    except Exception:
        engine = "local"
    return {"engine": engine}


@app.put("/llm/engine", dependencies=[Depends(require_write_auth)])
async def put_llm_engine(body: dict) -> dict:
    """Switch the LLM engine at runtime (#237)."""
    from .settings_store import SETTING_KEYS, get_setting, set_setting

    engine = str(body.get("value", ""))
    if "llm.engine" not in SETTING_KEYS:
        raise HTTPException(404, "unknown setting key: llm.engine")
    try:
        set_setting("llm.engine", engine)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    # Invalidate the doctor cache so the next /providers call re-probes.
    from .providers import _probe_cache

    _probe_cache.clear()

    return {"engine": get_setting("llm.engine")}


@app.get("/llm/models")
async def list_llm_models(engine: str) -> dict:
    """Model ids an engine offers right now, for the settings pickers.

    Asked live (opencode CLI, NIM /models) so a new or retired model shows up
    without a code change.
    """
    from .providers import NIM_BASE, nim_api_key, opencode_bin

    models: list[str] = []
    if engine == "opencode":
        exe = opencode_bin()
        if exe:
            proc = await asyncio.create_subprocess_exec(
                exe, "models", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            except TimeoutError:
                proc.kill()
                out = b""
            models = sorted({ln.strip() for ln in out.decode(errors="ignore").splitlines()
                             if ln.strip().startswith("opencode/")})
    elif engine == "kimi_nim":
        key = nim_api_key()
        if key:
            try:
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.get(f"{NIM_BASE}/models", headers={"Authorization": f"Bearer {key}"})
                models = sorted(m["id"] for m in r.json().get("data", []) if m.get("id"))
            except Exception:
                models = []
    else:
        raise HTTPException(422, "engine must be opencode or kimi_nim")
    return {"engine": engine, "models": models}


@app.get("/llm/probe", dependencies=[Depends(require_write_auth)])
async def probe_llm(
    engine: str | None = None,
    custom_base: str | None = None,
    custom_model: str | None = None,
    api_key: str | None = None,
    authorization: str | None = Header(None),
) -> dict:
    """Probe LLM endpoint dynamically from the server with live metadata (#237)."""
    import os as _os

    from .settings_store import SECRET_MASK, get_setting

    if api_key == SECRET_MASK:
        # The UI only holds the mask. Substitute the stored key, but never
        # toward a caller-chosen base URL: that would hand it to any server.
        stored_base = get_setting("llm.custom_base") or ""
        api_key = (get_setting("llm.api_key") or None) if not custom_base or custom_base == stored_base else None

    target_engine = engine or get_setting("llm.engine") or "local"
    if target_engine == "qwen_vllm":
        # pre-generic alias of 'local' (production still stores it)
        target_engine = "local"

    if target_engine == "none":
        return {
            "status": "none",
            "engine": "none",
            "installed": False,
            "badge": "Disabled",
            "label": "No LLM",
            "summary": "No local LLM engine is configured. Features requiring LLM inference will be unavailable.",
            "note": "Enable local to restore LLM capabilities.",
        }

    if target_engine in ("local", "custom"):
        from .providers import LLM_BASE, LLM_MODEL

        if target_engine == "local":
            base = LLM_BASE
            expected_model = LLM_MODEL
        else:
            base = custom_base or get_setting("llm.custom_base") or LLM_BASE
            expected_model = custom_model or get_setting("llm.custom_model") or LLM_MODEL
        best_for = ("Your own endpoint for private script writing "
                    "(Ollama, vLLM, LM Studio, llama.cpp).")
        # Probe OpenAI-compatible endpoint from the backend. The response
        # reports what the endpoint lists at /v1/models and makes no
        # hardware, quantization or speed claims: this is the user's setup,
        # not the operator's machine.
        models_url = f"{base}/models" if not base.endswith("/models") else base
        try:
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(models_url, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    models_list = data.get("data", [])
                    active_model = None
                    for m in models_list:
                        if m.get("id") == expected_model or not active_model:
                            active_model = m
                    model_id = active_model.get("id") if active_model else expected_model
                    model_ids = [m.get("id") for m in models_list if m.get("id")]
                    return {
                        "status": "ok",
                        "engine": target_engine,
                        "installed": True,
                        "location": "local",
                        "badge": f"Local model · {model_id}",
                        "label": "Local model (your endpoint)",
                        "model_id": model_id,
                        "models": model_ids,
                        "base": base,
                        "summary": (f"{model_id} via your OpenAI-compatible endpoint at {base}. "
                                    + (f"Also lists: {', '.join(model_ids[1:3])}. " if len(model_ids) > 1 else "")
                                    + "Check the endpoint for context and speed."),
                        "best_for": best_for,
                    }
                return {
                    "status": "offline",
                    "engine": target_engine,
                    "installed": False,
                    "location": "local",
                    "badge": "Local model · Offline",
                    "label": "Local model (your endpoint)",
                    "error": f"HTTP {r.status_code}",
                    "base": base,
                    "summary": (f"Your endpoint at {base} is not responding "
                                f"(HTTP {r.status_code}). Is it running?"),
                    "best_for": best_for,
                }
        except Exception as exc:
            return {
                "status": "offline",
                "engine": target_engine,
                "installed": False,
                "location": "local",
                "badge": "Local model · Offline",
                "label": "Local model (your endpoint)",
                "error": str(exc),
                "base": base,
                "summary": f"Your endpoint at {base} is unreachable. Is it running?",
                "best_for": best_for,
            }

    if target_engine == "kimi_nim":
        from .providers import nim_api_key, nim_model

        has_key, model = bool(nim_api_key()), nim_model()
        missing = [] if has_key else ["an NVIDIA NIM key (below, VOZONDA_NIM_API_KEY or secrets/nvidia_nim_api.key)"]
        if not model:
            missing.append("a model id (below or VOZONDA_NIM_MODEL)")
        return {
            "status": "unconfigured" if missing else "ok",
            "engine": "kimi_nim",
            "installed": not missing,
            "location": "cloud",
            "badge": f"NVIDIA NIM cloud · {model or 'no model chosen'}",
            "label": "NVIDIA NIM",
            "model_id": model,
            "provider": "NVIDIA NIM (cloud)",
            "summary": "A chat model on the NVIDIA NIM API. In the 2026-09-25 script bench Kimi K3 there followed "
                       "the dialog form (quick reactions, varied turns, natural German) where the local model "
                       "did not.",
            "best_for": "Livelier scripts from public sources. The source text is sent to NVIDIA's cloud; "
                        "shared queue, so it can be slow at peak times. The free developer key is for testing "
                        "and prototyping only; production use needs an NVIDIA AI Enterprise licence.",
            "note": ("Missing " + " and ".join(missing) + ".") if missing else "NIM key and model set.",
        }
    elif target_engine == "opencode":
        from .providers import opencode_bin, opencode_models

        found, models = bool(opencode_bin()), opencode_models()
        missing = [] if found else ["the opencode CLI (opencode.ai, or set VOZONDA_OPENCODE_BIN)"]
        if not models:
            missing.append("a model list (below or VOZONDA_OPENCODE_MODELS)")
        return {
            "status": "unconfigured" if missing else "ok",
            "engine": "opencode",
            "installed": not missing,
            "location": "cloud",
            "badge": f"OpenCode cloud · {models[0] if models else 'no model chosen'}",
            "label": "OpenCode",
            "model_id": ", ".join(models),
            "provider": "OpenCode via the local opencode CLI (cloud)",
            "summary": "Models offered by OpenCode, through your opencode CLI, tried in the listed order. "
                       "In the 2026-09-28 script bench big-pickle and mimo-v2.6-flash-free were the free "
                       "models that wrote full scripts in German and English.",
            "best_for": "A free cloud writer from public sources. The source text is sent to OpenCode and the "
                        "model providers; most free models may use it to improve their models and are offered "
                        "for a limited time. A script takes minutes.",
            "note": ("Missing " + " and ".join(missing) + ".") if missing else "opencode CLI and models set.",
        }
    elif target_engine == "claude":
        key = api_key or get_setting("llm.api_key") or _os.environ.get("ANTHROPIC_API_KEY", "")
        model_id = custom_model or get_setting("llm.custom_model") or "claude-3-7-sonnet-20250219"
        return {
            "status": "ok" if bool(key) else "unconfigured",
            "engine": "claude",
            "installed": bool(key),
            "badge": "Anthropic API · Claude 3.7 Sonnet",
            "label": "Claude 3.7 Sonnet / Haiku",
            "model_id": model_id,
            "provider": "Anthropic Cloud",
            "summary": "Frontier cloud model via Anthropic API. High fidelity script generation with extended thinking. Requires an active API key.",
            "best_for": "Maximum script quality when local models are insufficient. Pay-per-use pricing.",
            "note": "API key is active." if key else "Missing ANTHROPIC_API_KEY or api key in settings.",
        }
    raise HTTPException(422, f"unknown llm engine {target_engine!r}")



def _readable_id(url: str) -> str:
    import re as _re
    from urllib.parse import urlparse

    tail = urlparse(url).path.strip("/").split("/")[-1] or "episode"
    base = _re.sub(r"[^a-z0-9]+", "-", tail.lower()).strip("-")[:40] or "episode"
    # 12 hex digits (48 bits): an id must not be guessable from the title (GHSA-crq5-73gf-fv2h)
    return f"{base}-{uuid.uuid4().hex[:12]}"


@app.post(
    "/jobs",
    dependencies=[Depends(require_write_auth)],
    summary="Create a new audio overview episode",
    description=(
        "Submit a URL or text to be converted into a multi-voice podcast episode. "
        "Returns the job object with an id and initial state (queued). "
        "Poll GET /jobs/{id} or use the SSE events endpoint to wait for completion. "
        "Supports Idempotency-Key header for safe retries. "
        "Optional fields: style, format, tone, language, hosts, focus, digest, review_script, target_minutes. "
        "When billing is enabled, POST /jobs may return 402 with the price before processing."
    ),
)
async def create_job(
    request: Request,
    body: JobIn,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict:
    """Create a new audio overview job.

    Supports Idempotency-Key header (max 200 chars):
    If an Idempotency-Key header is supplied and matches a job created within the
    last 24 hours, the existing job JSON is returned immediately with status 200
    without creating a new job or scheduling rendering. If a request arrives with
    the same key but a different request body within 24 hours, it is treated the same
    and returns the existing job. If the key is older than 24 hours or not provided,
    a new job is created.
    """
    # Check Idempotency-Key header (VOZONDA-AGENT-2)
    clean_key: str | None = None
    raw_key = idempotency_key if idempotency_key is not None else request.headers.get("idempotency-key")
    if raw_key is not None:
        clean_key = raw_key.strip()
        if len(clean_key) > 200:
            raise HTTPException(422, "Idempotency-Key header must not exceed 200 characters")
        if clean_key:
            existing = store.get_idempotent_job(clean_key)
            if existing is not None:
                return existing

    # Validate callback_url if provided
    if body.callback_url:
        cb = body.callback_url.strip()
        if len(cb) > 2048:
            raise HTTPException(422, "callback_url must not exceed 2048 characters")
        from urllib.parse import urlparse

        from .fetcher import FetchError, guard_url

        p = urlparse(cb)
        if p.scheme not in ("http", "https") or not p.netloc:
            raise HTTPException(422, "callback_url must have http or https scheme")
        try:
            guard_url(cb)
        except FetchError as exc:
            raise HTTPException(422, f"callback_url rejected: {exc}") from exc

    from .fetcher import FetchError, guard_url

    # Source tray (VOZONDA-MULTI-SOURCE-TRAY): the sources were read when they were
    # added; the job uses exactly that text (one link keeps the url path for its cover
    # image) and keeps a copy in job_sources for variants and citations
    tray: list[dict] | None = None
    local_only = False
    if body.sources is not None:
        from .sources import TrayError, resolve_for_job

        if body.url or body.text or body.digest_sources:
            raise HTTPException(422, "use sources, or url/text/digest_sources, not both")
        try:
            tray = resolve_for_job([s.model_dump() for s in body.sources])
        except TrayError as exc:
            raise HTTPException(exc.status, exc.message) from None
        # VOZONDA-TRAY-PRIVACY: an uploaded file (no origin_url, not a note) is
        # written by the local model unless the tray allowed the cloud
        if not body.allow_cloud_for_uploads and any(
            s.get("origin_url") is None and s.get("kind") != "note" for s in tray
        ):
            local_only = True
        if len(tray) == 1 and tray[0]["kind"] == "article" and tray[0].get("origin_url"):
            body.url = tray[0]["origin_url"]
        elif len(tray) == 1:
            body.text = tray[0]["text"]
        else:
            body.digest = True
            # the digest stage reads the first line of a text source as its title; a note
            # already starts with it
            body.digest_sources = [
                "text:" + (t if t.startswith(s["title"]) else f"{s['title']}\n{t}")
                for s in tray
                for t in [s["text"][:100000]]
            ]

    # Mixed sources: when both url and text are provided on a standard job,
    # create a 2-source combined digest job (combine mode)
    if body.url and body.url.strip() and body.text and body.text.strip():
        txt = body.text.strip()
        if len(txt) < 20:
            raise HTTPException(422, "pasted text too short (min 20 chars)")
        if len(txt) > 100000:
            raise HTTPException(422, "pasted text too long (max 100000 chars)")
        try:
            guard_url(body.url.strip())
        except FetchError as exc:
            raise HTTPException(422, f"invalid url: {exc}") from exc
        body.digest = True
        body.combine = True
        body.digest_sources = [body.url.strip(), f"text:{txt}"]

    # DUE-066: accept {text} when url is absent; plain pasted article
    # digest (#122): digest_sources replaces url/text when digest=True
    
    # Validate access token if provided (DUE-067: billing support)
    token_info = _validate_access_token(body.access_token, request)
    user_id = token_info["user_id"] if token_info else None

    # VOZONDA-LEN-1: resolve precise length (explicit minutes or preset)
    target_minutes: float | None = None
    if body.target_minutes is not None or body.length is not None:
        from .length import LENGTH_PRESETS, MAX_MINUTES, MIN_MINUTES

        if body.target_minutes is not None:
            target_minutes = float(body.target_minutes)
            if not (MIN_MINUTES <= target_minutes <= MAX_MINUTES):
                raise HTTPException(422, "target_minutes must be between 1 and 60")
        else:
            preset = str(body.length or "").strip().lower()
            if preset not in LENGTH_PRESETS:
                raise HTTPException(422, f"length must be one of {sorted(LENGTH_PRESETS)}")
            target_minutes = LENGTH_PRESETS[preset]
    
    if body.digest:
        sources = body.digest_sources or []
        from .budget import max_sources as _tray_max_sources

        _tray_limit = _tray_max_sources()
        if len(sources) < 2 or len(sources) > _tray_limit:
            raise HTTPException(422, f"digest requires 2-{_tray_limit} digest_sources")
        from .fetcher import FetchError, guard_url
        _TEXT_RE = __import__("re").compile(r"^text:", __import__("re").IGNORECASE)
        clean_sources: list[str] = []
        for src in sources:
            s = src.strip()
            if _TEXT_RE.match(s):
                raw_text = s[5:]
                if len(raw_text) < 20:
                    raise HTTPException(422, "text source too short (min 20 chars)")
                if len(raw_text) > 100000:
                    raise HTTPException(422, "text source too long (max 100000 chars)")
                clean_sources.append(s)
            elif __import__("re").match(r"^https?://", s, __import__("re").IGNORECASE):
                try:
                    guard_url(s)
                except FetchError as exc:
                    raise HTTPException(422, f"invalid source url: {exc}") from exc
                clean_sources.append(s)
            else:
                if len(s) < 20:
                    raise HTTPException(422, "text source too short (min 20 chars)")
                if len(s) > 100000:
                    raise HTTPException(422, "text source too long (max 100000 chars)")
                clean_sources.append(f"text:{s}")
        if not is_known_style(body.style):
            raise HTTPException(422, f"unknown style '{body.style}'")
        if body.format not in ("dialog", "narration"):
            raise HTTPException(422, "format must be dialog or narration")
        if body.hosts not in (1, 2, 3):
            raise HTTPException(422, "hosts must be 1, 2, or 3")
        if body.review_script and not body.combine:
            raise HTTPException(422, "script review works for one conversation, not for a digest")
        job_id = f"digest-{uuid.uuid4().hex[:12]}"
        # url field holds a stable identifier for this digest; not fetched directly
        digest_url = f"digest:{job_id}"
        job = store.create(
            job_id,
            digest_url,
            body.style,
            body.format,
            body.tone,
            body.language,
            hosts=int(body.hosts),
            explicit=bool(body.explicit),
            voice=_clean_voice(body.voice) or None,
            digest=True,
            digest_sources=clean_sources,
            research_mode=bool(body.research_mode),
            user_id=user_id,
            access_token_id=token_info.get("token_id") if token_info else None,
            show_name=(body.show_name or "").strip()[:80] or None,
            show_author=(body.show_author or "").strip()[:80] or None,
            show_category=(body.show_category or "").strip()[:60] or None,
            show_slug=_show_index_for(body.show_name),
            target_minutes=target_minutes,
            focus=body.focus,
            review_script=bool(body.review_script),
            combine=bool(body.combine),
            callback_url=body.callback_url,
            public_base=str(request.base_url).rstrip("/"),
            local_only=local_only,
        )
        if tray:
            from .sources import save_job_sources

            save_job_sources(job_id, tray)
        if clean_key:
            store.set_idempotent_key(clean_key, job_id)
        listeners[job_id] = []
        tasks[job_id] = asyncio.create_task(_run(job_id))
        return job

    # Single-source path (url only or text only)
    source: str | None = None
    if body.text and body.text.strip():
        txt = body.text.strip()
        if len(txt) < 20:
            raise HTTPException(422, "pasted text too short (min 20 chars)")
        source = txt
    elif body.url and body.url.strip():
        source = body.url.strip()
    else:
        raise HTTPException(422, "provide url or text")
    if body.hosts not in (1, 2, 3):
        raise HTTPException(422, "hosts must be 1, 2, or 3")
    if not is_known_style(body.style):
        raise HTTPException(422, f"unknown style '{body.style}'")
    if body.format not in ("dialog", "narration"):
        raise HTTPException(422, "format must be dialog or narration")
    if body.review_script and body.research_mode:
        raise HTTPException(422, "script review works for a single source for now")
    # readable id: for text use pasted-text prefix
    if body.text and source == body.text.strip():
        job_id = f"pasted-{uuid.uuid4().hex[:12]}"
    else:
        job_id = _readable_id(source)
    job = store.create(
        job_id,
        source,
        body.style,
        body.format,
        body.tone,
        body.language,
        hosts=int(body.hosts),
        explicit=bool(body.explicit),
        voice=_clean_voice(body.voice) or None,
        research_mode=bool(body.research_mode),
        user_id=user_id,
        access_token_id=token_info.get("token_id") if token_info else None,
        target_minutes=target_minutes,
        focus=body.focus,
        review_script=bool(body.review_script),
        show_name=(body.show_name or "").strip()[:80] or None,
        show_author=(body.show_author or "").strip()[:80] or None,
        show_category=(body.show_category or "").strip()[:60] or None,
        show_slug=_show_index_for(body.show_name),
        callback_url=body.callback_url,
        public_base=str(request.base_url).rstrip("/"),
        local_only=local_only,
    )
    if tray:
        from .sources import save_job_sources

        save_job_sources(job_id, tray)
    if clean_key:
        store.set_idempotent_key(clean_key, job_id)
    listeners[job_id] = []
    tasks[job_id] = asyncio.create_task(_run(job_id))
    return job


async def _run(job_id: str, runner=run_job) -> None:
    async with _job_semaphore:
        async def emit(updated: dict) -> None:
            for q in listeners.get(job_id, []):
                await q.put(updated)

        try:
            async for updated in runner(store, job_id):
                await emit(updated)
                if updated["state"] in ("done", "failed", "awaiting_review"):
                    break
        except asyncio.CancelledError:
            # Kill all subprocesses for this job (renderer, ffmpeg, etc.)
            await _kill_job_subprocesses(job_id)
            # Clean up partial output files
            _cleanup_job_output_files(job_id)
            stage = store.get(job_id).get("current_stage") or "fetch"
            await emit(store.fail(job_id, stage, "cancelled"))
            raise
        except Exception as exc:
            stage = (store.get(job_id).get("current_stage") or "master")
            failed = store.fail(job_id, stage, str(exc))
            await emit(failed)
        finally:
            tasks.pop(job_id, None)


class ScriptReviewIn(BaseModel):
    # the reviewed script; omit to approve it unchanged
    lines: list[dict] | None = None
    # optional new title; when set, normalize whitespace, 1..120 chars
    title: str | None = None


_REVIEW_SPEAKERS = {"A", "B", "C", "Narrator"}


@app.post("/jobs/{job_id}/script", dependencies=[Depends(require_write_auth)])
async def approve_script(job_id: str, body: ScriptReviewIn) -> dict:
    """Approve (and optionally edit) a script paused for review, then voice it."""
    try:
        job = store.get(job_id)
    except KeyError:
        raise HTTPException(404, "job not found") from None
    if job.get("state") != "awaiting_review":
        raise HTTPException(409, f"job is {job.get('state')}, not waiting for a script review")
    
    script_edited = False
    if body.lines is not None:
        names = {ln.get("speaker"): ln.get("name") for ln in job.get("script") or [] if ln.get("name")}
        clean: list[dict] = []
        # citations only exist for a combined episode; edited values stay within 1..n
        n_src = len(job.get("digest_sources") or []) if job.get("combine") else None
        for ln in body.lines[:2000]:
            speaker = str(ln.get("speaker", "")).strip()
            if speaker not in _REVIEW_SPEAKERS:
                raise HTTPException(422, f"unknown speaker '{speaker}'")
            text = " ".join(str(ln.get("text", "")).split())[:4000]
            if not text:
                continue
            line = {"speaker": speaker, "text": text}
            if names.get(speaker):
                line["name"] = names[speaker]
            src = _clean_src(ln.get("src"), n_src)
            if src:
                line["src"] = src
            clean.append(line)
        if not clean:
            raise HTTPException(422, "the script is empty")
        store.update(job_id, script=clean)
        script_edited = clean != (job.get("script") or [])
        store.add_stage_meta(job_id, "script", reviewed=True, edited=script_edited)
    else:
        store.add_stage_meta(job_id, "script", reviewed=True, edited=False)
    
    if body.title is not None:
        normalized = " ".join(body.title.split())
        if not normalized or len(normalized) > 120:
            raise HTTPException(422, "title must be 1 to 120 characters")
        if normalized != (job.get("title") or "").strip():
            store.update(job_id, title=normalized)
            store.add_stage_meta(job_id, "script", title_edited=True)
    
    job = store.update(job_id, state="queued", script_approved=True)
    listeners.setdefault(job_id, [])
    tasks[job_id] = asyncio.create_task(_run(job_id, resume_after_review))
    return job


class JobRenameIn(BaseModel):
    title: str


@app.patch(
    "/jobs/{job_id}",
    dependencies=[Depends(require_write_auth)],
    summary="Rename an episode",
    description="Update the episode title. Works for any job state.",
)
async def rename_job(job_id: str, body: JobRenameIn) -> dict:
    try:
        store.get(job_id)
    except KeyError:
        raise HTTPException(404, "job not found") from None

    normalized = " ".join(body.title.split())
    if not normalized or len(normalized) > 120:
        raise HTTPException(422, "title must be 1 to 120 characters")

    store.update(job_id, title=normalized)
    updated = store.add_stage_meta(job_id, "script", title_edited=True)
    for q in listeners.get(job_id, []):
        await q.put(updated)
    return updated


@app.get(
    "/jobs",
    summary="List recent completed episodes",
    description=(
        "Return the most recently finished (done or failed) jobs with a summary view. "
        "Each job includes id, title, url, state, created_at, duration_ms, style, format, "
        "audio_url (for done jobs), and optional show metadata. "
        "Use ?limit=N to control the number of results returned (default 5)."
    ),
)
async def list_jobs(limit: int = 5) -> dict:
    import sqlite3

    from .jobs import DB_PATH

    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM jobs WHERE state IN ('done','failed') ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    # server-side recent dedupe: hide duplicate urls for done jobs (client did this)
    seen: set[str] = set()
    deduped = []
    for r in rows:
        if r["state"] == "done":
            url = r["url"]
            if url in seen:
                continue
            seen.add(url)
        deduped.append(r)
    return {
        "jobs": [
            {
                "id": r["id"],
                "title": r["title"] or r["url"],
                "url": r["url"],
                "state": r["state"],
                "created_at": r["created_at"],
                "duration_ms": r["duration_ms"],
                "style": r["style"],
                "format": r["format"],
                "language": r["language"],
                "description": r["description"] or "",
                "watchlist_id": r["watchlist_id"] if "watchlist_id" in r.keys() else None,  # noqa: SIM118 - sqlite3.Row needs .keys()
                "digest": bool(r["digest"]) if "digest" in r.keys() else False,  # noqa: SIM118
                "hosts": r["hosts"] if "hosts" in r.keys() else 2,  # noqa: SIM118
                "error": r["error"] if r["state"] == "failed" and "error" in r.keys() else "",  # noqa: SIM118
                "og_image": r["og_image"] if "og_image" in r.keys() else None,  # noqa: SIM118
                "audio_seconds": r["audio_seconds"] if "audio_seconds" in r.keys() else None,  # noqa: SIM118
                "show_name": r["show_name"] if "show_name" in r.keys() else "",  # noqa: SIM118
                "show_author": r["show_author"] if "show_author" in r.keys() else "",  # noqa: SIM118
                "show_category": r["show_category"] if "show_category" in r.keys() else "",  # noqa: SIM118
                "audio_url": f"/audio/{r['id']}.mp3" if r["state"] == "done" else None,
            }
            for r in deduped
        ]
    }


@app.get(
    "/jobs/{job_id}",
    summary="Get job details and current state",
    description=(
        "Retrieve the full job object including state, script, and audio metadata. "
        "State progresses through: queued, running, fetch, script, voice, master, "
        "done, or failed. When state is done, audio_url points to /audio/{id}.mp3. "
        "Also includes stage metadata with timing and audio file facts."
    ),
)
async def get_job(job_id: str) -> dict:
    try:
        job = store.get(job_id)
    except KeyError:
        raise HTTPException(404, "no such job") from None

    # audio facts (size, bitrate, sample rate) are probed once after master
    # finishes and cached in the stage meta; older jobs pick them up lazily
    stages = {s["name"]: s for s in job.get("stages", [])} if isinstance(
        job.get("stages"), list
    ) else job.get("stages", {})
    if job.get("state") == "done":
        audio = (stages.get("master", {}).get("meta") or {}).get("audio")
        mp3 = Path(MEDIA_DIR) / f"{job_id}.mp3"
        if not audio and mp3.exists():
            try:
                import asyncio
                import json as _json

                proc = await asyncio.create_subprocess_exec(
                    "ffprobe", "-v", "error",
                    "-show_entries",
                    "format=bit_rate,size:stream=sample_rate,channels",
                    "-of", "json", str(mp3),
                    stdout=asyncio.subprocess.PIPE,
                )
                out, _ = await proc.communicate()
                fmt = (_json.loads(out.decode() or "{}").get("format") or {})
                stream = (
                    _json.loads(out.decode() or "{}").get("streams") or [{}]
                )[0]
                store.add_stage_meta(job_id, "master", audio={
                    "bytes": int(fmt.get("size", 0)) or mp3.stat().st_size,
                    "kbps": round(int(fmt.get("bit_rate", 0)) / 1000),
                    "sample_rate": int(stream.get("sample_rate", 0)),
                })
                job = store.get(job_id)
            except Exception:
                logger.debug("audio meta probe failed for job %s", job_id, exc_info=True)
    if job.get("state") == "done" and not job.get("audio_url"):
        job["audio_url"] = f"/audio/{job_id}.mp3"
    return job


class SourceIn(BaseModel):
    """A link or a note for the source tray."""

    url: str | None = None
    text: str | None = None


class SourceTitleIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


def _source_or_404(source_id: str) -> dict:
    from . import sources as sources_mod

    src = sources_mod.get(source_id)
    if src is None:
        raise HTTPException(404, "no such source (unused sources expire after 24 h)")
    return src


def _source_error(exc: Exception) -> HTTPException:
    from .sources import ERRORS, SourceError

    code = exc.code if isinstance(exc, SourceError) else "unreadable"
    status = 413 if code == "too_large" else 415 if code == "unsupported_type" else 422
    if isinstance(exc, SourceError) and exc.detail:
        hint = exc.detail
    else:
        hint = ERRORS[code][0]
    return HTTPException(status, {"code": code, "hint": hint})


@app.post("/sources", status_code=202, dependencies=[Depends(require_write_auth)])
async def add_source(body: SourceIn) -> dict:
    """Add a link (read in the background, poll GET /sources/{id}) or a note (ready at once)."""
    from . import sources as sources_mod

    if bool(body.url and body.url.strip()) == bool(body.text and body.text.strip()):
        raise HTTPException(422, "send either url or text")
    try:
        if body.url and body.url.strip():
            return sources_mod.add_url(body.url)
        return sources_mod.add_note(body.text or "")
    except sources_mod.SourceError as exc:
        raise _source_error(exc) from None


@app.post("/sources/upload", status_code=202, dependencies=[Depends(require_write_auth)])
async def upload_source(request: Request) -> dict:
    """Upload one file as the raw request body (PDF, JPG, PNG, WebP, TXT, MD, audio).

    The type is taken from the bytes, not the name; the file is read in memory and only
    its extracted text is kept. No multipart, so nothing is spooled to disk.
    Audio uploads (MP3, WAV, Ogg/Opus, M4A, FLAC) may be up to VOZONDA_AUDIO_MAX_BYTES (100 MB);
    every other file is limited to 25 MB.
    """
    from . import sources as sources_mod

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > sources_mod.AUDIO_MAX_BYTES:
        raise HTTPException(413, {"code": "too_large", "hint": f"the file is larger than {sources_mod.AUDIO_MAX_BYTES // 1_000_000} MB (audio) or 25 MB (other files)."})
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > sources_mod.AUDIO_MAX_BYTES:
            raise HTTPException(413, {"code": "too_large", "hint": f"the file is larger than {sources_mod.AUDIO_MAX_BYTES // 1_000_000} MB (audio) or 25 MB (other files)."})
    if not buf:
        raise HTTPException(422, "empty upload")
    try:
        return sources_mod.add_upload(bytes(buf))
    except sources_mod.SourceError as exc:
        raise _source_error(exc) from None


@app.get("/sources/{source_id}", dependencies=[Depends(require_write_auth)])
async def get_source(source_id: str) -> dict:
    """A tray source: status reading/ready/failed, title, words, language, error hint."""
    return _source_or_404(source_id)


@app.patch("/sources/{source_id}", dependencies=[Depends(require_write_auth)])
async def rename_source(source_id: str, body: SourceTitleIn) -> dict:
    """Edit the title, e.g. before an upload's title shows up in public show notes."""
    from . import sources as sources_mod

    _source_or_404(source_id)
    return sources_mod.set_title(source_id, body.title)  # type: ignore[return-value]


@app.post("/sources/{source_id}/retry", status_code=202, dependencies=[Depends(require_write_auth)])
async def retry_source(source_id: str) -> dict:
    """Read a failed link again (an upload has to be uploaded again: its bytes are gone)."""
    from . import sources as sources_mod

    _source_or_404(source_id)
    try:
        return sources_mod.retry(source_id)  # type: ignore[return-value]
    except sources_mod.SourceError as exc:
        raise HTTPException(409, str(exc)) from None


@app.delete("/sources/{source_id}", dependencies=[Depends(require_write_auth)])
async def remove_source(source_id: str) -> dict:
    from . import sources as sources_mod

    if not sources_mod.delete(source_id):
        raise HTTPException(404, "no such source")
    return {"deleted": source_id}


@app.get("/jobs/{job_id}/sources")
async def list_job_sources(job_id: str) -> list[dict]:
    """The sources an episode was made from, as may be shown publicly: links with their
    URL, uploads and notes by title only."""
    from .sources import job_sources

    try:
        job = store.get(job_id)
    except KeyError:
        raise HTTPException(404, "no such job") from None
    return job_sources(job)


@app.post("/jobs/{job_id}/sources/clone", dependencies=[Depends(require_write_auth)])
async def clone_job_sources_endpoint(job_id: str) -> list[dict]:
    """create variant: fresh tray sources with the text this episode used (no re-fetch)."""
    from .sources import clone_job_sources

    try:
        job = store.get(job_id)
    except KeyError:
        raise HTTPException(404, "no such job") from None
    return clone_job_sources(job)


@app.get("/source/{job_id}")
async def job_source(job_id: str) -> Response:
    # the original source of an episode: urls redirect, pasted text is served
    try:
        job = store.get(job_id)
    except KeyError:
        raise HTTPException(404, "no such job") from None
    src = (job.get("url") or "").strip()
    if not src:
        raise HTTPException(404, "no source")
    if src.startswith(("http://", "https://")):
        return RedirectResponse(src)
    return PlainTextResponse(src)


@app.delete("/jobs/{job_id}", dependencies=[Depends(require_write_auth)])
async def cancel_job(job_id: str) -> dict:
    try:
        current = store.get(job_id)
    except KeyError:
        raise HTTPException(404, "no such job") from None

    task = tasks.pop(job_id, None)
    if task is not None and not task.done():
        task.cancel()

    if current["state"] in ("queued", "running"):
        stage = current.get("current_stage") or "fetch"
        cancelled = store.update(job_id, state="cancelled", stage=stage, status="failed", detail="cancelled")
        for q in listeners.pop(job_id, []):
            await q.put(cancelled)
        return {"cancelled": job_id}
    else:
        # already finished or failed - just remove
        for q in listeners.pop(job_id, []):
            await q.put(current)
        # a published episode is withdrawn from Nostr too (NIP-09 + BUD-02, best effort);
        # the show is captured now because the job row is about to go
        from .nostr_orchestrator import _event_ids_for_job, delete_published_job
        from .pipeline import _spawn_background

        if current.get("show_slug") and _event_ids_for_job(job_id):
            _spawn_background(delete_published_job(job_id, show_slug=current["show_slug"]))
        store.delete(job_id)
        from .sources import delete_job_sources

        delete_job_sources(job_id)
        # clean up any media files on disk for this job
        for p in MEDIA_DIR.glob(f"{job_id}*"):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                logger.debug("media cleanup failed for %s", p, exc_info=True)
        return {"deleted": job_id}


@app.get("/jobs/{job_id}/events")
async def job_events(job_id: str):
    try:
        store.get(job_id)
    except KeyError:
        raise HTTPException(404, "no such job") from None

    q: asyncio.Queue = asyncio.Queue()
    listeners.setdefault(job_id, []).append(q)

    async def stream():
        try:
            yield f"data: {json.dumps(store.get(job_id))}\n\n"
            while True:
                try:
                    updated = await asyncio.wait_for(q.get(), timeout=2.0)
                    yield f"data: {json.dumps(updated)}\n\n"
                    if updated["state"] in ("done", "failed", "cancelled"):
                        break
                except TimeoutError:
                    try:
                        current = store.get(job_id)
                    except KeyError:
                        break
                    if current["state"] in ("done", "failed", "cancelled"):
                        yield f"data: {json.dumps(current)}\n\n"
                        break
                    if current["state"] == "queued":
                        yield f"data: {json.dumps(current)}\n\n"
                    else:
                        yield ": keepalive\n\n"
        finally:
            try:
                listeners[job_id].remove(q)
            except (KeyError, ValueError):
                pass

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


_doctor_cache: dict | None = None
_doctor_cache_time: float = 0.0
_DOCTOR_TTL = 60  # seconds


@app.get("/doctor")
async def doctor(refresh: bool = False) -> dict:
    """Doctor diagnostics. The probe runs a subprocess import (seconds),
    so results are cached and warmed at startup; refresh=1 forces a rerun.
    Cache expires after 60s so a recovered backend surfaces without manual refresh."""
    global _doctor_cache, _doctor_cache_time
    now = __import__("time").monotonic()
    if _doctor_cache is None or refresh or (now - _doctor_cache_time > _DOCTOR_TTL):
        _doctor_cache = run_doctor()
        _doctor_cache_time = now
    return _doctor_cache




# GIT_REV is imported from .version


def _timbres() -> list[dict]:
    """Speaker choices of the engine that will actually render the audio.

    Plain data from voices.SPEAKER_TABLES so the api never imports torch;
    a non-qwen renderer registers its own table and ships its own voices.
    """
    engine = env("RENDERER", "qwen_tts")
    try:
        from .settings_store import get_setting

        stored = get_setting("tts.engine")
        if stored:
            engine = stored
    except Exception:
        logger.debug("tts engine setting lookup failed in _timbres", exc_info=True)
    try:
        from .voices import SPEAKER_TABLES

        return SPEAKER_TABLES.get(engine, SPEAKER_TABLES.get("qwen_tts", []))
    except ImportError:
        return []


def _default_timbre_for(engine: str = "qwen_tts") -> dict:
    """Per-language per-role default timbres (DUE-041) for the active engine."""
    from .voices import default_cast_for

    return default_cast_for(engine)


@app.get(
    "/meta",
    summary="Service metadata and configuration",
    description=(
        "Return available styles, tone options, language codes, voice timbres, "
        "TTS and LLM engine info, and runtime configuration. "
        "Useful for agents to discover valid values for style, language, hosts, "
        "and voice profile fields before submitting a job."
    ),
)
async def meta() -> dict:
    engine = env("RENDERER", "qwen_tts")
    try:
        from .settings_store import get_setting

        stored = get_setting("tts.engine")
        if stored:
            engine = stored
    except Exception:
        logger.debug("tts engine setting lookup failed in meta", exc_info=True)

    # LLM engine from settings, fallback to env label
    llm_engine = "local"
    llm_label = env("LLM_LABEL", "local model (your endpoint)")
    try:
        from .settings_store import get_setting as gs

        stored_llm = gs("llm.engine")
        if stored_llm:
            llm_engine = stored_llm
            if stored_llm in ("local", "qwen_vllm"):
                llm_engine = "local"
                llm_label = env("LLM_LABEL", "local model (your endpoint)")
            elif stored_llm == "kimi_nim":
                from .providers import nim_model

                llm_label = f"{nim_model() or 'no model'} (nvidia nim, cloud)"
            elif stored_llm == "opencode":
                from .providers import opencode_models

                llm_label = f"{(opencode_models() or ['no model'])[0]} (opencode, cloud)"
            elif stored_llm == "claude":
                llm_label = "claude-3.7-sonnet"
            elif stored_llm == "custom":
                llm_label = "custom-openai-compatible"
            elif stored_llm == "none":
                llm_label = "none"
    except Exception:
        logger.debug("llm label lookup failed in meta", exc_info=True)

    try:
        from .voices import all_speaker_tables

        tables = all_speaker_tables()
    except ImportError:
        tables = {}

    # VOZONDA-TRAY-PRIVACY: whether the script model writes on this machine.
    # The first provider of the unfiltered chain decides; the tray shows its
    # notice from this, not from a hardcoded model name.
    try:
        from .providers import LOCAL_ONLY as _local_only_flag
        from .providers import is_local_provider as _is_local_provider
        from .providers import llm_chain as _llm_chain

        _token = _local_only_flag.set(False)
        try:
            _chain = _llm_chain()
        finally:
            _local_only_flag.reset(_token)
        script_engine_local = bool(_chain) and _is_local_provider(_chain[0])
    except Exception:
        logger.debug("script engine locality lookup failed in meta", exc_info=True)
        script_engine_local = True

    return {
        "styles": all_style_ids(),
        "style_docs": all_style_docs(),
        "style_meta": all_style_meta(),
        "version": DISPLAY_VERSION,
        "base_version": BASE_VERSION,
        "pep440_version": __version__,
        "git_rev": GIT_REV,
        "script_engine_local": script_engine_local,
        "write_auth": bool(env("TOKEN")),
        "limits": {
            "max_source_chars": _budget.source_budget_chars(),
            "max_sources": _budget.max_sources(),
            "max_parallel_jobs": 1,
            "setting_ranges": {k: list(v) for k, v in SETTING_RANGES.items()},
        },
        "runtime": {
            "tts_engine": engine,
            "llm": llm_label,
            "llm_engine": llm_engine,
        },
        "v4v": {
            "node_address": get_node_v4v_address() or get_setting("feed.app.address") or "",
            "node_locked": is_node_v4v_address_locked(),
        },
        "timbres": _timbres(),
        "speaker_tables": tables,
        "default_timbre_for": _default_timbre_for(engine),
        "emotions": EMOTIONS,
        "languages": LANGUAGES,
        "tones": TONES,
    }


@app.get("/settings")
async def settings() -> dict:
    return {
        "settings": public_settings(),
        "node_v4v_locked": is_node_v4v_address_locked(),
        "defaults": {
            "tts.engine": env("TTS_ENGINE", "").strip() or "qwen_tts",
            "voice.speed": "1.0",
            "voice.gap_ms": "380",
            "music.enabled": "1",
            "music.intro": "1",
            "music.outro": "1",
            "music.duck_db": "-12.0",
            "music.style": "auto",
            "source.research_depth": "direct",
            "script.use_names": "auto",
            "script.intro_hook": "0",
            "script.takeaways": "0",
            "script.review_default": "0",
            "script.default_minutes": "8",
            "feed.public": "0",
            "feed.creator.split": "70",
            "feed.source.split": "20",
            "feed.app.split": "10",
            "feed.creator.address": "",
            "feed.source.address": "",
            "feed.app.address": "",
            "watchlist.render_mode": "newest",
            "llm.engine": "local",
            "llm.backup_engine": "none",
            "llm.api_key": "",
            "llm.custom_base": "",
            "llm.custom_model": "",
            "llm.nim_model": "",
            "llm.opencode_models": "",
            "show.name": "",
            "show.description": "",
            "show.author": "",
            "show.category": "Technology",
            "player.default_speed": "1.0",
            "player.default_text_size": "normal",
            "player.karaoke": "1",
            "player.chapters": "0",
            "player.autoscroll": "follow",
            "player.boost_placement": "meta",
            "script.narration": NARRATION_PROMPT,
            **{f"script.style.{sid}": tpl for sid, tpl in STYLE_TEMPLATES.items()
               if sid != "balanced"},
            "script.balanced": SCRIPT_PROMPT,
            "disclosure.ai_label": "1",
            "nostr.publish_default": "0",
            "distribution.rss_default": "1",
            "nostr.relays": DEFAULT_NOSTR_RELAYS,
            "nostr.blossom_servers": DEFAULT_BLOSSOM_SERVERS,
        },
    }


@app.put("/settings/{key}", dependencies=[Depends(require_write_auth)])
async def put_setting(key: str, body: dict) -> dict:
    try:
        set_setting(key, str(body.get("value", "")))
    except KeyError as exc:
        raise HTTPException(404, "unknown setting key") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"key": key, "value": get_setting(key)}


# ---------------------------------------------------------------------------
# Podcast Shows (#232)
# ---------------------------------------------------------------------------

class ShowIn(BaseModel):
    name: str = ""
    author: str = ""
    category: str = ""
    slug: str | None = None  # auto-generated if empty


class ShowOut(BaseModel):
    slug: str
    name: str
    author: str
    category: str


def _list_shows() -> list[ShowOut]:
    """Read all user-defined shows from settings (show.N.*) and the default show."""
    from .settings_store import SETTING_KEYS, all_settings

    # Check if the dynamic show keys are registered; register them if not
    dynamic_keys = {"show.1.name", "show.1.author", "show.1.category"}
    if not dynamic_keys.issubset(SETTING_KEYS):
        # dynamic show keys are added on-demand; we read from all_settings instead
        pass

    from .settings_store import show_numbers

    shows: list[ShowOut] = []
    all_settings_dict = all_settings()

    # every numbered show, gaps included (a deleted show 1 used to hide all others)
    for i in show_numbers():
        shows.append(ShowOut(
            slug=f"s{i}",
            name=all_settings_dict[f"show.{i}.name"] or "",
            author=all_settings_dict.get(f"show.{i}.author", "") or "",
            category=all_settings_dict.get(f"show.{i}.category", "") or "",
        ))

    # Add the default/current show if it has a name
    default_name = all_settings_dict.get("show.name", "") or ""
    if default_name:
        shows.append(ShowOut(
            slug="default",
            name=default_name,
            author=all_settings_dict.get("show.author", "") or "",
            category=all_settings_dict.get("show.category", "") or "",
        ))

    # De-duplicate: keep last occurrence (latest is the "real" default)
    seen: set[str] = set()
    unique: list[ShowOut] = []
    for s in reversed(shows):
        if s.name and s.name not in seen:
            seen.add(s.name)
            unique.insert(0, s)

    return unique


def _register_show_keys(slug: str) -> None:
    """Register dynamic show keys so set_setting accepts them."""
    # We bypass the SETTING_KEYS check by using all_settings_dict + direct DB write


def _show_index_for(show_name: str | None) -> str | None:
    """The numbered show (settings show.<n>.*) a job belongs to, as '<n>', resolved once when
    the job is created. Shows are stored by number, so a slug derived from the name
    ('My Show' -> 'my-show') never matched show.<n>.nostr and opted-in shows would never
    publish (2026-10-02). No numbered show with that exact name: None (nothing is published)."""
    name = (show_name or "").strip().casefold()
    if not name:
        return None
    settings_now = all_settings()
    i = 1
    while settings_now.get(f"show.{i}.name"):
        if str(settings_now[f"show.{i}.name"]).strip().casefold() == name:
            return str(i)
        i += 1
    return None


def _get_show_slug() -> str:
    """A number no show ever had (a deleted show keeps its Nostr key: reusing the
    lowest free number let a new show publish as the old one)."""
    from .settings_store import next_show_number

    return str(next_show_number())


@app.get("/shows")
async def list_shows() -> dict:
    """List all user-defined shows (persistent, reusable show definitions)."""
    return {"shows": _list_shows()}


@app.post("/shows", dependencies=[Depends(require_write_auth)])
async def create_show(body: ShowIn) -> dict:
    """Create or update a persistent show definition."""

    # Truncate to limits
    name = (body.name or "").strip()[:80]
    author = (body.author or "").strip()[:80]
    category = (body.category or "").strip()[:60]

    if not name:
        raise HTTPException(422, "show name is required")

    # Determine slug: use provided slug or generate
    slug = body.slug or _get_show_slug()

    # Store as show.N.* settings
    show_num = slug.lstrip("s")
    try:
        idx = int(show_num)
    except (ValueError, TypeError):
        # a number no show ever had: a deleted show keeps its key (Nostr identity)
        from .settings_store import next_show_number

        idx = next_show_number()
        slug = str(idx)

    # Write directly to DB (bypass SETTING_KEYS validation for dynamic keys)
    conn = __import__("vozonda_api.settings_store", fromlist=["_conn"])._conn()
    db_settings: dict[str, str] = {
        f"show.{idx}.name": name,
        f"show.{idx}.author": author,
        f"show.{idx}.category": category,
    }
    # Only a NEW show takes the preset nostr.publish_default; saving an existing show
    # keeps its own switch (review F-3: re-saving used to overwrite it with the preset)
    if get_setting(f"show.{idx}.nostr") is None:
        db_settings[f"show.{idx}.nostr"] = get_setting("nostr.publish_default") or "0"
    # Only a NEW show takes the preset distribution.rss_default; saving an existing show
    # keeps its own switch
    if get_setting(f"show.{idx}.rss") is None:
        db_settings[f"show.{idx}.rss"] = get_setting("distribution.rss_default") or "1"
    for k, v in db_settings.items():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (k, v),
        )
    conn.commit()
    conn.close()

    # Return slug in s{N} format to match list_shows and feed URLs
    return {"slug": f"s{idx}", "name": name, "author": author, "category": category}


@app.put("/shows/{slug}", dependencies=[Depends(require_write_auth)])
async def update_show(slug: str, body: ShowIn) -> dict:
    """Update an existing show definition."""
    name = (body.name or "").strip()[:80]
    author = (body.author or "").strip()[:80]
    category = (body.category or "").strip()[:60]

    if not name:
        raise HTTPException(422, "show name is required")

    # Parse numeric index from slug (s1 -> 1, s2 -> 2, or bare number)
    show_num = slug.lstrip("s")
    try:
        idx = int(show_num)
    except (ValueError, TypeError):
        raise HTTPException(404, "show not found")

    # Verify the show exists
    from .settings_store import all_settings
    all_settings_dict = all_settings()
    if f"show.{idx}.name" not in all_settings_dict or not all_settings_dict.get(f"show.{idx}.name"):
        raise HTTPException(404, "show not found")

    # Update directly in DB
    conn = __import__("vozonda_api.settings_store", fromlist=["_conn"])._conn()
    for k, v in [(f"show.{idx}.name", name), (f"show.{idx}.author", author), (f"show.{idx}.category", category)]:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (k, v),
        )
    conn.commit()
    conn.close()

    return {"slug": slug, "name": name, "author": author, "category": category}


@app.delete("/shows/{slug}", dependencies=[Depends(require_write_auth)])
async def delete_show(slug: str) -> dict:
    """Delete a persistent show definition."""
    show_num = slug.lstrip("s")
    try:
        idx = int(show_num)
    except (ValueError, TypeError):
        raise HTTPException(404, "show not found")

    from .settings_store import _conn
    conn = _conn()
    for k in [f"show.{idx}.name", f"show.{idx}.author", f"show.{idx}.category", f"show.{idx}.nostr", f"show.{idx}.rss"]:
        conn.execute("DELETE FROM settings WHERE key = ?", (k,))
    conn.commit()
    conn.close()
    # the show's key is its Nostr identity: never deleted silently (review F-3)
    from .podcast_key import has_keypair

    if has_keypair(str(idx)):
        logger.info("show %s deleted; its Nostr key file is kept (it is the show's identity)", idx)

    return {"deleted": slug}


class WatchlistIn(BaseModel):
    feed_url: str
    style: str = "balanced"
    format: str = "dialog"
    language: str = "auto"
    hosts: int = 2
    explicit: bool = False
    voice: dict | None = None  # DUE-078 per-feed voice profile
    schedule: str | None = None
    schedule_tz: str = "UTC"
    show_slug: str = ""


def _normalize_watchlist_show(show_slug: str | None) -> str:
    """Numeric show number (settings show.<n>.*) for a watchlist, 'default', or '' = none.

    Accepts '1', 's1', or 'default'; 422 when the show does not exist.
    """
    from .settings_store import all_settings

    raw = (show_slug or "").strip()
    if not raw:
        return ""
    if raw.lower() == "default":
        settings_now = all_settings()
        if not settings_now.get("show.name"):
            raise HTTPException(422, "default show not configured")
        return "default"
    num = raw[1:] if raw[:1].lower() == "s" else raw
    if not num.isdigit():
        raise HTTPException(422, f"unknown show '{show_slug}'")
    settings_now = all_settings()
    if not settings_now.get(f"show.{num}.name"):
        raise HTTPException(422, f"unknown show '{show_slug}'")
    return num


@app.get("/watchlist")
async def list_watchlist(request: Request, access_token: str | None = None) -> dict:
    from .watchlist import list_watchlists
    
    # Check watchlist access (hosted tier required when billing enabled)
    token_info = _validate_access_token(access_token, request)
    _check_watchlist_access(token_info)

    return {"watchlist": list_watchlists()}


@app.get("/watchlist/{wid}")
async def get_watchlist_endpoint(wid: str, request: Request, access_token: str | None = None) -> dict:
    from .watchlist import get_watchlist

    token_info = _validate_access_token(access_token, request)
    _check_watchlist_access(token_info)

    try:
        return get_watchlist(wid)
    except KeyError:
        raise HTTPException(404, "no such watchlist") from None


@app.post("/watchlist", dependencies=[Depends(require_write_auth)])
async def create_watchlist(request: Request, body: WatchlistIn, access_token: str | None = None) -> dict:
    from .fetcher import FetchError, guard_url
    from .watchlist import create_watchlist as wl_create
    from .watchlist import validate_schedule, validate_timezone
    
    # Check watchlist access (hosted tier required when billing enabled)
    token_info = _validate_access_token(access_token, request)
    _check_watchlist_access(token_info)

    # validate feed_url via same SSRF guard as article fetch
    try:
        guard_url(body.feed_url)
    except FetchError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not is_known_style(body.style):
        raise HTTPException(422, f"unknown style '{body.style}'")
    if body.format not in ("dialog", "narration"):
        raise HTTPException(422, "format must be dialog or narration")
    if body.language not in LANGUAGES and body.language != "auto":
        raise HTTPException(422, f"unknown language '{body.language}'")
    if body.hosts not in (1, 2, 3):
        raise HTTPException(422, "hosts must be 1, 2, or 3")

    # validate schedule & timezone
    if body.schedule is not None:
        try:
            validated_schedule = validate_schedule(body.schedule)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    else:
        validated_schedule = None

    schedule_tz = body.schedule_tz or "UTC"
    try:
        validated_tz = validate_timezone(schedule_tz)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    validated_show = _normalize_watchlist_show(body.show_slug)

    try:
        wl = wl_create(body.feed_url.strip(), body.style, body.format, body.language, body.hosts, explicit=body.explicit, voice=_clean_voice(body.voice) or None, schedule=validated_schedule, schedule_tz=validated_tz, show_slug=validated_show)
    except Exception as exc:
        msg = str(exc).lower()
        if "unique" in msg or "already" in msg:
            raise HTTPException(409, "feed already watched") from exc
        raise HTTPException(422, str(exc)) from exc
    # With a schedule set, the poller stops rendering entries as they arrive.
    # Without a schedule, do an immediate pull.
    if not validated_schedule:
        try:
            import asyncio

            from .watchlist_poller import poll_single

            asyncio.create_task(poll_single(wl, store, tasks, listeners))
        except Exception:
            logger.warning("immediate watchlist poll failed for %s", wl.get("id"), exc_info=True)
    return wl


class WatchlistUpdate(BaseModel):
    enabled: bool | None = None
    voice: dict | None = None
    digest_mode: int | None = None
    digest_count: int | None = None
    style: str | None = None
    format: str | None = None
    language: str | None = None
    hosts: int | None = None
    explicit: bool | None = None
    schedule: str | None = None
    schedule_tz: str | None = None
    show_slug: str | None = None


@app.put("/watchlist/{wid}", dependencies=[Depends(require_write_auth)])
async def update_watchlist(wid: str, body: WatchlistUpdate, access_token: str | None = None) -> dict:
    from .watchlist import _UNSET, validate_schedule, validate_timezone
    from .watchlist import update_watchlist as wl_update
    
    # Check watchlist access (hosted tier required when billing enabled)
    token_info = _validate_access_token(access_token)
    _check_watchlist_access(token_info)

    # validate fields against the same rules as POST
    if body.style is not None and not is_known_style(body.style):
        raise HTTPException(422, f"unknown style '{body.style}'")
    if body.format is not None and body.format not in ("dialog", "narration"):
        raise HTTPException(422, "format must be dialog or narration")
    if body.language is not None and body.language not in LANGUAGES and body.language != "auto":
        raise HTTPException(422, f"unknown language '{body.language}'")
    if body.hosts is not None and body.hosts not in (1, 2, 3):
        raise HTTPException(422, "hosts must be 1, 2, or 3")

    validated_schedule = _UNSET
    if "schedule" in body.model_fields_set:
        if body.schedule is not None:
            try:
                validated_schedule = validate_schedule(body.schedule)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        else:
            validated_schedule = None

    validated_tz = None
    if "schedule_tz" in body.model_fields_set:
        if body.schedule_tz is not None:
            try:
                validated_tz = validate_timezone(body.schedule_tz)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        else:
            validated_tz = "UTC"

    try:
        return wl_update(
            wid,
            enabled=body.enabled,
            voice=_clean_voice(body.voice) if body.voice is not None else None,
            digest_mode=body.digest_mode,
            digest_count=body.digest_count,
            style=body.style,
            format=body.format,
            language=body.language,
            hosts=body.hosts,
            explicit=body.explicit,
            schedule=validated_schedule,
            schedule_tz=validated_tz,
            show_slug=_normalize_watchlist_show(body.show_slug) if "show_slug" in body.model_fields_set else _UNSET,
        )
    except KeyError:
        raise HTTPException(404, "no such watchlist") from None


@app.delete("/watchlist/{wid}", dependencies=[Depends(require_write_auth)])
async def delete_watchlist(wid: str, access_token: str | None = None) -> dict:
    from .watchlist import delete_watchlist as wl_delete
    
    # Check watchlist access (hosted tier required when billing enabled)
    token_info = _validate_access_token(access_token)
    _check_watchlist_access(token_info)

    try:
        wl_delete(wid)
    except KeyError:
        raise HTTPException(404, "no such watchlist") from None
    return {"deleted": wid}


@app.post("/watchlist/{wid}/check", dependencies=[Depends(require_write_auth)])
async def check_watchlist_now(wid: str, access_token: str | None = None) -> dict:
    from .watchlist import get_watchlist
    from .watchlist_poller import poll_single
    
    # Check watchlist access (hosted tier required when billing enabled)
    token_info = _validate_access_token(access_token)
    _check_watchlist_access(token_info)

    try:
        wl = get_watchlist(wid)
    except KeyError:
        raise HTTPException(404, "no such watchlist") from None
    created = await poll_single(wl, store, tasks, listeners, is_manual=True)
    error = get_watchlist(wid).get("last_error")
    result: dict = {"checked": wid, "created": created}
    if error:
        result["error"] = error
    return result


# ---------------------------------------------------------------------------
# Custom user styles (VOZONDA-CUSTOM-STYLES-API)
# ---------------------------------------------------------------------------

class CustomStyleIn(BaseModel):
    id: str = ""
    name: str = ""
    doc: str = ""
    role_a: str = ""
    role_b: str = ""
    tone: str = ""
    rhythm_type: str = ""


class CustomStyleUpdate(BaseModel):
    name: str | None = None
    doc: str | None = None
    role_a: str | None = None
    role_b: str | None = None
    tone: str | None = None
    rhythm_type: str | None = None


@app.get("/styles/custom")
async def list_custom_styles() -> dict:
    """List the user's custom styles (built-ins live in GET /meta)."""
    from .custom_styles import list_custom_styles as _list

    return {"styles": _list()}


@app.post("/styles/custom", dependencies=[Depends(require_write_auth)])
async def create_custom_style(body: CustomStyleIn) -> dict:
    """Create a custom style: pick a rhythm type and name the two roles."""
    from .custom_styles import create_custom_style as _create

    try:
        return _create(
            body.id, body.name, body.doc, body.role_a, body.role_b, body.tone, body.rhythm_type
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.put("/styles/custom/{style_id}", dependencies=[Depends(require_write_auth)])
async def update_custom_style(style_id: str, body: CustomStyleUpdate) -> dict:
    """Update a custom style. Built-in ids cannot be taken or overridden."""
    from .custom_styles import update_custom_style as _update
    from .custom_styles import validate_style_id

    try:
        validate_style_id(style_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        return _update(
            style_id,
            name=body.name,
            doc=body.doc,
            role_a=body.role_a,
            role_b=body.role_b,
            tone=body.tone,
            rhythm_type=body.rhythm_type,
        )
    except KeyError:
        raise HTTPException(404, "no such custom style") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.delete("/styles/custom/{style_id}", dependencies=[Depends(require_write_auth)])
async def delete_custom_style(style_id: str) -> dict:
    """Delete a custom style. Jobs already made with it render with balanced."""
    from .custom_styles import delete_custom_style as _delete
    from .custom_styles import validate_style_id

    try:
        validate_style_id(style_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        _delete(style_id)
    except KeyError:
        raise HTTPException(404, "no such custom style") from None
    return {"deleted": style_id}


@app.post("/watchlist/{wid}/digest", dependencies=[Depends(require_write_auth)])
async def render_watchlist_digest(wid: str) -> dict:
    """Bundle the newest unrendered feed entries into one digest job (#122).

    Delegates to trigger_watchlist_digest for shared fetch/candidate logic.
    Keeps HTTP behaviour: 404, 502, 422 texts.
    """
    from .watchlist import get_watchlist
    from .watchlist_poller import trigger_watchlist_digest

    try:
        wl = get_watchlist(wid)
    except KeyError:
        raise HTTPException(404, "no such watchlist") from None

    res = await trigger_watchlist_digest(
        wid,
        store,
        tasks,
        listeners,
        count=int(wl.get("digest_count") or 3),
        min_entries=2,
        is_scheduled=False,
    )
    if res is None:
        raise HTTPException(
            422,
            "not enough fresh entries for a digest (0 new, need 2). hit check now first or wait for new articles.",
        )
    return {"digest_job": res["digest_job"], "sources": res["sources"]}


def _public_base(request: Request) -> str:
    """Public address for share pages, OG tags and clip links: VOZONDA_PUBLIC_URL when set
    (needed behind a proxy that rewrites the host), else the address the request came in on.
    Never a hardcoded domain: every self-hosted install has its own (same rule as webhooks.py)."""
    return (env("PUBLIC_URL", "").strip() or str(request.base_url)).rstrip("/")

SHARE_TMPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · vozonda</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="audio.episode">
<meta property="og:site_name" content="vozonda">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{img}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{og_alt}">
<meta property="og:audio" content="{audio}">
<meta property="og:audio:type" content="audio/mpeg">
<meta property="og:audio:artist" content="{show_author}">
<meta property="og:audio:album" content="{show_name}">
<meta property="music:duration" content="{duration_iso}">
<meta name="twitter:card" content="player">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{img}">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "AudioObject",
  "name": "{title}",
  "description": "{desc}",
  "thumbnail": {{
    "@type": "ImageObject",
    "url": "{img}",
    "width": 1200,
    "height": 630
  }},
  "contentUrl": "{audio}",
  "encodingFormat": "audio/mpeg",
  "duration": "{duration_iso}",
  "uploadDate": "{created_at}",
  "publisher": {{
    "@type": "Organization",
    "name": "vozonda",
    "url": "{app_url}"
  }},
  "creator": {{
    "@type": "Person",
    "name": "{show_author}"
  }},
  "inLanguage": "{language}"
}}
</script>
<style>
  :root {{ --paper:#faf6ef; --ink:#1a1815; --soft:#6b655b; --line:#e4dccb; --green:#76b900; }}
  body {{ margin:0; background:var(--paper); color:var(--ink);
         font-family:'Source Serif 4',Georgia,serif; line-height:1.65; }}
  main {{ max-width:680px; margin:0 auto; padding:48px 24px; }}
  .kick {{ font-family:ui-monospace,Menlo,monospace; font-size:.75rem;
          letter-spacing:.05em; color:var(--green); }}
  h1 {{ font-size:1.9rem; line-height:1.2; margin:.4rem 0 .2rem; }}
  .meta {{ font-family:ui-monospace,Menlo,monospace; font-size:.75rem; color:var(--soft); }}
  audio {{ width:100%; margin:24px 0 8px; }}
  blockquote {{ margin:32px 0 0; padding-left:16px; border-left:2px solid var(--line); }}
  blockquote p {{ margin:12px 0; color:var(--soft); }}
  blockquote b {{ font-family:ui-monospace,Menlo,monospace; font-size:.7rem;
                 font-weight:400; letter-spacing:.04em; margin-right:8px; }}
  footer {{ margin-top:40px; padding-top:16px; border-top:1px solid var(--line);
           font-family:ui-monospace,Menlo,monospace; font-size:.78rem; }}
  a {{ color:inherit; }}
  .zap-row {{ margin: 24px 0 0; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; font-family: ui-monospace,Menlo,monospace; font-size: .78rem; }}
  .zap-btn {{ display: inline-flex; align-items: center; gap: 6px; background: var(--ink); color: var(--paper); border: 1px solid var(--ink); border-radius: 4px; padding: 8px 14px; cursor: pointer; font-family: ui-monospace,Menlo,monospace; font-size: .82rem; }}
  .zap-btn:hover {{ background: var(--green); border-color: var(--green); }}
  .zap-modal {{ position: fixed; inset: 0; background: rgba(26,24,21,.42); backdrop-filter: blur(2px); display: none; place-items: center; z-index: 50; padding: 16px; }}
  .zap-modal.open {{ display: grid; }}
  .zap-card {{ width: min(520px, 100%); background: var(--paper); border: 1px solid var(--line); border-radius: 6px; padding: 20px; display: grid; gap: 14px; box-shadow: 0 12px 32px rgba(0,0,0,.18); }}
  .zap-head {{ display: flex; justify-content: space-between; align-items: center; }}
  .zap-head h2 {{ margin: 0; font-family: ui-monospace,Menlo,monospace; font-size: .85rem; }}
  .zap-close {{ background: transparent; border: 1px solid var(--line); border-radius: 4px; padding: 4px 8px; cursor: pointer; font-family: ui-monospace,Menlo,monospace; }}
  .zap-chips {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .zap-chip {{ background: #f0ebe0; border: 1px solid var(--line); border-radius: 4px; padding: 6px 10px; cursor: pointer; font-family: ui-monospace,Menlo,monospace; }}
  .zap-chip.sel {{ background: var(--ink); color: var(--paper); border-color: var(--ink); }}
  .zap-text {{ width: 100%; font-family: ui-monospace,Menlo,monospace; border: 1px solid var(--line); border-radius: 4px; padding: 8px; }}
  .zap-invoice {{ font-family: ui-monospace,Menlo,monospace; font-size: .75rem; word-break: break-all; background: #f0ebe0; padding: 8px; border-radius: 4px; border: 1px solid var(--line); }}
  .zap-actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
  .zap-primary {{ background: var(--ink); color: var(--paper); border: 1px solid var(--ink); border-radius: 4px; padding: 8px 14px; cursor: pointer; font-family: ui-monospace,Menlo,monospace; }}
  .zap-primary:disabled {{ opacity: .5; }}
  .zap-wait {{ color: var(--soft); font-family: ui-monospace,Menlo,monospace; font-size: .75rem; }}
  .zap-ok {{ color: var(--green); font-family: ui-monospace,Menlo,monospace; }}
  .zap-err {{ color: #c53030; font-family: ui-monospace,Menlo,monospace; white-space: pre-wrap; }}
</style>
</head>
<body>
<main>
  <p class="kick">// vozonda</p>
  <h1>{title}</h1>
  <p class="meta">{meta_line}</p>
  <audio controls preload="metadata" src="{audio}"></audio>
  <p class="meta"><a href="{audio}">⬇ download mp3</a></p>
  {source_links}
  {zap_row}
  {teaser}
  <footer>
    Expressive audio overview, generated with sovereign AI. Open source, privacy-first.<br>
    {zap_footer}
  </footer>
</main>
{zap_modal}
<script>
(function() {{
  const modal = document.getElementById('zap-modal');
  const openBtn = document.getElementById('zap-open');
  const closeBtn = document.getElementById('zap-close');
  const chips = document.getElementById('zap-chips');
  const commentEl = document.getElementById('zap-comment');
  const countEl = document.getElementById('zap-count');
  const addrEl = document.getElementById('zap-addr');
  const sendBtn = document.getElementById('zap-send');
  const invoiceWrap = document.getElementById('zap-invoice-wrap');
  const invoiceEl = document.getElementById('zap-invoice');
  const waitEl = document.getElementById('zap-wait');
  const okEl = document.getElementById('zap-ok');
  const errEl = document.getElementById('zap-err');
  const copyBtn = document.getElementById('zap-copy');
  const weblnBtn = document.getElementById('zap-webln');
  const walletBtn = document.getElementById('zap-open-wallet');
  const resetBtn = document.getElementById('zap-reset');
  const lightningAddress = (addrEl && addrEl.textContent || '').trim();
  let sats = 500;
  let invoice = '';
  let relays = ['wss://relay.damus.io', 'wss://nos.lol'];
  let subSockets = [];

  function showModal() {{ modal.classList.add('open'); }}
  function hideModal() {{ modal.classList.remove('open'); }}
  openBtn && openBtn.addEventListener('click', showModal);
  closeBtn && closeBtn.addEventListener('click', hideModal);
  modal && modal.addEventListener('click', (e) => {{ if (e.target === modal) hideModal(); }});

  chips && chips.addEventListener('click', (e) => {{
    const t = e.target.closest('.zap-chip');
    if (!t) return;
    chips.querySelectorAll('.zap-chip').forEach(c => c.classList.remove('sel'));
    t.classList.add('sel');
    sats = parseInt(t.dataset.sats, 10) || 500;
    sendBtn.textContent = 'zap ' + sats + ' sats';
  }});
  commentEl && commentEl.addEventListener('input', () => {{ countEl.textContent = commentEl.value.length + '/300'; }});

  function setErr(msg) {{ errEl.textContent = msg; errEl.style.display = msg ? 'block' : 'none'; }}
  function setOk(show) {{ okEl.style.display = show ? 'block' : 'none'; }}

  function lnAddressToUrl(addr) {{
    const parts = addr.split('@');
    return 'https://' + parts[1] + '/.well-known/lnurlp/' + encodeURIComponent(parts[0]);
  }}

  async function fetchPayParams(addr) {{
    const url = lnAddressToUrl(addr);
    const r = await fetch(url);
    if (!r.ok) throw new Error('lnurl fetch HTTP ' + r.status);
    return await r.json();
  }}

  function buildZapTemplate(sender, recipient, msats, relaysList, content, lnurl) {{
    const tags = [['p', recipient], ['amount', String(msats)], ['relays'].concat(relaysList)];
    if (lnurl) tags.push(['lnurl', lnurl]);
    return {{ kind: 9734, created_at: Math.floor(Date.now()/1000), tags: tags, content: content || '' }};
  }}

  async function startZap() {{
    setErr(''); setOk(false);
    if (!lightningAddress || !lightningAddress.includes('@')) {{ setErr('no lightning address configured'); return; }}
    sendBtn.disabled = true;
    sendBtn.textContent = 'fetching lnurl...';
    try {{
      const params = await fetchPayParams(lightningAddress);
      if (!params.allowsNostr) throw new Error('LNURL allowsNostr false');
      if (!params.nostrPubkey) throw new Error('missing nostrPubkey');
      const msats = sats * 1000;
      if (msats < params.minSendable || msats > params.maxSendable) throw new Error('amount out of range');
      let zapJson;
      const text = commentEl.value || '';
      // try NIP-07 sign if available
      if (window.nostr && window.nostr.signEvent) {{
        try {{
          const pubkey = await window.nostr.getPublicKey();
          const tmpl = buildZapTemplate(pubkey, params.nostrPubkey, msats, relays, text, lightningAddress);
          const signed = await window.nostr.signEvent(tmpl);
          zapJson = JSON.stringify(signed);
        }} catch (e) {{
          const tmpl = buildZapTemplate('0'.repeat(64), params.nostrPubkey, msats, relays, text, lightningAddress);
          zapJson = JSON.stringify(tmpl);
        }}
      }} else {{
        const tmpl = buildZapTemplate('0'.repeat(64), params.nostrPubkey, msats, relays, text, lightningAddress);
        zapJson = JSON.stringify(tmpl);
      }}
      sendBtn.textContent = 'requesting invoice...';
      const cbUrl = new URL(params.callback);
      cbUrl.searchParams.set('amount', String(msats));
      cbUrl.searchParams.set('nostr', zapJson);
      if (text) cbUrl.searchParams.set('comment', text);
      const r2 = await fetch(cbUrl.toString());
      if (!r2.ok) throw new Error('callback HTTP ' + r2.status);
      const j2 = await r2.json();
      if (j2.status === 'ERROR') throw new Error(j2.reason || 'lnurl error');
      invoice = j2.pr;
      if (!invoice) throw new Error('missing pr');
      invoiceEl.textContent = invoice;
      invoiceWrap.style.display = 'grid';
      waitEl.style.display = 'block';
      sendBtn.textContent = 'waiting for receipt...';
      listenForReceipt(params.nostrPubkey);
      // try WebLN
      if (window.webln) {{
        try {{ await window.webln.enable(); }} catch {{}}
      }}
    }} catch (e) {{
      setErr(e.message || String(e));
      sendBtn.textContent = 'zap ' + sats + ' sats';
    }} finally {{
      sendBtn.disabled = false;
    }}
  }}

  function listenForReceipt(pubkey) {{
    // close old
    subSockets.forEach(s => {{ try {{ s.close(); }} catch {{}} }});
    subSockets = [];
    const subId = 'vozonda-pub-' + Math.random().toString(36).slice(2,6);
    const filter = {{ kinds: [9735], '#p': [pubkey] }};
    const req = JSON.stringify(['REQ', subId, filter]);
    relays.forEach(url => {{
      try {{
        const ws = new WebSocket(url);
        subSockets.push(ws);
        ws.onopen = () => {{ try {{ ws.send(req); }} catch {{}} }};
        ws.onmessage = (ev) => {{
          try {{
            const msg = JSON.parse(ev.data);
            if (Array.isArray(msg) && msg[0] === 'EVENT' && msg[1] === subId) {{
              setOk(true);
              waitEl.textContent = 'zap confirmed (kind 9735)';
              sendBtn.textContent = 'confirmed';
            }}
          }} catch {{}}
        }};
      }} catch {{}}
    }});
  }}

  sendBtn && sendBtn.addEventListener('click', startZap);
  copyBtn && copyBtn.addEventListener('click', async () => {{
    try {{ await navigator.clipboard.writeText(invoice); copyBtn.textContent = 'copied!'; setTimeout(()=> copyBtn.textContent='copy invoice', 1500); }} catch {{}}
  }});
  weblnBtn && weblnBtn.addEventListener('click', async () => {{
    if (!window.webln) {{ setErr('WebLN not available'); return; }}
    try {{ await window.webln.enable(); await window.webln.sendPayment(invoice); setOk(true); }} catch (e) {{ setErr(e.message || String(e)); }}
  }});
  walletBtn && walletBtn.addEventListener('click', () => {{ if (invoice) window.location.href = 'lightning:' + invoice; }});
  resetBtn && resetBtn.addEventListener('click', () => {{
    invoice = ''; invoiceEl.textContent=''; invoiceWrap.style.display='none'; waitEl.style.display='none'; setOk(false); setErr(''); sendBtn.textContent='zap '+sats+' sats';
    subSockets.forEach(s => {{ try {{ s.close(); }} catch {{}} }}); subSockets=[];
  }});
}})();
</script>
</body>
</html>"""


@app.get("/e/{job_id}", response_class=HTMLResponse)
async def share_page(job_id: str, request: Request):
    try:
        job = store.get(job_id)
    except KeyError:
        raise HTTPException(404, "no such episode") from None
    if job["state"] != "done":
        raise HTTPException(404, "not finished")
    title = job.get("title") or "untitled"
    lines = (job.get("script") or [])[:6]
    turns = len(job.get("script") or [])
    show_name = (job.get("show_name") or "").strip() or "vozonda"
    show_author = (job.get("show_author") or "").strip() or "vozonda"
    language = job.get("language") or "en"
    duration_ms = job.get("duration_ms")
    if duration_ms:
        total_secs = duration_ms / 1000
        total_mins, secs = divmod(total_secs, 60)
        hours, minutes = int(total_mins // 60), int(total_mins % 60)
        duration_iso = f"{hours:01d}:{minutes:02d}:{secs:05.2f}" if hours else f"{minutes:02d}:{secs:05.2f}"
    else:
        duration_iso = "PT0S"
    created_at = job.get("created_at")
    if created_at:
        try:
            created_at_iso = datetime.datetime.fromtimestamp(created_at, tz=datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            created_at_iso = ""
    else:
        created_at_iso = ""
    teaser = "<blockquote>" + "".join(
        f"<p><b>{htmllib.escape(l['speaker'])}</b>{htmllib.escape(l['text'][:280])}</p>"
        for l in lines
    ) + "</blockquote>" if lines else ""
    base = _public_base(request)
    # Rich OG image: prefer per-episode cover if available, else default
    og_img = job.get("og_image")
    if og_img:
        # og_image stored as filename under MEDIA_DIR, served via /img/
        img_url = f"{base}/img/{og_img}" if not og_img.startswith("http") else og_img
    else:
        img_url = f"{base}/og-default.png"
    # lightning address for zap (creator address from settings; empty if not set)
    try:
        from .settings_store import get_setting

        lightning_address = (get_setting("feed.creator.address") or "").strip()
    except Exception:
        lightning_address = ""
    esc_addr = htmllib.escape(lightning_address) if lightning_address else ""
    zap_row = """  <div class="zap-row" id="zap-row">
    <button type="button" class="zap-btn" id="zap-open">&#9889; zap the maker</button>
    <span class="meta">NIP-57 zap via LNURL, signed with NIP-07 or Amber, paid via WebLN</span>
  </div>""" if lightning_address else ""
    zap_footer = f'<a href="{base}"><strong>Make your own</strong></a> &middot; zap &#9889; {esc_addr}' if lightning_address else ""
    zap_modal = f"""<div class="zap-modal" id="zap-modal" role="dialog" aria-modal="true" aria-labelledby="zap-title">
  <div class="zap-card">
    <div class="zap-head">
      <h2 id="zap-title">zap this episode</h2>
      <button type="button" class="zap-close" id="zap-close">close</button>
    </div>
    <p class="meta">Send sats directly to the maker via NIP-57. LNURL fetch, kind 9734 signed, BOLT11 via WebLN or copy.</p>
    <div class="zap-chips" id="zap-chips" role="group" aria-label="Amount presets">
      <button type="button" class="zap-chip" data-sats="21">21 sats</button>
      <button type="button" class="zap-chip sel" data-sats="500">500 sats</button>
      <button type="button" class="zap-chip" data-sats="1000">1000 sats</button>
      <button type="button" class="zap-chip" data-sats="5000">5000 sats</button>
      <button type="button" class="zap-chip" data-sats="21000">21k sats</button>
    </div>
    <div>
      <label class="meta" for="zap-comment">comment (optional)</label>
      <input id="zap-comment" class="zap-text" placeholder="love this episode" maxlength="300" />
      <span class="meta" id="zap-count">0/300</span>
    </div>
    <div class="meta">to <span id="zap-addr">{esc_addr}</span></div>
    <div id="zap-invoice-wrap" style="display:none">
      <p class="meta">invoice</p>
      <code class="zap-invoice" id="zap-invoice"></code>
      <div class="zap-actions">
        <button type="button" class="zap-primary" id="zap-copy">copy invoice</button>
        <button type="button" class="zap-primary" id="zap-webln">pay with WebLN</button>
        <button type="button" class="zap-primary" id="zap-open-wallet">open wallet</button>
      </div>
      <p class="zap-wait" id="zap-wait" style="display:none">listening for kind 9735 receipt on relays...</p>
    </div>
    <p class="zap-ok" id="zap-ok" style="display:none">zap confirmed (kind 9735 seen)</p>
    <p class="zap-err" id="zap-err" style="display:none"></p>
    <div class="zap-actions">
      <button type="button" class="zap-primary" id="zap-send">zap 500 sats</button>
      <button type="button" class="zap-close" id="zap-reset">reset</button>
    </div>
  </div>
</div>""" if lightning_address else ""
    og_alt = f"Cover image for {htmllib.escape(title)} episode by {htmllib.escape(show_author)} on vozonda"
    source_links = "".join(
        f'<p class="meta">Source: <a href="{htmllib.escape(u, quote=True)}">{htmllib.escape(u)}</a></p>'
        for u in _job_source_urls(job)
    )
    # AI disclosure line for episode page
    disclosure_html = ""
    try:
        from .settings_store import get_setting as _getDisclosure

        if _getDisclosure("disclosure.ai_label") == "1":
            stages = {s["name"]: s for s in job.get("stages", [])} if isinstance(job.get("stages"), list) else job.get("stages", {})
            script_meta = stages.get("script", {}).get("meta", {}) if isinstance(stages.get("script"), dict) else {}
            voice_meta = stages.get("voice", {}).get("meta", {}) if isinstance(stages.get("voice"), dict) else {}
            llm_model = script_meta.get("llm_model") or script_meta.get("llm_provider") or "AI"
            tts_engine = voice_meta.get("engine") or "AI"
            disclosure = f"AI-generated: script by {llm_model}, voices by {tts_engine}."
            disclosure_html = f'<p class="meta">{htmllib.escape(disclosure)}</p>'
    except Exception:
        logger.debug("share page disclosure lookup failed for job %s", job_id, exc_info=True)

    return SHARE_TMPL.format(
        title=htmllib.escape(title),
        desc=htmllib.escape(f"{turns}-turn dialogue · two voices · self-hosted with vozonda"),
        url=f"{base}/e/{job_id}",
        img=img_url,
        # opened with the feed key (a private episode's link in the feed): the player needs it too
        audio=f"{base}/audio/{job_id}.mp3" + (f"?key={quote(request.query_params['key'])}"
                                              if request.query_params.get("key") else ""),
        meta_line=htmllib.escape(f"{turns} turns · 2 voices"),
        teaser=teaser + disclosure_html,
        source_links=source_links,
        app_url=base,
        zap_row=zap_row,
        zap_footer=zap_footer,
        zap_modal=zap_modal,
        show_name=htmllib.escape(show_name),
        show_author=htmllib.escape(show_author),
        og_alt=og_alt,
        duration_iso=duration_iso,
        created_at=created_at_iso,
        language=htmllib.escape(language),
    )


# Clip share page template (SEO: quote-driven title, semantic description)
CLIP_SHARE_TMPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="audio.episode">
<meta property="og:site_name" content="vozonda">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{img}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{og_alt}">
<meta property="og:audio" content="{audio}">
<meta property="og:audio:type" content="audio/mpeg">
<meta property="og:audio:artist" content="{show_author}">
<meta property="og:audio:album" content="{show_name}">
<meta property="music:duration" content="{duration_iso}">
<meta name="twitter:card" content="player">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{img}">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "AudioObject",
  "name": "{title}",
  "description": "{desc}",
  "thumbnail": {{
    "@type": "ImageObject",
    "url": "{img}",
    "width": 1200,
    "height": 630
  }},
  "contentUrl": "{audio}",
  "encodingFormat": "audio/mpeg",
  "duration": "{duration_iso}",
  "uploadDate": "{created_at}",
  "inLanguage": "{language}"
}}
</script>
<style>
  :root {{ --paper:#faf6ef; --ink:#1a1815; --soft:#6b655b; --line:#e4dccb; --green:#76b900; }}
  body {{ margin:0; background:var(--paper); color:var(--ink);
         font-family:'Source Serif 4',Georgia,serif; line-height:1.65; }}
  main {{ max-width:680px; margin:0 auto; padding:48px 24px; }}
  .kick {{ font-family:ui-monospace,Menlo,monospace; font-size:.75rem;
          letter-spacing:.05em; color:var(--green); }}
  h1 {{ font-size:1.9rem; line-height:1.2; margin:.4rem 0 .2rem; }}
  .meta {{ font-family:ui-monospace,Menlo,monospace; font-size:.75rem; color:var(--soft); }}
  audio {{ width:100%; margin:24px 0 8px; }}
  blockquote {{ margin:32px 0 0; padding-left:16px; border-left:2px solid var(--line); }}
  blockquote p {{ margin:12px 0; color:var(--soft); }}
  blockquote b {{ font-family:ui-monospace,Menlo,monospace; font-size:.7rem;
                 font-weight:400; letter-spacing:.04em; margin-right:8px; }}
  footer {{ margin-top:40px; padding-top:16px; border-top:1px solid var(--line);
           font-family:ui-monospace,Menlo,monospace; font-size:.78rem; }}
  a {{ color:inherit; }}
  .clip-badge {{ display:inline-block; background:var(--green); color:var(--paper);
                font-family:ui-monospace,Menlo,monospace; font-size:.65rem;
                padding:2px 6px; border-radius:3px; margin-left:8px; }}
</style>
</head>
<body>
<main>
  <p class="kick">// vozonda</p>
  <h1>{title} <span class="clip-badge">clip {turn_start}–{turn_end}</span></h1>
  <p class="meta">{meta_line}</p>
  <audio controls preload="metadata" src="{audio}"></audio>
  <p class="meta"><a href="{audio}">⬇ download clip mp3</a></p>
  <blockquote>{transcript}</blockquote>
  <footer>
    Clip from an episode generated with sovereign AI. Open source, privacy-first.<br>
    <a href="{app_url}"><strong>Make your own</strong></a> · <a href="{episode_url}">full episode</a>
  </footer>
</main>
</body>
</html>"""


@app.get("/e/{job_id}/clip/{clip_spec}", response_class=HTMLResponse)
async def clip_share_page(job_id: str, clip_spec: str, request: Request):
    """Serve share page for a specific transcript clip.

    Supports both legacy '/e/{id}/clip/{start}-{end}' and SEO
    '/e/{id}/clip/{start}-{end}-{slug}' where the slug is human-readable
    and ignored for lookup (regex extracts the two turn indices).
    """
    try:
        turn_start, turn_end, _slug = parse_clip_spec(clip_spec)
    except ValueError:
        raise HTTPException(404, "invalid clip range") from None
    try:
        job = store.get(job_id)
    except KeyError:
        raise HTTPException(404, "no such episode") from None
    if job["state"] != "done":
        raise HTTPException(404, "not finished")

    script = job.get("script") or []
    if turn_start < 0 or turn_end >= len(script) or turn_start > turn_end:
        raise HTTPException(404, "invalid clip range")

    found = find_clip_file(job_id, turn_start, turn_end)
    if found is None:
        raise HTTPException(404, "clip not found")
    clip_file = found.name
    clip_fs_path = found

    episode_title = job.get("title") or "untitled"
    clip_lines = script[turn_start:turn_end + 1]
    transcript = "".join(
        f"<p><b>{htmllib.escape(l['speaker'])}</b> {htmllib.escape(l['text'])}</p>"
        for l in clip_lines
    )
    turns = len(script)
    base = _public_base(request)
    show_name = (job.get("show_name") or "").strip() or "vozonda"
    show_author = (job.get("show_author") or "").strip() or "vozonda"
    language = job.get("language") or "en"
    created_at = job.get("created_at")
    if created_at:
        try:
            created_at_iso = datetime.datetime.fromtimestamp(created_at, tz=datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            created_at_iso = ""
    else:
        created_at_iso = ""

    clip_dur = get_audio_duration_sync(clip_fs_path) or (turn_end - turn_start + 1) * 15.0
    dur_m = int(clip_dur // 60)
    dur_s = int(clip_dur % 60)
    duration_iso = f"PT{dur_m}M{dur_s}S"

    og_img = job.get("og_image")
    if og_img:
        img_url = f"{base}/img/{og_img}" if not og_img.startswith("http") else og_img
    else:
        img_url = f"{base}/og-default.png"
    og_alt = f"Clip {turn_start}-{turn_end} of {htmllib.escape(episode_title)}"

    # SEO: quote-driven title and rich description
    quote = clip_quote_snippet(script, turn_start, turn_end)
    seo_title = clip_title(quote, episode_title)
    spoken_text = " ".join(l.get("text", "") for l in clip_lines)
    seo_desc = clip_description(spoken_text, clip_dur, episode_title)
    # canonical URL includes slug when available (filesystem name carries slug)
    url_slug = ""
    if "-clip-" in clip_file:
        # extract suffix slug from filename for canonical
        stem = clip_file.removesuffix(".mp3")
        parts = stem.split("-clip-")
        if len(parts) == 2:
            turn_slug = parts[1]  # e.g. "1-2-hello-world"
            segs = turn_slug.split("-", 2)
            if len(segs) == 3:
                url_slug = segs[2]
    canonical = f"{base}/e/{job_id}/clip/{turn_start}-{turn_end}"
    if url_slug:
        canonical = f"{canonical}-{url_slug}"
    # descriptive label for meta line
    label = clip_display_label(script, turn_start, turn_end, clip_dur)

    return CLIP_SHARE_TMPL.format(
        title=htmllib.escape(seo_title),
        desc=htmllib.escape(seo_desc),
        url=canonical,
        img=img_url,
        og_alt=og_alt,
        audio=f"{base}/audio/{clip_file}",
        meta_line=htmllib.escape(f"{label} · {turn_end - turn_start + 1} turns · from episode {turns} turns"),
        transcript=transcript,
        turn_start=turn_start,
        turn_end=turn_end,
        app_url=base,
        episode_url=f"{base}/e/{job_id}",
        show_name=htmllib.escape(show_name),
        show_author=htmllib.escape(show_author),
        duration_iso=duration_iso,
        created_at=created_at_iso,
        language=htmllib.escape(language),
    )


@app.get("/og-default.png", include_in_schema=False)
async def og_image():
    p = MEDIA_DIR / "og-default.png"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png")


@app.get(
    "/audio/{filename:path}.mp3",
    summary="Serve audio files",
    description=(
        "Download MP3 audio files for episodes, clips, and voice probes. "
        "Episode audio is served at /audio/{job_id}.mp3 after a job completes (state=done). "
        "Transcript clips are served at /audio/{job_id}-clip-{start}-{end}.mp3. "
        "Voice probes are served at /audio/probe-{timbre}.mp3."
    ),
)
@app.head("/audio/{filename:path}.mp3", include_in_schema=False)
async def audio(filename: str, request: Request) -> FileResponse:
    """Serve audio files: main episodes, voice probes, and generated clips.
    
    Supports job episodes (/audio/{job_id}.mp3), transcript clips
    (/audio/{job_id}-clip-{turn_start}-{turn_end}.mp3), and voice probes
    (/audio/probe-{timbre}.mp3).
    """
    path = MEDIA_DIR / f"{filename}.mp3"
    # Security: prevent path traversal (F-5)
    try:
        path.resolve().relative_to(MEDIA_DIR.resolve())
    except ValueError:
        raise HTTPException(403, "forbidden") from None
    if path.exists():
        return FileResponse(path, media_type="audio/mpeg")

    # If filename starts with "probe-", check public voice probe samples
    if filename.startswith("probe-"):
        probe_name = filename.removeprefix("probe-").lower().strip()
        samples_dir = Path(__file__).resolve().parents[4] / "apps/web/public/media/samples/voices"
        if samples_dir.exists():
            exact = samples_dir / f"{probe_name}.mp3"
            # Security: prevent traversal within samples dir (F-5)
            try:
                exact.resolve().relative_to(samples_dir.resolve())
            except ValueError:
                raise HTTPException(403, "forbidden") from None
            if exact.exists():
                return FileResponse(exact, media_type="audio/mpeg")
            matches = sorted(samples_dir.glob(f"*_{probe_name}.mp3"))
            if matches:
                return FileResponse(matches[0], media_type="audio/mpeg")

    raise HTTPException(404, "audio not found")


@app.get("/audio/{job_id}.peaks.json")
@app.head("/audio/{job_id}.peaks.json", include_in_schema=False)
async def audio_peaks(job_id: str, request: Request) -> FileResponse:
    # job_id is the id without extension; file is {id}.peaks.json next to mp3
    path = MEDIA_DIR / f"{job_id}.peaks.json"
    # Security: prevent path traversal (F-6)
    try:
        path.resolve().relative_to(MEDIA_DIR.resolve())
    except ValueError:
        raise HTTPException(403, "forbidden") from None
    if not path.exists():
        raise HTTPException(404, "no peaks yet")
    return FileResponse(path, media_type="application/json")



class ClipCreateIn(BaseModel):
    job_id: str
    turn_start: int
    turn_end: int


@app.post("/clips", dependencies=[Depends(require_write_auth)])
async def create_clip(body: ClipCreateIn, request: Request) -> dict:
    """Create an audio clip from a transcript selection.
    
    Extracts a precise MP3 segment from a finished episode using per-turn
    timestamps (script[].t0) so that clip bounds align exactly with the
    selected transcript lines.
    
    Returns metadata: clip URL, filename, start/end timestamps, duration.
    """
    job_id = body.job_id
    turn_start = body.turn_start
    turn_end = body.turn_end
    
    # Validate job exists and is done
    try:
        job = store.get(job_id)
    except KeyError:
        raise HTTPException(404, f"job not found: {job_id}")
    
    if job.get("state") != "done":
        raise HTTPException(409, f"job not finished: state={job['state']}")
    
    script = job.get("script")
    if not script:
        raise HTTPException(409, "job has no script")
    
    # Validate turn indices
    script_len = len(script)
    if turn_start < 0 or turn_end < 0 or turn_start >= script_len or turn_end >= script_len:
        raise HTTPException(422, f"turn indices out of range [0,{script_len-1}]")
    if turn_start > turn_end:
        raise HTTPException(422, "turn_start must be <= turn_end")
    
    # Compute clip bounds
    source_mp3 = MEDIA_DIR / f"{job_id}.mp3"
    if not source_mp3.exists():
        raise HTTPException(409, "source audio not found")
    
    try:
        duration = get_audio_duration_sync(source_mp3)
        start_sec, end_sec = compute_clip_bounds(script, turn_start, turn_end, duration)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    
    # SEO slug from first turn quote
    quote_slug = clip_quote_slug(script, turn_start, turn_end)
    # Prefer slug filename when we have a meaningful slug
    dest_filename = clip_filename(job_id, turn_start, turn_end, quote_slug if quote_slug and quote_slug != "clip" else None)
    clip_file = MEDIA_DIR / dest_filename
    # If a legacy file already exists without slug, reuse it to avoid duplicate slicing
    legacy_path = MEDIA_DIR / clip_filename(job_id, turn_start, turn_end)
    if legacy_path.exists() and legacy_path != clip_file:
        clip_file = legacy_path
        dest_filename = legacy_path.name
    else:
        # check existing slug variant already exists
        existing = find_clip_file(job_id, turn_start, turn_end)
        if existing is not None and existing.exists():
            clip_file = existing
            dest_filename = existing.name
    # Only slice if destination does not already exist
    if not clip_file.exists():
        # if we chose slug name but file not present, ensure we use slug name
        if quote_slug and quote_slug != "clip":
            clip_file = MEDIA_DIR / clip_filename(job_id, turn_start, turn_end, quote_slug)
            dest_filename = clip_file.name
        try:
            await slice_audio(source_mp3, clip_file, start_sec, end_sec)
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            raise HTTPException(409, f"audio slicing failed: {exc}")

    base = _public_base(request)
    share_slug = quote_slug if quote_slug and quote_slug != "clip" else ""
    share_url = f"{base}/e/{job_id}/clip/{turn_start}-{turn_end}"
    if share_slug:
        share_url = f"{share_url}-{share_slug}"
    # SEO helpers for response
    quote = clip_quote_snippet(script, turn_start, turn_end)
    spoken_text = " ".join(str(script[i].get("text", "")) for i in range(turn_start, turn_end + 1))
    duration = round(end_sec - start_sec, 2)
    seo_title = clip_title(quote, job.get("title") or "untitled")
    seo_desc = clip_description(spoken_text, duration, job.get("title") or "untitled")
    speaker = str(script[turn_start].get("name") or script[turn_start].get("speaker") or "").strip() or "voice"
    label = clip_display_label(script, turn_start, turn_end, duration)

    return {
        "job_id": job_id,
        "turn_start": turn_start,
        "turn_end": turn_end,
        "filename": dest_filename,
        "url": f"/audio/{dest_filename}",
        "share_url": share_url,
        "slug": share_slug,
        "quote_snippet": quote,
        "speaker": speaker,
        "label": label,
        "title": seo_title,
        "description": seo_desc,
        "start_seconds": start_sec,
        "end_seconds": end_sec,
        "duration_seconds": duration,
    }


@app.get("/jobs/{job_id}/clips")
async def list_clips(job_id: str, request: Request) -> list[dict]:
    """List all generated clips for a job.

    Parses both legacy '{id}-clip-{start}-{end}.mp3' and SEO
    '{id}-clip-{start}-{end}-{slug}.mp3' filenames. Returns enriched
    metadata for SEO-friendly labels and share URLs.
    """
    try:
        job = store.get(job_id)
    except KeyError:
        raise HTTPException(404, "job not found")

    clips: list[dict] = []
    script = job.get("script") or []
    episode_title = job.get("title") or "untitled"
    for clip_path_obj in MEDIA_DIR.glob(f"{job_id}-clip-*.mp3"):
        stem = clip_path_obj.stem
        parts = stem.split("-clip-")
        if len(parts) != 2:
            continue
        try:
            turn_part = parts[1]
            # turn_part is '{start}-{end}' or '{start}-{end}-{slug}'
            segs = turn_part.split("-")
            if len(segs) < 2:
                continue
            turn_start = int(segs[0])
            turn_end = int(segs[1])
            slug = "-".join(segs[2:]) if len(segs) > 2 else ""
        except (ValueError, IndexError):
            continue

        # Validate against script length
        if turn_start < 0 or turn_end >= len(script) or turn_start > turn_end:
            continue

        duration = get_audio_duration_sync(clip_path_obj)

        base = _public_base(request)
        # SEO share URL includes slug when present
        share_url = f"{base}/e/{job_id}/clip/{turn_start}-{turn_end}"
        if slug:
            share_url = f"{share_url}-{slug}"
        elif script:
            # generate slug from script for canonical share URL even if file is legacy
            gen_slug = clip_quote_slug(script, turn_start, turn_end)
            if gen_slug and gen_slug != "clip":
                share_url = f"{share_url}-{gen_slug}"

        # descriptive label: speaker badge + quote snippet
        quote = clip_quote_snippet(script, turn_start, turn_end) if script else ""
        speaker = ""
        if 0 <= turn_start < len(script):
            speaker = str(script[turn_start].get("name") or script[turn_start].get("speaker") or "").strip() or "voice"
        else:
            speaker = "voice"
        label = clip_display_label(script, turn_start, turn_end, duration) if script else f"{speaker} ({round(duration)}s)"
        spoken_text = " ".join(str(script[i].get("text", "")) for i in range(turn_start, turn_end + 1)) if script else ""
        seo_title = clip_title(quote, episode_title)
        seo_desc = clip_description(spoken_text, duration, episode_title) if script else ""

        clips.append({
            "filename": clip_path_obj.name,
            "turn_start": turn_start,
            "turn_end": turn_end,
            "duration_seconds": round(duration, 2),
            "url": f"/audio/{clip_path_obj.name}",
            "share_url": share_url,
            "slug": slug,
            "quote_snippet": quote,
            "speaker": speaker,
            "label": label,
            "title": seo_title,
            "description": seo_desc,
        })

    clips.sort(key=lambda c: (c["turn_start"], c["turn_end"]))
    return clips


@app.delete("/jobs/{job_id}/clips/{filename}", dependencies=[Depends(require_write_auth)])
async def delete_clip(job_id: str, filename: str) -> dict:
    """Delete a specific audio clip file for a job."""
    if not filename.startswith(f"{job_id}-clip-") or not filename.endswith(".mp3"):
        raise HTTPException(400, "invalid clip filename for job")
    
    clip_file = (MEDIA_DIR / filename).resolve()
    if not clip_file.is_relative_to(MEDIA_DIR.resolve()):
        raise HTTPException(400, "invalid path")
    
    if not clip_file.exists():
        raise HTTPException(404, "clip file not found")
    
    try:
        clip_file.unlink()
    except OSError as exc:
        raise HTTPException(500, f"failed to delete clip: {exc}")
    
    return {"deleted": True, "job_id": job_id, "filename": filename}


@app.get("/img/{filename:path}")
@app.head("/img/{filename:path}", include_in_schema=False)
async def serve_image(filename: str, request: Request) -> FileResponse:
    """Serve cover images and other static assets from MEDIA_DIR."""
    path = MEDIA_DIR / filename
    if not path.exists() or not path.is_file():
        # Auto-generate template cover if requested for an existing job
        if filename.endswith(("-cover.png", "-og.png")):
            job_id = filename.rsplit("-", 1)[0]
            try:
                job = store.get(job_id)
                from .cover import generate_template_cover

                generate_template_cover(
                    job.get("title") or "vozonda episode",
                    style=job.get("style") or "balanced",
                    output=path,
                    size=1200,
                )
                store.update(job_id, og_image=filename)
            except Exception:
                raise HTTPException(404, "image not found") from None
        else:
            raise HTTPException(404, "image not found")
    # Security: prevent path traversal
    try:
        path.resolve().relative_to(MEDIA_DIR.resolve())
    except ValueError:
        raise HTTPException(403, "forbidden") from None
    media_type = "image/png" if filename.endswith(".png") else "image/jpeg" if filename.endswith(".jpg") else "image/png"
    return FileResponse(path, media_type=media_type)


def _format_vtt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _format_srt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    s_int = int(s)
    ms = round((s - s_int) * 1000)
    return f"{h:02d}:{m:02d}:{s_int:02d},{ms:03d}"


@app.get("/vtt/{job_id}.vtt")
async def get_vtt(job_id: str) -> Response:
    """Generate a clean WebVTT transcript for Podcasting 2.0 players and web captioning."""
    try:
        job = store.get(job_id)
    except KeyError:
        raise HTTPException(404, "job not found")
    script = job.get("script") or []
    if not script:
        raise HTTPException(404, "no script available")

    title = job.get("title") or "vozonda episode"
    vtt_lines = ["WEBVTT", "", f"NOTE Title: {title}", ""]
    for i, turn in enumerate(script):
        t0 = float(turn.get("t0", i * 5))
        t1 = float(turn.get("t1", t0 + 4.5))
        speaker = turn.get("name") or turn.get("speaker") or f"Speaker {turn.get('speaker', 0)}"
        text = str(turn.get("text", "")).strip()
        vtt_lines.append(f"{i + 1}")
        vtt_lines.append(f"{_format_vtt_ts(t0)} --> {_format_vtt_ts(t1)}")
        vtt_lines.append(f"<v {speaker}>{text}")
        vtt_lines.append("")
    return Response(content="\n".join(vtt_lines), media_type="text/vtt")


@app.get("/srt/{job_id}.srt")
async def get_srt(job_id: str) -> Response:
    """Generate a SubRip (SRT) subtitle file for video and audio players."""
    try:
        job = store.get(job_id)
    except KeyError:
        raise HTTPException(404, "job not found")
    script = job.get("script") or []
    if not script:
        raise HTTPException(404, "no script available")

    srt_lines = []
    for i, turn in enumerate(script):
        t0 = float(turn.get("t0", i * 5))
        t1 = float(turn.get("t1", t0 + 4.5))
        speaker = turn.get("name") or turn.get("speaker") or f"Speaker {turn.get('speaker', 0)}"
        text = str(turn.get("text", "")).strip()
        srt_lines.append(f"{i + 1}")
        srt_lines.append(f"{_format_srt_ts(t0)} --> {_format_srt_ts(t1)}")
        srt_lines.append(f"[{speaker}] {text}")
        srt_lines.append("")
    return Response(content="\n".join(srt_lines), media_type="application/x-subrip")


@app.get("/share/{clip_id}", response_class=HTMLResponse)
async def share_clip(clip_id: str) -> HTMLResponse:
    """Public social share card for sliced audio clips with OpenGraph player tags."""
    clip_file = MEDIA_DIR / f"{clip_id}.mp3"
    if not clip_file.exists():
        raise HTTPException(404, "clip not found")

    title = "Vozonda Clip"
    audio_url = f"/audio/{clip_id}.mp3"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta property="og:title" content="{title}">
  <meta property="og:type" content="music.song">
  <meta property="og:audio" content="{audio_url}">
  <meta property="og:audio:type" content="audio/mpeg">
  <meta name="twitter:card" content="player">
  <meta name="twitter:title" content="{title}">
  <style>
    :root {{ --bg: #0e1117; --ink: #e6edf3; --line: #30363d; --green: #238636; }}
    body {{ background: var(--bg); color: var(--ink); font-family: ui-monospace, monospace; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }}
    .card {{ background: #161b22; border: 1px solid var(--line); border-radius: 8px; padding: 24px; max-width: 480px; width: 100%; text-align: center; }}
    h1 {{ font-size: 1.1rem; margin: 0 0 16px; font-weight: normal; color: var(--green); }}
    audio {{ width: 100%; margin: 16px 0; }}
    a {{ color: #58a6ff; text-decoration: none; font-size: 0.85rem; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>// vozonda audio clip</h1>
    <audio controls autoplay src="{audio_url}"></audio>
    <div><a href="/">open in vozonda &rarr;</a></div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.post("/watchlist/{wid}/cover", dependencies=[Depends(require_write_auth)])
async def upload_cover(wid: str, request: Request):
    """Upload a cover image for a watchlist/feed. Accepts multipart form with 'file' field."""
    import imghdr

    form = await request.form()
    file = form.get("file")
    if not file or not hasattr(file, "file"):
        raise HTTPException(422, "missing file")

    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(422, "file too large (max 5MB)")

    # Validate image
    img_type = imghdr.what(None, data)
    if img_type not in ("png", "jpeg", "jpg"):
        raise HTTPException(422, "only PNG and JPEG allowed")

    # Generate filename
    import uuid
    ext = "png" if img_type == "png" else "jpg"
    filename = f"watchlist-{wid}-cover.{uuid.uuid4().hex[:8]}.{ext}"
    dest = MEDIA_DIR / filename
    dest.write_bytes(data)

    # Update watchlist with cover image
    from .watchlist import update_watchlist
    try:
        update_watchlist(wid, cover_image=filename)
    except KeyError:
        raise HTTPException(404, "watchlist not found") from None

    return {"ok": True, "cover_image": filename}


@app.put("/audio/{job_id}.peaks.json", dependencies=[Depends(require_write_auth)])
async def put_audio_peaks(job_id: str, request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(422, "invalid json") from None
    peaks = data.get("peaks") if isinstance(data, dict) else None
    if not isinstance(peaks, list) or not peaks:
        raise HTTPException(422, "missing peaks array")
    if len(peaks) > 1024:
        raise HTTPException(422, "too many peaks")
    # basic numeric sanity; coerce
    try:
        clean = [float(v) for v in peaks]
    except (TypeError, ValueError):
        raise HTTPException(422, "peaks must be numeric") from None
    # store alongside mp3; allow overwriting (idempotent cache)
    path = MEDIA_DIR / f"{job_id}.peaks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # preserve supplied duration/bars if present, else just peaks
    payload: dict = {"peaks": clean}
    if isinstance(data.get("duration"), (int, float)):
        payload["duration"] = float(data["duration"])
    if isinstance(data.get("bars"), int):
        payload["bars"] = int(data["bars"])
    path.write_text(json.dumps(payload))
    return JSONResponse({"ok": True, "peaks": len(clean)})


@app.get("/storage")
async def storage_stats() -> dict:
    """Return media directory storage stats and retention info."""
    from .retention import get_storage_stats

    return get_storage_stats()


@app.post("/storage/purge", dependencies=[Depends(require_write_auth)])
async def purge_storage(request: Request) -> dict:
    """Purge media files older than retention threshold (default 360 days)."""
    from .retention import DEFAULT_RETENTION_DAYS, purge_old_media

    days = DEFAULT_RETENTION_DAYS
    try:
        data = await request.json()
        if isinstance(data, dict) and "days" in data:
            days = max(1, min(3650, int(data["days"])))
    except Exception:
        logger.debug("purge storage body parse failed, using default days", exc_info=True)

    return purge_old_media(days=days)


@app.get("/music/status")
async def music_status() -> dict:
    """Return status of intro and outro music tracks (custom vs procedural)."""
    from .music_store import get_music_status

    return get_music_status()


@app.post("/music/import-url", dependencies=[Depends(require_write_auth)])
async def import_music(request: Request) -> dict:
    """Import an audio track from URL safely into media/music/ (intro or outro)."""
    from .fetcher import FetchError
    from .music_store import import_music_from_url

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required")

    url = body.get("url", "").strip()
    kind = body.get("kind", "intro").strip()

    if not url:
        raise HTTPException(status_code=400, detail="Missing required 'url' field")

    try:
        res = await import_music_from_url(url=url, kind=kind)
        return res
    except FetchError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Music import failed: {e}") from e


@app.post("/music/reset", dependencies=[Depends(require_write_auth)])
async def reset_music_endpoint(request: Request) -> dict:
    """Reset custom music tracks back to built-in procedural jazz progression."""
    from .music_store import reset_music

    kind = "all"
    try:
        body = await request.json()
        if isinstance(body, dict) and "kind" in body:
            kind = body["kind"]
    except Exception:
        logger.debug("reset music body parse failed, using kind=all", exc_info=True)

    return reset_music(kind=kind)


@app.get("/music/{kind}.mp3")
async def serve_music_preview(kind: str) -> FileResponse:
    """Serve a preview MP3 for the specified music track (custom or procedural)."""
    from .music_store import get_or_create_preview_audio

    norm_kind = kind.lower().strip()
    if norm_kind not in ("intro", "outro"):
        raise HTTPException(status_code=404, detail="Track kind must be 'intro' or 'outro'")

    path = get_or_create_preview_audio(norm_kind)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Preview audio not found")

    return FileResponse(path, media_type="audio/mpeg")



def _job_source_urls(row: dict) -> list[str]:
    """Source url(s) of a job: digest sources first, else the job url."""
    sources: list[str] = []
    raw = row.get("digest_sources")
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list):
                sources = [str(s).strip() for s in parsed if isinstance(s, str) and s.strip()]
        except Exception:
            sources = []
    url = str(row.get("url") or "").strip()
    if not sources and url and not url.startswith("digest:"):
        sources = [url]
    return sources


# Feed routes (VOZONDA-SPLIT-1: moved to routers/feeds.py)
app.include_router(feed_router)


# Distribution routes (VOZONDA-DISTRIBUTION)
app.include_router(distribution_router)


# ---------------------------------------------------------------------------
# Nostr Multi-Signer Auth (NIP-07 / NIP-46 Amber / npub)
# ---------------------------------------------------------------------------

@app.get("/auth/nostr/challenge")
async def nostr_challenge() -> dict:
    from .nostr_auth import create_challenge

    chal, exp = create_challenge()
    return {"challenge": chal, "expires_at": exp, "ttl": 300}


class NostrVerifyIn(BaseModel):
    event: dict
    challenge: str | None = None
    signer: str | None = None  # extension | amber | bunker | readOnly


@app.post("/auth/nostr/verify")
async def nostr_verify(body: NostrVerifyIn) -> dict:
    from .nostr_auth import (
        consume_challenge,
        hex_to_npub,
        peek_challenge,
        store_identity,
        verify_event_structure,
    )

    chal = body.challenge
    # if challenge supplied, check it exists (peek first for better error)
    if chal is not None and not peek_challenge(chal):
        raise HTTPException(422, "challenge expired or unknown")
    ok, reason = verify_event_structure(body.event, expected_challenge=chal)
    if not ok:
        raise HTTPException(422, reason)
    # one-time consume after successful verify
    if chal is not None:
        consume_challenge(chal)
    pubkey = str(body.event.get("pubkey", "")).lower()
    npub = hex_to_npub(pubkey)
    signer = (body.signer or "unknown").strip() or "unknown"
    # persist binding (npub <-> app, no nsec ever)
    try:
        store_identity(pubkey, signer=signer)
    except Exception:
        logger.warning("nostr identity persist failed for pubkey %s", pubkey, exc_info=True)
    return {"ok": True, "pubkey": pubkey, "npub": npub, "signer": signer}


class NpubValidateIn(BaseModel):
    pubkey: str | None = None
    npub: str | None = None
    input: str | None = None


@app.post("/auth/npub/validate")
async def npub_validate(body: NpubValidateIn) -> dict:
    from .nostr_auth import hex_to_npub, is_valid_hex_pubkey, is_valid_npub, normalize_pubkey

    raw = (body.input or body.npub or body.pubkey or "").strip()
    if not raw:
        raise HTTPException(422, "provide input, npub or pubkey")
    # reject nsec outright (never store/handle private)
    from .nostr_auth import is_valid_nsec

    if is_valid_nsec(raw):
        raise HTTPException(422, "nsec not allowed (private key), use npub or hex pubkey only")
    try:
        hex_key = normalize_pubkey(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "valid": True,
        "hex": hex_key,
        "npub": hex_to_npub(hex_key),
        "is_npub": is_valid_npub(raw),
        "is_hex": is_valid_hex_pubkey(raw),
    }


@app.get("/auth/nostr/identities")
async def nostr_identities() -> dict:
    from .nostr_auth import list_identities

    return {"identities": list_identities()}


@app.delete("/auth/nostr/identities/{pubkey}", dependencies=[Depends(require_write_auth)])
async def nostr_remove_identity(pubkey: str) -> dict:
    from .nostr_auth import remove_identity

    if not remove_identity(pubkey):
        raise HTTPException(404, "no such identity")
    return {"removed": pubkey.lower()}


# ---------------------------------------------------------------------------
# Nostr Publishing per-show endpoints (VOZONDA-NOSTR-3)
# ---------------------------------------------------------------------------

class NostrEnableIn(BaseModel):
    enabled: bool
    confirm_public: bool | None = None


@app.get("/shows/{slug}/nostr")
async def get_show_nostr(slug: str) -> dict:
    """Return Nostr publishing status for a show: enabled flag, npub, last event id."""
    import sqlite3

    from .jobs import DB_PATH
    from .settings_store import all_settings, get_setting

    show_num = slug.lstrip("s")
    try:
        idx = int(show_num)
    except (ValueError, TypeError):
        raise HTTPException(404, "show not found")

    # Check if show exists
    all_settings_dict = all_settings()
    if f"show.{idx}.name" not in all_settings_dict or not all_settings_dict.get(f"show.{idx}.name"):
        raise HTTPException(404, "show not found")

    # Read nostr switch
    nostr_val = get_setting(f"show.{idx}.nostr")
    enabled = nostr_val == "1"

    # Get npub if keypair exists
    npub = None
    last_event_id = None
    try:
        from .podcast_key import has_keypair, load_keypair, pubkey_to_npub

        if has_keypair(show_num):
            _, pubkey_hex = load_keypair(show_num)
            npub = pubkey_to_npub(pubkey_hex)
    # silent: nostr key loading is optional for the show meta endpoint
    except Exception:
        pass

    # this show's last published show event (the old query took any show's)
    try:
        with sqlite3.connect(DB_PATH) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT event_id FROM nostr_show_meta WHERE show_slug = ?", (show_num,),
            ).fetchone()
            if row:
                last_event_id = row["event_id"]
    except Exception:
        logger.debug("nostr: last_event_id lookup failed", exc_info=True)

    return {
        "enabled": enabled,
        "npub": npub,
        "last_event_id": last_event_id,
    }


@app.put("/shows/{slug}/nostr", dependencies=[Depends(require_write_auth)])
async def put_show_nostr(slug: str, body: NostrEnableIn) -> dict:
    """Enable or disable Nostr publishing for a show.

    Enabling without confirm_public=true returns 422 with a warning that
    episodes become public and are hard to remove.
    """
    from .settings_store import _conn

    show_num = slug.lstrip("s")
    try:
        idx = int(show_num)
    except (ValueError, TypeError):
        raise HTTPException(404, "show not found")

    # Check if show exists
    all_settings_dict = all_settings()
    if f"show.{idx}.name" not in all_settings_dict or not all_settings_dict.get(f"show.{idx}.name"):
        raise HTTPException(404, "show not found")

    # Enabling without confirmation returns 422
    if body.enabled and not body.confirm_public:
        raise HTTPException(
            422,
            "Enabling Nostr publishing makes episodes public and hard to remove. "
            "Set confirm_public=true to confirm.",
        )

    # Update the show's nostr setting
    conn = _conn()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (f"show.{idx}.nostr", "1" if body.enabled else "0"),
    )
    conn.commit()
    conn.close()

    return {
        "enabled": body.enabled,
        "slug": slug,
    }


@app.post("/shows/{slug}/nostr/export-nsec", dependencies=[Depends(require_write_auth)])
async def export_show_nsec(slug: str) -> dict:
    """Export the nsec secret key for a show (one-time explicit backup).

    Requires write auth. Returns the nsec value.
    """
    show_num = slug.lstrip("s")
    try:
        int(show_num)
    except (ValueError, TypeError):
        raise HTTPException(404, "show not found")

    # Check if keypair exists
    from .podcast_key import export_nsec, has_keypair

    if not has_keypair(show_num):
        raise HTTPException(404, "no keypair found for this show")

    nsec = export_nsec(show_num)
    return {"slug": slug, "nsec": nsec}


@app.get("/jobs/{job_id}/nostr")
async def get_job_nostr(job_id: str) -> dict:
    """Return Nostr publishing status for a job: event_ids and relay/server results."""
    import sqlite3

    from .jobs import DB_PATH

    try:
        store.get(job_id)
    except KeyError:
        raise HTTPException(404, "job not found")

    try:
        with sqlite3.connect(DB_PATH) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT kind, event_id, relay_url, relay_ok, server_url, server_ok "
                "FROM nostr_publish WHERE job_id = ? ORDER BY published_at",
                (job_id,),
            ).fetchall()
    except Exception:
        rows = []

    events: list[dict] = []
    for r in rows:
        events.append({
            "kind": r["kind"],
            "event_id": r["event_id"],
            "relay_url": r["relay_url"],
            "relay_ok": bool(r["relay_ok"]) if r["relay_ok"] is not None else None,
            "server_url": r["server_url"],
            "server_ok": bool(r["server_ok"]) if r["server_ok"] is not None else None,
        })

    return {
        "job_id": job_id,
        "events": events,
    }


@app.post("/jobs/{job_id}/nostr/publish", dependencies=[Depends(require_write_auth)])
async def retry_job_publish(job_id: str) -> dict:
    """Retry Nostr publishing for a job (re-runs the full publish flow)."""
    try:
        store.get(job_id)
    except KeyError:
        raise HTTPException(404, "job not found")

    from .nostr_orchestrator import publish_job
    from .pipeline import _spawn_background

    # an upload can take minutes: answer now, publish in the background
    _spawn_background(publish_job(job_id))
    return {"job_id": job_id, "retried": True, "queued": True}


@app.delete("/jobs/{job_id}/nostr", dependencies=[Depends(require_write_auth)])
async def delete_job_nostr(job_id: str) -> dict:
    """Best-effort deletion of a job from Nostr (kind:54 events + Blossom blobs)."""
    try:
        store.get(job_id)
    except KeyError:
        raise HTTPException(404, "job not found")

    from .nostr_orchestrator import delete_published_job

    result = await delete_published_job(job_id)
    return {
        "job_id": job_id,
        "deleted": result,
    }


# Billing routes (VOZONDA-SPLIT-2: moved to routers/billing.py)
app.include_router(billing_router)


def serve() -> None:
    import uvicorn

    host = env("HOST", "127.0.0.1")
    port = int(env("PORT", "8787"))
    uvicorn.run(app, host=host, port=port)
