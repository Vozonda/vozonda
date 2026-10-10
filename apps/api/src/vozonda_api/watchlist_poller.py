"""Watchlist poller: turns new feed entries into jobs.

Poller runs as a background asyncio task, every VOZONDA_WATCHLIST_INTERVAL
(default 10 min). Each watchlist feed is fetched with the same SSRF guard
as article fetches, parsed as RSS or Atom via stdlib xml, and for each new
URL (not yet in jobs) a job is created and started through the same
pipeline as POST /jobs.

Deduplication (VOZONDA-WATCH-DEDUPE): before creating a job, the poller
checks if the canonical URL or a near-duplicate title already exists in
the jobs table (exact URL skip) and across ALL feeds in the current poll
batch (canonical URL + title similarity).
"""

import asyncio
import datetime
import logging
import re
import time
import uuid
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException

from .env import env
from .fetcher import (
    FETCH_HEADERS,
    FETCH_MAX_BYTES,
    FETCH_TIMEOUT,
    FetchError,
    guard_url,
    guarded_client,
)
from .jobs import _is_url_rendered
from .watchlist_dedupe import canonical_url, is_duplicate

logger = logging.getLogger(__name__)

POLL_INTERVAL = int(env("WATCHLIST_INTERVAL", "600"))
MAX_NEW_PER_POLL = int(env("WATCHLIST_MAX_NEW", "3"))
# podcast feeds carry many episodes and are routinely several mb,
# far past the 2mb article cap (acast beyond-the-obvious: 2.8mb)
FETCH_SIZE_CAP = max(FETCH_MAX_BYTES, 20_000_000)

_WEEKDAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _show_fields_for_watchlist(watchlist: dict) -> dict:
    """Show reach a watchlist publishes into: {} when no show is set.

    Returns show_slug/show_name/show_author/show_category of the numbered
    show (settings show.<n>.*) so poller jobs read like manual episodes of
    that show for publish_job and the master-feed filter.
    """
    raw = str(watchlist.get("show_slug") or "").strip()
    if not raw:
        return {}
    if raw.lower() == "default":
        try:
            from .settings_store import all_settings

            settings_now = all_settings()
        except Exception:
            return {}
        name = str(settings_now.get("show.name") or "").strip()
        if not name:
            return {}
        return {
            "show_slug": "default",
            "show_name": name,
            "show_author": str(settings_now.get("show.author") or "").strip(),
            "show_category": str(settings_now.get("show.category") or "").strip(),
        }
    num = raw[1:] if raw[:1].lower() == "s" else raw
    if not num.isdigit():
        return {}
    try:
        from .settings_store import all_settings

        settings_now = all_settings()
    except Exception:
        return {}
    name = str(settings_now.get(f"show.{num}.name") or "").strip()
    if not name:
        return {}
    return {
        "show_slug": num,
        "show_name": name,
        "show_author": str(settings_now.get(f"show.{num}.author") or "").strip(),
        "show_category": str(settings_now.get(f"show.{num}.category") or "").strip(),
    }


def parse_feed(xml_text: str) -> list[dict]:
    """Parse RSS 2.0, Atom 1.0, or RSS 1.0/RDF into [{guid, link, title}].

    guid is stable id (guid or id or link). link is the article or episode URL.
    Parses newest first when feed lists newest first; order preserved.
    """
    # quick strip BOM
    xml_text = xml_text.lstrip("\ufeff").strip()
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        return []

    entries: list[dict] = []
    tag = root.tag.lower()

    def local_tag(t: str) -> str:
        return t.split("}")[-1].lower() if "}" in t else t.lower()

    # 1. RSS 2.0 / RSS 0.9x / channel-based feeds
    if tag.endswith("rss") or any(local_tag(c.tag) == "channel" for c in root):
        channel = next((c for c in root if local_tag(c.tag) == "channel"), root)
        for item in [c for c in channel if local_tag(c.tag) == "item"]:
            guid_el = next((c for c in item if local_tag(c.tag) == "guid"), None)
            link_el = next((c for c in item if local_tag(c.tag) == "link"), None)
            title_el = next((c for c in item if local_tag(c.tag) == "title"), None)
            enclosure_el = next((c for c in item if local_tag(c.tag) == "enclosure"), None)

            guid = (guid_el.text.strip() if guid_el is not None and guid_el.text else "") or ""
            link = (link_el.text.strip() if link_el is not None and link_el.text else "") or ""
            title = (title_el.text.strip() if title_el is not None and title_el.text else "") or ""

            # Podcast fallback: if <link> missing in item, check <enclosure url="...">
            if not link and enclosure_el is not None:
                link = (enclosure_el.get("url") or "").strip()
            if not link and guid.startswith("http"):
                link = guid

            stable = guid or link or title
            if not link or not stable:
                continue
            entries.append({"guid": stable, "link": link, "title": title})
        if entries:
            return entries

    # 2. Atom feed: root is feed, entries are entry
    if tag.endswith("feed") or any(local_tag(c.tag) == "entry" for c in root):
        for entry in [c for c in root if local_tag(c.tag) == "entry"]:
            id_el = next((c for c in entry if local_tag(c.tag) == "id"), None)
            title_el = next((c for c in entry if local_tag(c.tag) == "title"), None)
            link_els = [c for c in entry if local_tag(c.tag) == "link"]

            link = ""
            for le in link_els:
                href = le.get("href")
                rel = le.get("rel") or "alternate"
                if href and rel in ("alternate", None):
                    link = href.strip()
                    break
            if not link and link_els:
                for le in link_els:
                    if le.get("href"):
                        link = le.get("href").strip()
                        break
                    elif le.text and le.text.strip().startswith("http"):
                        link = le.text.strip()
                        break

            guid = (id_el.text.strip() if id_el is not None and id_el.text else "") or ""
            title = (title_el.text.strip() if title_el is not None and title_el.text else "") or ""
            stable = guid or link or title
            if not link or not stable:
                continue
            entries.append({"guid": stable, "link": link, "title": title})
        if entries:
            return entries

    # 3. RDF / RSS 1.0 (root is rdf:RDF, items are rdf:item or rss:item)
    for elem in root.iter():
        if local_tag(elem.tag) == "item":
            about = elem.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about") or elem.get("about") or ""
            link_el = next((c for c in elem if local_tag(c.tag) == "link"), None)
            title_el = next((c for c in elem if local_tag(c.tag) == "title"), None)
            guid_el = next((c for c in elem if local_tag(c.tag) == "guid"), None)

            link = (link_el.text.strip() if link_el is not None and link_el.text else "") or about
            title = (title_el.text.strip() if title_el is not None and title_el.text else "") or ""
            guid = (guid_el.text.strip() if guid_el is not None and guid_el.text else "") or about or link

            stable = guid or link or title
            if link and stable:
                entries.append({"guid": stable, "link": link, "title": title})

    return entries


async def fetch_feed_text(feed_url: str) -> str:
    """Fetch feed XML with SSRF guard, size cap, retry.

    Reuses fetcher guard and headers; enforces text-ish types loosely
    (feeds are often application/rss+xml or application/atom+xml).
    """
    guard_url(feed_url)
    async with guarded_client(timeout=FETCH_TIMEOUT, follow_redirects=True, headers=FETCH_HEADERS) as client:
        resp = await client.get(feed_url)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        # allow rss/atom/xml + generic text/html (some feeds serve html)
        allowed = ("application/rss+xml", "application/atom+xml", "application/xml", "text/xml", "text/plain", "text/html", "application/xhtml+xml")
        if ctype and ctype not in allowed and not ctype.endswith("+xml"):
            # still try to parse; many servers send wrong type
            pass
        # bounded read: truncate at the cap, never discard the first
        # oversized chunk (that made big feeds look empty)
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_bytes():
            chunks.append(chunk)
            total += len(chunk)
            if total >= FETCH_SIZE_CAP:
                break
        raw = b"".join(chunks)[:FETCH_SIZE_CAP].decode(resp.encoding or "utf-8", errors="replace")
        return raw


def is_schedule_due(
    schedule: str | None,
    schedule_tz: str | None = None,
    last_scheduled_run: float | None = None,
    now: float | datetime.datetime | None = None,
    *,
    created_at: float | None = None,
) -> bool:
    """Check whether a scheduled watchlist is due for a digest run.

    Supports 'daily@HH:MM' and 'weekly@mon@HH:MM' in the given timezone
    (default UTC). Returns True if a scheduled run should execute at `now`,
    handling timezone conversion, missed-run catch-up, and repeated polls in
    the same slot.
    """
    if not schedule:
        return False
    parts = schedule.strip().split("@")
    kind = parts[0].lower()
    if kind not in ("daily", "weekly"):
        return False

    tz_str = (schedule_tz or "UTC").strip()
    try:
        tz = ZoneInfo(tz_str)
    except Exception:
        tz = ZoneInfo("UTC")

    if now is None:
        now_dt = datetime.datetime.now(tz=tz)
    elif isinstance(now, (int, float)):
        now_dt = datetime.datetime.fromtimestamp(now, tz=tz)
    elif isinstance(now, datetime.datetime):
        now_dt = now.astimezone(tz) if now.tzinfo is not None else now.replace(tzinfo=tz)
    else:
        return False

    now_ts = float(now) if isinstance(now, (int, float)) else float(now.timestamp()) if now is not None else time.time()

    if kind == "daily":
        if len(parts) != 2:
            return False
        time_part = parts[1].strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", time_part)
        if not m:
            return False
        target_h, target_m = int(m.group(1)), int(m.group(2))
        today_slot = datetime.datetime(now_dt.year, now_dt.month, now_dt.day, target_h, target_m, 0, tzinfo=tz)
        if now_dt >= today_slot:
            latest_slot = today_slot
        else:
            latest_slot = today_slot - datetime.timedelta(days=1)
    elif kind == "weekly":
        if len(parts) != 3:
            return False
        wday_str = parts[1].lower().strip()
        if wday_str not in _WEEKDAY_MAP:
            return False
        target_wday = _WEEKDAY_MAP[wday_str]
        time_part = parts[2].strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", time_part)
        if not m:
            return False
        target_h, target_m = int(m.group(1)), int(m.group(2))
        days_since = (now_dt.weekday() - target_wday) % 7
        today_slot_date = now_dt.date() - datetime.timedelta(days=days_since)
        today_slot = datetime.datetime(today_slot_date.year, today_slot_date.month, today_slot_date.day, target_h, target_m, 0, tzinfo=tz)
        if now_dt >= today_slot:
            latest_slot = today_slot
        else:
            # Before the current week's slot - check previous week's slot for catch-up
            latest_slot = today_slot - datetime.timedelta(weeks=1)

    latest_slot_ts = latest_slot.timestamp()

    if last_scheduled_run is not None:
        return float(last_scheduled_run) < latest_slot_ts

    if created_at is not None:
        # Catch-up: fire only if slot is before simulated "now" (past slot)
        # AND after creation (valid catch-up window)
        return latest_slot_ts <= now_ts and float(created_at) < latest_slot_ts

    return now_dt >= latest_slot


async def trigger_watchlist_digest(
    wid: str,
    store,
    tasks: dict,
    listeners: dict,
    *,
    count: int | None = None,
    min_entries: int = 1,
    is_scheduled: bool = False,
    run_at: float | None = None,
) -> dict | None:
    """Bundle unrendered feed entries into one digest job (#122).

    Reused by both POST /watchlist/{wid}/digest (min_entries=2) and the
    background poller for scheduled digests (min_entries=1).
    """
    from .watchlist import get_watchlist, record_poll_failure, record_poll_success, update_last_scheduled_run

    try:
        wl = get_watchlist(wid)
    except KeyError:
        if not is_scheduled:
            raise HTTPException(404, "no such watchlist") from None
        return None

    digest_count = count if count is not None else max(2, min(10, int(wl.get("digest_count") or 3)))
    try:
        xml_text = await fetch_feed_text(wl["feed_url"])
        entries = parse_feed(xml_text)
    except FetchError as exc:
        record_poll_failure(wid, f"feed fetch failed: {exc}")
        if not is_scheduled:
            raise HTTPException(502, f"feed fetch failed: {exc}") from exc
        return None
    except Exception as exc:
        record_poll_failure(wid, f"feed parse failed: {exc}")
        if not is_scheduled:
            raise HTTPException(502, f"feed parse failed: {exc}") from exc
        return None

    if not entries:
        record_poll_failure(wid, "feed contains no entries")
        if not is_scheduled:
            raise HTTPException(422, "feed contains no entries")
        print(f"[watchlist-schedule] watchlist {wid}: feed contains no entries, skipping digest")
        if is_scheduled and run_at is not None:
            update_last_scheduled_run(wid, run_at)
        return None

    candidates: list[str] = []
    seen: set[str] = set()
    for ent in entries:
        link = (ent.get("link") or "").strip()
        if not link or link in seen:
            continue
        try:
            guard_url(link)
        except FetchError:
            continue
        seen.add(link)
        if _is_url_rendered(link):
            continue  # already rendered (or rendering)
        candidates.append(link)
        if len(candidates) >= digest_count:
            break

    if len(candidates) < min_entries:
        if not is_scheduled:
            raise HTTPException(
                422,
                f"not enough fresh entries for a digest ({len(candidates)} new, need {min_entries}). hit check now first or wait for new articles.",
            )
        # Scheduled run with no new entries: no episode, one log line
        # Only record success if we actually checked (no fetch/parse errors)
        record_poll_success(wid)
        print(f"[watchlist-schedule] watchlist {wid}: no new entries, skipping episode")
        if run_at is not None:
            update_last_scheduled_run(wid, run_at)
        return None

    job_id = f"digest-{uuid.uuid4().hex[:12]}"
    store.create(
        job_id,
        f"digest:{job_id}",
        wl.get("style") or "balanced",
        wl.get("format") or "dialog",
        "neutral",
        wl.get("language") or "auto",
        watchlist_id=wid,
        hosts=int(wl.get("hosts") or 2),
        explicit=bool(wl.get("explicit")),
        voice=wl.get("voice_profile"),
        digest=True,
        digest_sources=candidates,
        **_show_fields_for_watchlist(wl),
    )
    listeners[job_id] = []
    from .main import _run

    tasks[job_id] = asyncio.create_task(_run(job_id))
    record_poll_success(wid)
    if run_at is not None:
        update_last_scheduled_run(wid, run_at)
    return {"digest_job": job_id, "sources": candidates}


async def poll_single(
    watchlist: dict,
    store,
    tasks: dict,
    listeners: dict,
    *,
    is_manual: bool = False,
    now: float | None = None,
) -> list[str]:
    """Poll one watchlist feed, create jobs for new URLs.

    Returns list of created job ids.
    """
    from .settings_store import get_setting
    from .watchlist import record_poll_failure, record_poll_success

    feed_url = watchlist["feed_url"]
    style = watchlist.get("style") or "balanced"
    fmt = watchlist.get("format") or "dialog"
    language = watchlist.get("language") or "auto"
    wid = watchlist["id"]
    schedule = watchlist.get("schedule")

    if schedule:
        now_ts = now if now is not None else time.time()
        tz_name = watchlist.get("schedule_tz") or "UTC"
        last_run = watchlist.get("last_scheduled_run")
        created_at = watchlist.get("created_at")

        # Manual check bypasses the schedule gate (F-3)
        if not is_manual and not is_schedule_due(schedule, tz_name, last_run, now_ts, created_at=created_at):
            return []

        digest_res = await trigger_watchlist_digest(
            wid,
            store,
            tasks,
            listeners,
            min_entries=1,
            is_scheduled=not is_manual,
            run_at=now_ts if not is_manual else None,
        )
        if digest_res and "digest_job" in digest_res:
            return [digest_res["digest_job"]]
        return []

    created: list[str] = []

    # Resolution of max new jobs per poll (#165):
    # If manual check: allow catch-up (up to MAX_NEW_PER_POLL).
    # If auto poll: check global setting 'watchlist.render_mode'. Default is 'newest' (1 per check).
    render_mode = get_setting("watchlist.render_mode") or "newest"
    max_limit = MAX_NEW_PER_POLL if (is_manual or render_mode == "catchup") else 1

    try:
        xml_text = await fetch_feed_text(feed_url)
        entries = parse_feed(xml_text)
        # limit to newest N entries per feed (feed already newest first)
        entries = entries[:20]
        if not entries:
            record_poll_failure(wid, "feed fetched but contains no entries")
            return []
        # deduplicate by URL already in jobs
        # check existence via SQLite to avoid loading all jobs
        from .watchlist import get_seen_entries, prune_seen_entries, record_seen_entry
        from .watchlist_dedupe import _72H

        now_entry = now if now is not None else time.time()
        # Prune entries older than 72 h across all watchlists
        prune_seen_entries(now=now_entry)

        # Collect all entries seen across watchlists within 72 h for cross-feed dedup
        seen_all: list[dict] = get_seen_entries(since=now_entry - _72H)
        # Use set for quick check within this poll batch
        seen_urls: set[str] = set()
        for ent in entries:
            link = ent["link"].strip()
            if not link or link in seen_urls:
                continue
            # SSRF guard for each entry link too (don't queue local URLs)
            try:
                guard_url(link)
            except FetchError:
                continue
            seen_urls.add(link)
            # check if job with this URL already exists (any state)
            if _is_url_rendered(link):
                continue
            # cross-feed dedup: skip if canonical URL or near-duplicate title
            # already present in entries from earlier feeds (or earlier in
            # this feed) within the last 72 hours
            entry_doc = {"link": link, "title": ent.get("title") or "", "created_at": now_entry}
            if is_duplicate(entry_doc, seen_all):
                ref_urls = [canonical_url(r["link"]) for r in seen_all if canonical_url(r["link"]) == canonical_url(link)]
                ref_titles = [r.get("title", "") for r in seen_all if r.get("title") and (r.get("title") == ent.get("title") or (len(r.get("title", "")) > 2 and len(ent.get("title", "")) > 2))]
                match_info = f"canonical: {ref_urls[0] if ref_urls else ''}; title: {ref_titles[0] if ref_titles else ''}"
                print(f"[watchlist-dedup] skipping {link}: duplicate of {match_info}")
                continue
            # add to seen_all for subsequent cross-feed dedup checks
            seen_all.append(entry_doc)
            # create job, start pipeline
            # guard again for url host private after fetch guard (duplicate)
            # use same readable id logic as POST /jobs
            from .main import _readable_id, _run

            job_id = _readable_id(link)
            # ensure watchlist_id + hosts stored (W2)
            hosts = int(watchlist.get("hosts") or 2)
            explicit = bool(watchlist.get("explicit"))
            try:
                store.create(job_id, link, style, fmt, "neutral", language, watchlist_id=wid, hosts=hosts, explicit=explicit, voice=watchlist.get("voice_profile"), **_show_fields_for_watchlist(watchlist))
            except Exception:
                continue
            # Persist seen entry across all watchlists
            record_seen_entry(link, ent.get("title") or "", first_seen=now_entry, job_id=job_id, watchlist_id=wid)
            listeners[job_id] = []
            tasks[job_id] = asyncio.create_task(_run(job_id))
            created.append(job_id)
            if len(created) >= max_limit:
                break
        record_poll_success(wid)
    except (FetchError, httpx.HTTPError, httpx.TimeoutException) as e:
        record_poll_failure(wid, f"{type(e).__name__}: {e}")
    except Exception as e:
        record_poll_failure(wid, f"{type(e).__name__}: {e}")
    return created


async def poll_all(store, tasks: dict, listeners: dict, *, now: float | None = None) -> int:
    from .watchlist import list_watchlists

    watchlists = list_watchlists()
    total = 0
    for wl in watchlists:
        if not wl.get("enabled", True):
            continue
        created = await poll_single(wl, store, tasks, listeners, now=now)
        total += len(created)
        # small gap between feeds
        await asyncio.sleep(0.2)
    return total


async def start_poller(store, tasks: dict, listeners: dict) -> None:
    # wait a bit after startup before first poll
    await asyncio.sleep(10)
    while True:
        try:
            await poll_all(store, tasks, listeners)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("watchlist poll cycle failed", exc_info=True)
        await asyncio.sleep(POLL_INTERVAL)