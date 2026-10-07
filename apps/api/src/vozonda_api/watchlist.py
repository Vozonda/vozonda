"""Watchlist store: feeds to auto-render as episodes.

Table `watchlist` lives in the same SQLite DB as jobs (VOZONDA_DB).
Each row is a feed URL + desired render settings; a background poller
fetches the feed, turns new entries into jobs.
"""

import json
import logging
import re
import sqlite3
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .jobs import _conn  # reuse DB_PATH and connection helper
from .watchlist_dedupe import _normalize_title, canonical_url

logger = logging.getLogger(__name__)


def _add_column(c: sqlite3.Connection, table: str, column_ddl: str) -> None:
    """ALTER TABLE ADD COLUMN that skips existing columns.

    Only a duplicate-column OperationalError is swallowed; any other
    error is logged and re-raised so a broken schema fails at startup.
    """
    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column_ddl}")
    except sqlite3.OperationalError as exc:
        if "duplicate column" in str(exc).lower():
            return
        logger.exception("watchlist migration failed adding %s to %s", column_ddl, table)
        raise

_UNSET = object()
_WEEKDAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def validate_schedule(schedule: str | None) -> str | None:
    """Validate schedule string format.

    Accepted formats:
    - 'daily@HH:MM' (24-hour time, e.g. 'daily@08:00')
    - 'weekly@mon@HH:MM' (e.g. 'weekly@mon@08:00')
    Returns canonical lowercase string, or None if schedule is None.
    Raises ValueError on invalid format.
    """
    if schedule is None:
        return None
    if not isinstance(schedule, str):
        raise ValueError("Schedule must be a string or null")  # noqa: TRY004
    s = schedule.strip()
    if not s:
        raise ValueError("Schedule cannot be empty")
    parts = s.split("@")
    kind = parts[0].lower()
    if kind == "daily":
        if len(parts) != 2:
            raise ValueError(f"Invalid daily schedule format '{schedule}': expected 'daily@HH:MM'")
        time_part = parts[1].strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", time_part)
        if not m:
            raise ValueError(f"Invalid time format in schedule '{schedule}': expected HH:MM")
        h, mn = int(m.group(1)), int(m.group(2))
        if not (0 <= h <= 23 and 0 <= mn <= 59):
            raise ValueError(f"Time out of range in schedule '{schedule}': hour 0..23, minute 0..59")
        return f"daily@{h:02d}:{mn:02d}"
    elif kind == "weekly":
        if len(parts) != 3:
            raise ValueError(f"Invalid weekly schedule format '{schedule}': expected 'weekly@mon@HH:MM'")
        wday = parts[1].lower().strip()
        if wday not in _WEEKDAYS:
            raise ValueError(f"Invalid weekday '{parts[1]}' in schedule '{schedule}': must be one of {sorted(_WEEKDAYS)}")
        time_part = parts[2].strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", time_part)
        if not m:
            raise ValueError(f"Invalid time format in schedule '{schedule}': expected HH:MM")
        h, mn = int(m.group(1)), int(m.group(2))
        if not (0 <= h <= 23 and 0 <= mn <= 59):
            raise ValueError(f"Time out of range in schedule '{schedule}': hour 0..23, minute 0..59")
        return f"weekly@{wday}@{h:02d}:{mn:02d}"
    else:
        raise ValueError(f"Invalid schedule format '{schedule}': must start with 'daily@' or 'weekly@'")


def validate_timezone(tz_name: str | None) -> str:
    """Validate timezone name using Python standard library zoneinfo.

    Returns canonical timezone name.
    Raises ValueError if timezone is unknown or invalid.
    """
    if not tz_name or not isinstance(tz_name, str) or not tz_name.strip():
        raise ValueError("Timezone must be a non-empty string")
    clean_tz = tz_name.strip()
    try:
        ZoneInfo(clean_tz)
    except (ZoneInfoNotFoundError, ValueError, Exception) as exc:
        raise ValueError(f"Unknown timezone '{tz_name}'") from exc
    return clean_tz


WATCHLIST_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
  id TEXT PRIMARY KEY,
  feed_url TEXT NOT NULL UNIQUE,
  style TEXT NOT NULL DEFAULT 'balanced',
  format TEXT NOT NULL DEFAULT 'dialog',
  language TEXT NOT NULL DEFAULT 'auto',
  hosts INTEGER NOT NULL DEFAULT 2,
  created_at REAL NOT NULL,
  last_checked REAL,
  enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS watchlist_seen (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_url TEXT NOT NULL,
  normalized_title TEXT NOT NULL,
  first_seen REAL NOT NULL,
  job_id TEXT,
  watchlist_id TEXT
);
"""


def init_watchlist_db() -> None:
    with _conn() as c:
        c.executescript(WATCHLIST_SCHEMA)
        for column in (
            "voice_profile TEXT",
            "last_error TEXT",
            "fail_count INTEGER NOT NULL DEFAULT 0",
            # digest (#122): per-feed mode + source count
            "digest_mode INTEGER NOT NULL DEFAULT 0",
            "digest_count INTEGER NOT NULL DEFAULT 3",
            "explicit INTEGER NOT NULL DEFAULT 0",
            "cover_image TEXT",
            # schedule (VOZONDA-WATCH-SCHEDULE)
            "schedule TEXT",
            "schedule_tz TEXT DEFAULT 'UTC'",
            "last_scheduled_run REAL",
            "show_slug TEXT DEFAULT ''",
        ):
            _add_column(c, "watchlist", column)
        for column in (
            "canonical_url TEXT",
            "normalized_title TEXT",
            "first_seen REAL",
            "job_id TEXT",
            "watchlist_id TEXT",
        ):
            _add_column(c, "watchlist_seen", column)
        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_seen_canonical_url ON watchlist_seen(canonical_url)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_seen_first_seen ON watchlist_seen(first_seen)")
        except Exception:
            logger.warning("watchlist index creation failed", exc_info=True)


def set_last_error(wid: str, error: str | None) -> None:
    """Record the last poll error (None on success) so the ui can show
    why a feed produces nothing instead of failing silently."""
    with _conn() as c:
        c.execute("UPDATE watchlist SET last_error = ? WHERE id = ?", (error, wid))


def record_poll_failure(wid: str, error_msg: str, max_consecutive_failures: int = 5) -> None:
    """Record failure and auto-pause feed after repeated consecutive failures."""
    init_watchlist_db()
    with _conn() as c:
        row = c.execute("SELECT fail_count FROM watchlist WHERE id = ?", (wid,)).fetchone()
        current_fails = (row[0] if row and row[0] is not None else 0) + 1
        if current_fails >= max_consecutive_failures:
            c.execute(
                "UPDATE watchlist SET fail_count = ?, enabled = 0, last_error = ?, last_checked = ? WHERE id = ?",
                (current_fails, f"paused after repeated failures: {error_msg}", time.time(), wid),
            )
        else:
            c.execute(
                "UPDATE watchlist SET fail_count = ?, last_error = ?, last_checked = ? WHERE id = ?",
                (current_fails, error_msg, time.time(), wid),
            )


def record_poll_success(wid: str) -> None:
    """Reset failure counter and error on successful poll."""
    init_watchlist_db()
    with _conn() as c:
        c.execute(
            "UPDATE watchlist SET fail_count = 0, last_error = NULL, last_checked = ? WHERE id = ?",
            (time.time(), wid),
        )


def _row_to_dict(row) -> dict:
    d = dict(row)
    # normalize types
    d["hosts"] = int(d.get("hosts") or 2)
    d["enabled"] = bool(d.get("enabled"))
    d["voice_profile"] = json.loads(d["voice_profile"]) if d.get("voice_profile") else None
    d["fail_count"] = int(d.get("fail_count") or 0)
    # digest (#122)
    d["digest_mode"] = int(d.get("digest_mode") or 0)
    d["digest_count"] = max(2, min(10, int(d.get("digest_count") or 3)))
    # schedule (VOZONDA-WATCH-SCHEDULE)
    d["schedule"] = d.get("schedule") or None
    d["schedule_tz"] = d.get("schedule_tz") or "UTC"
    d["last_scheduled_run"] = float(d["last_scheduled_run"]) if d.get("last_scheduled_run") is not None else None
    d["show_slug"] = str(d.get("show_slug") or "").strip()
    return d


def list_watchlists() -> list[dict]:
    init_watchlist_db()
    with _conn() as c:
        rows = c.execute("SELECT * FROM watchlist ORDER BY created_at ASC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_watchlist(wid: str) -> dict:
    init_watchlist_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM watchlist WHERE id = ?", (wid,)).fetchone()
    if row is None:
        raise KeyError(wid)
    return _row_to_dict(row)


def create_watchlist(
    feed_url: str,
    style: str = "balanced",
    fmt: str = "dialog",
    language: str = "auto",
    hosts: int = 2,
    explicit: bool = False,
    voice: dict | None = None,
    schedule: str | None = None,
    schedule_tz: str = "UTC",
    show_slug: str = "",
) -> dict:
    init_watchlist_db()
    wid = uuid.uuid4().hex[:8]
    now = time.time()
    with _conn() as c:
        c.execute(
            "INSERT INTO watchlist (id, feed_url, style, format, language, hosts, explicit, voice_profile, schedule, schedule_tz, show_slug, created_at, enabled) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (wid, feed_url, style, fmt, language, int(hosts), int(bool(explicit)), json.dumps(voice) if voice else None, schedule, schedule_tz, (show_slug or "").strip(), now, 1),
        )
    return get_watchlist(wid)


def delete_watchlist(wid: str) -> None:
    init_watchlist_db()
    with _conn() as c:
        cur = c.execute("DELETE FROM watchlist WHERE id = ?", (wid,))
        if cur.rowcount == 0:
            raise KeyError(wid)


def update_watchlist(
    wid: str,
    enabled: bool | None = None,
    *,
    voice: dict | None = None,
    digest_mode: int | None = None,
    digest_count: int | None = None,
    style: str | None = None,
    format: str | None = None,
    language: str | None = None,
    hosts: int | None = None,
    explicit: bool | None = None,
    schedule: str | None | object = _UNSET,
    schedule_tz: str | None = None,
    last_scheduled_run: float | None | object = _UNSET,
    cover_image: str | None = None,
    show_slug: str | None | object = _UNSET,
) -> dict:
    init_watchlist_db()
    now = time.time()
    with _conn() as c:
        sets: list[str] = []
        args: list = []
        if enabled is not None:
            sets.append("enabled = ?")
            args.append(1 if enabled else 0)
        if voice is not None:
            sets.append("voice_profile = ?")
            args.append(json.dumps(voice) if voice else None)
        if digest_mode is not None:
            sets.append("digest_mode = ?")
            args.append(int(digest_mode))
        if digest_count is not None:
            sets.append("digest_count = ?")
            args.append(max(2, min(10, int(digest_count))))
        if style is not None:
            sets.append("style = ?")
            args.append(style)
        if format is not None:
            sets.append("format = ?")
            args.append(format)
        if language is not None:
            sets.append("language = ?")
            args.append(language)
        if hosts is not None:
            sets.append("hosts = ?")
            args.append(int(hosts))
        if explicit is not None:
            sets.append("explicit = ?")
            args.append(int(bool(explicit)))
        if schedule is not _UNSET:
            sets.append("schedule = ?")
            args.append(schedule)
            # Setting/changing/clearing schedule rewrites last_scheduled_run
            # (F-5 / Bug 3): now when set, None when cleared
            if last_scheduled_run is _UNSET:
                sets.append("last_scheduled_run = ?")
                args.append(now if schedule is not None else None)
        if schedule_tz is not None:
            sets.append("schedule_tz = ?")
            args.append(schedule_tz)
        if last_scheduled_run is not _UNSET:
            sets.append("last_scheduled_run = ?")
            args.append(last_scheduled_run)
        if cover_image is not None:
            sets.append("cover_image = ?")
            args.append(cover_image)
        if show_slug is not _UNSET:
            sets.append("show_slug = ?")
            args.append(show_slug.strip() if isinstance(show_slug, str) else "")
        args.append(wid)
        if sets:
            cur = c.execute(f"UPDATE watchlist SET {', '.join(sets)} WHERE id = ?", args)
            if cur.rowcount == 0:
                raise KeyError(wid)
    return get_watchlist(wid)


# backward compat: update_enabled(wid, enabled, voice=..., digest_mode=..., digest_count=...)
def update_enabled(wid: str, enabled: bool, voice: dict | None = None, digest_mode: int | None = None, digest_count: int | None = None) -> dict:
    return update_watchlist(wid, enabled=enabled, voice=voice, digest_mode=digest_mode, digest_count=digest_count)


def update_last_checked(wid: str, checked_at: float | None = None) -> None:
    init_watchlist_db()
    with _conn() as c:
        c.execute("UPDATE watchlist SET last_checked = ? WHERE id = ?", (checked_at if checked_at is not None else time.time(), wid))


def update_last_scheduled_run(wid: str, run_at: float | None = None) -> None:
    init_watchlist_db()
    with _conn() as c:
        c.execute("UPDATE watchlist SET last_scheduled_run = ? WHERE id = ?", (run_at if run_at is not None else time.time(), wid))


# ---------------------------------------------------------------------------
# Composite Executive Briefing for multi-article digests (DUE-073 / #258)
# ---------------------------------------------------------------------------

def build_composite_briefing(jobs: list[dict]) -> dict:
    """Compile a structured composite Executive Briefing from multiple jobs.

    jobs: list of job dicts each possibly containing executive_summary and
    key_takeaways (as produced by insights.extract_insights). Returns a dict
    with executive_summary (joined, capped) and key_takeaways (merged, capped
    at 5, preserving source_quote grounding).
    """
    summaries: list[str] = []
    all_tks: list[dict] = []
    for job in jobs:
        es = (job.get("executive_summary") or "").strip()
        if es:
            summaries.append(es)
        tks = job.get("key_takeaways") or []
        if isinstance(tks, list):
            for tk in tks:
                if isinstance(tk, dict) and (tk.get("text") or tk.get("title")):
                    all_tks.append(tk)
    composite_summary = " ".join(summaries)[:600].strip() if summaries else ""
    # cap overall takeaways to 5 for Blinkist-grade density, preserve order
    composite_takeaways = all_tks[:5]
    return {"executive_summary": composite_summary, "key_takeaways": composite_takeaways}


def format_briefing_for_feed(executive_summary: str | None, takeaways: list[dict] | None) -> str:
    """Format briefing as a short text for digest job descriptions.

    Used when a digest job needs a composite description before its own
    LLM-extracted insights are ready (fallback).
    """
    parts: list[str] = []
    if executive_summary and executive_summary.strip():
        parts.append(f"Executive Briefing: {executive_summary.strip()}")
    if takeaways:
        bullets: list[str] = []
        for tk in takeaways:
            if not isinstance(tk, dict):
                continue
            title = str(tk.get("title") or "").strip()
            text = str(tk.get("text") or "").strip()
            if title and text:
                bullets.append(f"* {title}: {text}")
            elif title:
                bullets.append(f"* {title}")
            elif text:
                bullets.append(f"* {text}")
        if bullets:
            parts.append("Key Takeaways:\n" + "\n".join(bullets[:5]))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Cross-watchlist deduplication store (VOZONDA-WATCH-DEDUPE-FIX)
# ---------------------------------------------------------------------------

def record_seen_entry(
    url: str,
    title: str,
    first_seen: float | None = None,
    job_id: str | None = None,
    watchlist_id: str | None = None,
) -> None:
    """Record a seen feed entry for cross-watchlist deduplication."""
    init_watchlist_db()
    c_url = canonical_url(url)
    norm_title = _normalize_title(title)
    ts = float(first_seen) if first_seen is not None else time.time()
    with _conn() as c:
        c.execute(
            "INSERT INTO watchlist_seen (canonical_url, normalized_title, first_seen, job_id, watchlist_id) VALUES (?, ?, ?, ?, ?)",
            (c_url, norm_title, ts, job_id, watchlist_id),
        )


def prune_seen_entries(now: float | None = None, max_age_seconds: float = 72 * 3600) -> int:
    """Prune seen entries older than max_age_seconds (default 72 hours)."""
    init_watchlist_db()
    now_ts = float(now) if now is not None else time.time()
    cutoff = now_ts - max_age_seconds
    with _conn() as c:
        cur = c.execute("DELETE FROM watchlist_seen WHERE first_seen < ?", (cutoff,))
        return cur.rowcount


def get_seen_entries(since: float | None = None) -> list[dict]:
    """Retrieve recently seen entries for deduplication."""
    init_watchlist_db()
    with _conn() as c:
        if since is not None:
            rows = c.execute(
                "SELECT canonical_url, normalized_title, first_seen, job_id, watchlist_id FROM watchlist_seen WHERE first_seen >= ? ORDER BY first_seen DESC",
                (float(since),),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT canonical_url, normalized_title, first_seen, job_id, watchlist_id FROM watchlist_seen ORDER BY first_seen DESC"
            ).fetchall()
    return [
        {
            "canonical_url": r["canonical_url"],
            "link": r["canonical_url"],
            "normalized_title": r["normalized_title"],
            "title": r["normalized_title"],
            "first_seen": float(r["first_seen"]),
            "created_at": float(r["first_seen"]),
            "job_id": r["job_id"],
            "watchlist_id": r["watchlist_id"],
        }
        for r in rows
    ]


def clear_seen_entries() -> None:
    """Clear all seen entries (for test isolation)."""
    init_watchlist_db()
    with _conn() as c:
        c.execute("DELETE FROM watchlist_seen")
