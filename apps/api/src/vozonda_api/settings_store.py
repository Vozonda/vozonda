import logging
import re
import secrets
import sqlite3
from typing import Any

from .env import env
from .envfile import load_env_file
from .jobs import DB_PATH, init_db

logger = logging.getLogger(__name__)

load_env_file()

SETTING_KEYS = {
    "script.balanced",
    "script.narration",
    "script.turns_min",
    "script.turns_max",
    "script.turn_words_max",
    "script.short_reactions",
    "format.default",
    "tone.default",
    "voice.dialog.count",
    "voice.a.timbre",
    "voice.b.timbre",
    "voice.c.timbre",
    "voice.solo.timbre",
    "voice.a.name",
    "voice.b.name",
    "voice.c.name",
    "feed.creator.address",
    "feed.creator.split",
    "feed.source.address",
    "feed.source.split",
    "feed.app.address",
    "feed.app.split",
    "feed.public",
    "feed.private_key",
    "voice.emotion",
    "voice.speed",
    "voice.gap_ms",
    "language.default",
    "tts.engine",
    "llm.engine",
    "llm.api_key",
    "llm.nim_api_key",
    "llm.nim_model",
    "llm.opencode_models",
    "llm.backup_engine",
    "llm.custom_base",
    "llm.custom_model",
    "watchlist.render_mode",
    "source.research_depth",
    "source.max_chars",
    "source.max_sources",
    "music.enabled",
    "music.intro",
    "music.outro",
    "music.duck_db",
    "music.style",
    "script.use_names",
    "script.intro_hook",
    "script.review_default",
    "script.takeaways",
    "script.default_minutes",
    "show.name",
    "show.description",
    "show.author",
    "show.category",
    "player.default_speed",
    "player.default_text_size",
    "player.karaoke",
    "player.chapters",
    "player.autoscroll",
    "player.boost_placement",
    "disclosure.ai_label",
    # "0" turns off the check for new releases (updates.py)
    "update.check",
    # Nostr publishing (VOZONDA-NOSTR)
    "nostr.publish_default",
    "nostr.relays",
    "nostr.blossom_servers",
    # Distribution (VOZONDA-DISTRIBUTION)
    "distribution.rss_default",
}


# every style gets its own override key, wired to pipeline._script()
try:
    from .styles import STYLE_IDS

    SETTING_KEYS |= {f"script.style.{sid}" for sid in STYLE_IDS if sid != "balanced"}
except ImportError:
    pass


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_table() -> None:
    with _conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )


init_db()
ensure_table()


# The app's share of a value-for-value split goes to the open-source project unless the
# install sets its own address (env, locked) or the share to 0 (operator, 2026-10-03:
# installs that use the app support it this way; a fake placeholder sent the share nowhere)
PROJECT_V4V_ADDRESS = "vozonda@rizful.com"


def is_node_v4v_address_locked() -> bool:
    return bool(env("NODE_V4V_ADDRESS") or env("APP_V4V_ADDRESS"))


def get_node_v4v_address() -> str | None:
    return env("NODE_V4V_ADDRESS") or env("APP_V4V_ADDRESS")


# the per-show Nostr switch; numbered shows and default show
_SHOW_NOSTR_KEY = re.compile(r"^show\.(?:(?:s)?[0-9]+|default)\.nostr$")

# the per-show RSS switch; same rule as show.<n>.nostr
_SHOW_RSS_KEY = re.compile(r"^show\.(?:(?:s)?[0-9]+|default)\.rss$")


def _normalize_show_key(key: str) -> str:
    """Normalize show.N.* keys by removing optional 's' prefix from the number.
    
    show.s1.nostr -> show.1.nostr
    show.s1.rss -> show.1.rss
    show.1.name -> show.1.name (unchanged)
    """
    if key.startswith("show.s"):
        i = 6
        while i < len(key) and key[i].isdigit():
            i += 1
        if i > 6 and i < len(key) and key[i] == ".":
            return f"show.{key[6:i]}{key[i:]}"
    return key


DEFAULT_NOSTR_RELAYS = "wss://relay.damus.io, wss://nos.lol, wss://relay.primal.net"
# free third-party servers that took a signed 30 MB audio preflight (BUD-06) on
# 2026-10-02; blossom.band and blossom.nostr.build refuse 30 MB (413) and would lose
# every episode over about half an hour
DEFAULT_BLOSSOM_SERVERS = "https://nostr.download, https://blossom.primal.net, https://cdn.nostrcheck.me"


def _fetch_row(key: str):
    with _conn() as c:
        return c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()


def get_setting(key: str) -> Any | None:
    norm_key = _normalize_show_key(key)
    if norm_key not in SETTING_KEYS and not norm_key.startswith("tts.wpm.") and not _SHOW_NOSTR_KEY.match(norm_key) and not _SHOW_RSS_KEY.match(norm_key):
        raise KeyError(f"unknown setting: {key}")
    if norm_key == "feed.app.address":
        env_addr = get_node_v4v_address()
        if env_addr:
            return env_addr
        row = _fetch_row(norm_key)
        return (row["value"] if row else "") or PROJECT_V4V_ADDRESS
    if norm_key == "distribution.rss_default":
        # Default to '1' (RSS on) for new shows
        row = _fetch_row(norm_key)
        return row["value"] if row else "1"
    row = _fetch_row(norm_key)
    if row is None and norm_key == "tts.engine":
        # a fresh install without a stored engine follows VOZONDA_TTS_ENGINE (the CPU
        # docker quickstart sets kokoro, piper covers the languages kokoro lacks);
        # before this the env var was never read
        env_engine = env("TTS_ENGINE", "").strip()
        if env_engine and env_engine in _tts_engine_keys():
            return env_engine
    if row is None and norm_key == "disclosure.ai_label":
        # on unless switched off: GET /settings and the settings page already show '1' as
        # the default, but an unset value compared as None and no AI tag was written
        # (EU AI Act Art. 50 machine-readable marking of synthetic audio)
        return "1"
    if row is None and norm_key == "nostr.publish_default":
        return "0"
    if row is None and norm_key == "nostr.relays":
        return DEFAULT_NOSTR_RELAYS
    if row is None and norm_key == "nostr.blossom_servers":
        return DEFAULT_BLOSSOM_SERVERS
    if row is not None and norm_key in ("llm.engine", "llm.backup_engine"):
        return _normalize_llm_engine(row["value"])
    return row["value"] if row else None


def get_private_feed_key() -> str:
    """Per-install secret that unlocks private feeds; generated on first use
    and persisted. Never returned to clients: it sits in SECRET_SETTINGS."""
    existing = get_setting("feed.private_key")
    if existing:
        return str(existing)
    key = secrets.token_urlsafe(24)
    set_setting("feed.private_key", key)
    return key


# Settings that hold credentials: never sent back to a client. GET /settings
# shows SECRET_MASK instead, and writing the mask back keeps the stored value.
SECRET_SETTINGS = frozenset({"llm.api_key", "llm.nim_api_key", "feed.private_key"})
SECRET_MASK = "********"


def public_settings() -> dict[str, str]:
    """all_settings() with credential values replaced by SECRET_MASK."""
    res = all_settings()
    for k in SECRET_SETTINGS:
        if res.get(k):
            res[k] = SECRET_MASK
    return res


def all_settings() -> dict[str, str]:
    with _conn() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
    res = {r["key"]: r["value"] for r in rows}
    for k in ("llm.engine", "llm.backup_engine"):
        if res.get(k):
            res[k] = _normalize_llm_engine(res[k])
    env_addr = get_node_v4v_address()
    if env_addr:
        res["feed.app.address"] = env_addr
    elif not res.get("feed.app.address"):
        res["feed.app.address"] = PROJECT_V4V_ADDRESS
    return res


def set_setting(key: str, value: str) -> str:
    """Validate and persist a setting; returns the cleaned stored value."""
    norm_key = _normalize_show_key(key)
    if key in SECRET_SETTINGS and value == SECRET_MASK:
        return get_setting(key) or ""
    # tts.wpm.<engine> is written by the pipeline's length calibration; until
    # 2026-09-24 only get_setting allowed the prefix, every write raised, the
    # pipeline swallowed it and all length planning ran on the 160 wpm default
    if norm_key not in SETTING_KEYS and not norm_key.startswith("tts.wpm.") and not _SHOW_NOSTR_KEY.match(norm_key) and not _SHOW_RSS_KEY.match(norm_key):
        raise KeyError(f"unknown setting: {key}")
    if norm_key == "feed.app.address" and is_node_v4v_address_locked():
        return get_node_v4v_address() or ""
    cleaned = _validate(norm_key, value)
    with _conn() as c:
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (norm_key, cleaned),
        )
    return cleaned


# mirrors the clamps applied by pipeline.py / voice-config build so a bad
# stored value can never crash a running job
SETTING_RANGES: dict[str, tuple[float, float]] = {
    "feed.creator.split": (0, 100),
    "feed.source.split": (0, 100),
    "feed.app.split": (0, 100),
    "voice.dialog.count": (1, 3),
    "voice.speed": (0.5, 2.0),
    "voice.gap_ms": (50, 1200),
    "script.turns_min": (6, 40),
    "script.turns_max": (8, 60),
    "script.turn_words_max": (20, 90),
    "script.short_reactions": (0, 10),
    "script.default_minutes": (1, 60),
    "music.duck_db": (-30.0, 0.0),
}
_SETTING_INTS = {"voice.dialog.count", "voice.gap_ms"}
def _tts_engine_keys() -> set[str]:
    """Valid engine ids come from the provider registry, not a hardcoded list."""
    from .providers import engine_ids
    return engine_ids()

# script writer engines (llm.engine and its llm.backup_engine); which model an
# engine runs is a setting (llm.nim_model, llm.opencode_models), never code.
# 'local' is the user's own OpenAI-compatible endpoint from VOZONDA_LLM_BASE /
# VOZONDA_LLM_MODEL (Ollama, vLLM, LM Studio, llama.cpp).
LLM_ENGINES = frozenset({"local", "kimi_nim",
                         "opencode", "claude", "custom", "none"})
# 'qwen_vllm' stays accepted as an alias of 'local' on read and write (the
# production install stores llm.backup_engine=qwen_vllm). The other
# operator-era keys are gone: a stored value with one of them reads as
# 'local' with a warning, and writing one is rejected.
LLM_ENGINE_ALIASES = {"qwen_vllm": "local"}
REMOVED_LLM_ENGINES = frozenset({"nemotron_vllm", "gemma_vllm", "nemo_sglang"})


def _normalize_llm_engine(value: str) -> str:
    v = (value or "").strip()
    if v in LLM_ENGINE_ALIASES:
        return LLM_ENGINE_ALIASES[v]
    if v in REMOVED_LLM_ENGINES:
        logger.warning("llm engine %r no longer exists, using 'local'", v)
        return "local"
    return v
_MODEL_ID = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._:-]+)+")

# display names must stay short: they end up in transcript labels and aria text
_NAME_KEYS = {"voice.a.name", "voice.b.name", "voice.c.name"}
_NAME_MAX = 24
_SHOW_TEXT_KEYS = {"show.name": 80, "show.author": 80, "show.category": 60, "show.description": 4000}


def _validate(key: str, value: str) -> str:
    if key.startswith("tts.wpm."):
        # calibrated words-per-minute per engine (VOZONDA-LEN-1); dynamic keys
        try:
            num = float(value)
        except ValueError as exc:
            raise ValueError(f"{key} expects a number, got {value!r}") from exc
        num = min(400.0, max(40.0, num))
        return f"{num:g}"
    if key == "tts.engine":
        from .providers import engine_blocked_reason
        blocked = engine_blocked_reason(value.strip())
        if blocked:
            raise ValueError(blocked)
        if value.strip() not in _tts_engine_keys():
            raise ValueError(f"tts.engine must be one of {sorted(_tts_engine_keys())}, got {value!r}")
        return value.strip()
    if key in ("llm.engine", "llm.backup_engine"):
        v = value.strip()
        if key == "llm.backup_engine" and v == "":
            return v
        if v in LLM_ENGINE_ALIASES:
            return LLM_ENGINE_ALIASES[v]
        if v in REMOVED_LLM_ENGINES:
            raise ValueError(f"{key} engine {v!r} no longer exists, use 'local' instead")
        if v not in LLM_ENGINES:
            raise ValueError(f"{key} must be one of {sorted(LLM_ENGINES)}, got {value!r}")
        return v
    if key == "llm.nim_model":
        v = value.strip()
        if v and not _MODEL_ID.fullmatch(v):
            raise ValueError(f"llm.nim_model must look like vendor/model, got {value!r}")
        return v
    if key == "llm.opencode_models":
        # ordered list: the first is tried first, the rest are fallbacks
        ids = [m for m in re.split(r"[,\s]+", value.strip()) if m]
        bad = [m for m in ids if not _MODEL_ID.fullmatch(m)]
        if bad:
            raise ValueError(f"llm.opencode_models expects provider/model ids, got {bad}")
        return ", ".join(ids)
    if key == "watchlist.render_mode":
        if value.strip() not in {"newest", "catchup"}:
            raise ValueError(f"watchlist.render_mode must be 'newest' or 'catchup', got {value!r}")
        return value.strip()
    if key == "source.research_depth":
        val = value.strip().lower()
        if val not in {"direct", "deep-page", "fact-check", "contrast"}:
            raise ValueError(f"source.research_depth must be direct, deep-page, fact-check, or contrast, got {value!r}")
        return val
    if key == "source.max_chars":
        val = value.strip().lower()
        if val == "auto":
            return "auto"
        try:
            num = int(float(value.strip()))
        except ValueError as exc:
            raise ValueError(f"source.max_chars must be 'auto' or 10000-2000000, got {value!r}") from exc
        if not 10000 <= num <= 2000000:
            raise ValueError(f"source.max_chars must be 'auto' or 10000-2000000, got {value!r}")
        return str(num)
    if key == "source.max_sources":
        try:
            num = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"source.max_sources must be 2-50, got {value!r}") from exc
        if not 2 <= num <= 50:
            raise ValueError(f"source.max_sources must be 2-50, got {value!r}")
        return str(num)
    if key in _NAME_KEYS:
        return value.strip()[:_NAME_MAX]
    if key in _SHOW_TEXT_KEYS:
        return value.strip()[: _SHOW_TEXT_KEYS[key]]
    if key == "player.default_speed":
        val = value.strip()
        if val not in {"0.8", "1.0", "1.25", "1.5", "2.0"}:
            raise ValueError(f"player.default_speed must be one of {{'0.8', '1.0', '1.25', '1.5', '2.0'}}, got {value!r}")
        return val
    if key == "player.default_text_size":
        val = value.strip().lower()
        if val not in {"compact", "normal", "large"}:
            raise ValueError(f"player.default_text_size must be 'compact', 'normal', or 'large', got {value!r}")
        return val
    if key == "feed.public":
        val = value.strip()
        if val not in {"0", "1"}:
            raise ValueError(f"feed.public must be '0' or '1', got {value!r}")
        return val
    if key == "script.review_default":
        val = value.strip()
        if val not in {"0", "1"}:
            raise ValueError(f"script.review_default must be '0' or '1', got {value!r}")
        return val
    if key == "player.karaoke":
        val = value.strip()
        if val not in {"0", "1"}:
            raise ValueError(f"player.karaoke must be '0' or '1', got {value!r}")
        return val
    if key == "player.chapters":
        val = value.strip()
        if val not in {"0", "1"}:
            raise ValueError(f"player.chapters must be '0' or '1', got {value!r}")
        return val
    if key == "player.autoscroll":
        val = value.strip().lower()
        if val not in {"follow", "free"}:
            raise ValueError(f"player.autoscroll must be 'follow' or 'free', got {value!r}")
        return val
    if key == "player.boost_placement":
        val = value.strip().lower()
        if val not in {"meta", "strip"}:
            raise ValueError(f"player.boost_placement must be 'meta' or 'strip', got {value!r}")
        return val
    if key == "disclosure.ai_label":
        val = value.strip()
        if val not in {"0", "1"}:
            raise ValueError(f"disclosure.ai_label must be '0' or '1', got {value!r}")
        return val
    if key in SETTING_RANGES:
        try:
            num = float(value)
        except ValueError as exc:
            raise ValueError(f"{key} expects a number, got {value!r}") from exc
        lo, hi = SETTING_RANGES[key]
        num = min(hi, max(lo, num))
        return str(round(num)) if key in _SETTING_INTS else f"{num:g}"
    if key == "nostr.publish_default":
        val = value.strip()
        if val not in {"0", "1"}:
            raise ValueError(f"nostr.publish_default must be '0' or '1', got {value!r}")
        return val
    if key == "nostr.relays":
        # comma-separated wss:// URLs; empty string is valid (clears the list)
        urls = [u.strip() for u in value.split(",") if u.strip()]
        for u in urls:
            if not u.startswith("wss://"):
                raise ValueError(f"nostr.relays entries must start with wss://, got {u!r}")
        return ", ".join(urls)
    if key == "nostr.blossom_servers":
        # comma-separated https:// URLs
        urls = [u.strip() for u in value.split(",") if u.strip()]
        for u in urls:
            if not u.startswith("https://"):
                raise ValueError(f"nostr.blossom_servers entries must start with https://, got {u!r}")
        return ", ".join(urls)
    if _SHOW_NOSTR_KEY.match(key):
        val = value.strip()
        if val not in {"0", "1"}:
            raise ValueError(f"{key} must be '0' or '1', got {value!r}")
        return val
    if _SHOW_RSS_KEY.match(key):
        val = value.strip()
        if val not in {"0", "1"}:
            raise ValueError(f"{key} must be '0' or '1', got {value!r}")
        return val
    if key == "distribution.rss_default":
        val = value.strip()
        if val not in {"0", "1"}:
            raise ValueError(f"distribution.rss_default must be '0' or '1', got {value!r}")
        return val
    return value


def resolve_show_nostr(show_num: str) -> str:
    """'1' only when the show's own switch is on (operator rule 2026-10-02: Nostr is
    switched on deliberately per show). nostr.publish_default is the preset a NEW
    show starts with (POST /shows) and is never a fallback here."""
    if show_num == "default":
        val = get_setting("show.default.nostr")
        if val is None:
            val = get_setting("show.nostr")
        return "1" if val == "1" else "0"
    return "1" if get_setting(f"show.{show_num}.nostr") == "1" else "0"


def resolve_show_rss(show_num: str) -> str:
    """'0' only when the show's RSS was switched off explicitly. Before the distribution
    switch every show had a feed, so an unset value means on (2026-10-02: the startup
    backfill meant to write '1' never ran, a NameError at import, and every existing
    show would have lost its feed). distribution.rss_default is the preset for NEW shows."""
    if show_num == "default":
        return "0" if get_setting("show.default.rss") == "0" else "1"
    return "0" if get_setting(f"show.{show_num}.rss") == "0" else "1"


_SHOW_KEY_NUM = re.compile(r"^show\.([0-9]+)\.")


def show_numbers() -> list[int]:
    """Numbers of the shows that exist (show.<n>.name set), with gaps: deleting show 1
    must not hide show 2 (every listing used to stop at the first gap)."""
    nums = set()
    for key, value in all_settings().items():
        m = _SHOW_KEY_NUM.match(key)
        if m and key.endswith(".name") and value:
            nums.add(int(m.group(1)))
    return sorted(nums)


def next_show_number() -> int:
    """A number no show ever had. A deleted show keeps its key file (its Nostr identity)
    and its episodes keep their show_slug, so reusing the number would let a new show
    publish as the old one (coordinator, 2026-10-02)."""
    used = {int(m.group(1)) for k in all_settings() if (m := _SHOW_KEY_NUM.match(k))}
    try:
        from .podcast_key import _get_nostr_secret_dir

        used |= {int(f.stem) for f in _get_nostr_secret_dir().glob("*.key") if f.stem.isdigit()}
    except Exception:
        logger.debug("show key directory not readable", exc_info=True)
    try:
        with _conn() as c:
            used |= {int(r[0]) for r in c.execute("SELECT DISTINCT show_slug FROM jobs WHERE show_slug != ''")
                     if str(r[0]).isdigit()}
    except Exception:
        logger.debug("jobs table not readable for show numbers", exc_info=True)
    return max(used, default=0) + 1
