import email.utils
import hashlib
import hmac
import html as htmllib
import json
import logging
import sqlite3
from itertools import pairwise
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from ..env import env
from ..public_address import public_base
from ..settings_store import (
    get_private_feed_key,
    get_setting,
    resolve_show_public,
    resolve_show_rss,
)

router = APIRouter()
logger = logging.getLogger("vozonda_api.feeds")

# Newest episodes a feed carries. Every request builds the whole feed, so an
# unbounded feed grows with the archive; podcast apps only read the head.
FEED_MAX_ITEMS = int(env("FEED_MAX_ITEMS", "300"))


async def _require_write_auth(authorization: str | None = Header(None)) -> None:
    from ..main import require_write_auth

    await require_write_auth(authorization)


def _format_duration(ms: int | None) -> str | None:
    if ms is None:
        return None
    try:
        s = int(ms // 1000)  # type: ignore[operator]
    except Exception:
        return None
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _extract_insights_from_row(row: dict) -> tuple[str, list[dict]]:
    """Extract executive_summary and key_takeaways from a jobs row dict."""
    exec_summary = ""
    try:
        exec_summary = (row.get("executive_summary") or "").strip()  # type: ignore[union-attr]
    except Exception:
        exec_summary = ""
    tks: list[dict] = []
    raw = row.get("key_takeaways")
    if raw is None:
        # also try sqlite Row direct access fallback
        try:
            raw = row.get("key_takeaways")  # type: ignore[attr-defined]
        except Exception:
            raw = None
    if isinstance(raw, list):
        tks = [tk for tk in raw if isinstance(tk, dict)]
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                tks = [tk for tk in parsed if isinstance(tk, dict)]
        except Exception:
            tks = []
    return exec_summary, tks


def _enrich_description_for_feed(base_desc: str, exec_summary: str, takeaways: list[dict]) -> str:
    """Build enriched description with executive summary and bulleted takeaways."""
    parts: list[str] = []
    if base_desc and base_desc.strip():
        parts.append(base_desc.strip())
    if exec_summary and exec_summary.strip():
        parts.append(f"Executive Summary: {exec_summary.strip()}")
    if takeaways:
        bullets: list[str] = []
        for tk in takeaways:
            if not isinstance(tk, dict):
                continue
            title = str(tk.get("title") or "").strip()
            text = str(tk.get("text") or "").strip()
            if title and text:
                bullets.append(f"• {title}: {text}")
            elif title:
                bullets.append(f"• {title}")
            elif text:
                bullets.append(f"• {text}")
        if bullets:
            parts.append("Key Takeaways:\n" + "\n".join(bullets[:5]))
    if len(parts) <= 1:
        return parts[0] if parts else base_desc
    return "\n\n".join(parts)


def _feed_is_public(show_num: str | None = None) -> bool:
    """Private unless the owner opted in per show; falls back to global feed.public.
    An unset value is private (the UI default says so too), and a settings error fails closed."""
    try:
        if show_num is not None:
            return str(resolve_show_public(show_num) or "0").strip() == "1"
        # Legacy global check (used for backward compatibility in some places)
        return str(get_setting("feed.public") or "0").strip() == "1"
    except Exception:
        return False


def _require_feed_access(key: str | None, show_num: str | None = None) -> None:
    """Feeds are private by default: a wrong or missing key is a 404, never
    a 401, so the feed's existence is not revealed. Per-show public check
    when show_num is provided."""
    if _feed_is_public(show_num):
        return
    expected = get_private_feed_key()
    if not key or not hmac.compare_digest(str(key).encode(), expected.encode()):
        raise HTTPException(404, "not found")


def _with_source_attribution(desc: str, sources: list[str]) -> str:
    if not sources:
        return desc
    lines = "\n".join(f"Source: {s}" for s in sources)
    return f"{desc}\n\n{lines}" if desc.strip() else lines


def _format_source_line(i: int, s: dict) -> str:
    """One public source line (VOZONDA-TRAY-CITATIONS): '[n] title' plus the
    link url for link sources. Uploads and notes show by title only, never
    with text or a file name."""
    title = str(s.get("title") or "").strip()
    url = str(s.get("origin_url") or "").strip()
    if url:
        label = title if title else url
        if label == url:
            return f"[{i + 1}] {url}"
        return f"[{i + 1}] {label} — {url}"
    return f"[{i + 1}] {title or 'untitled'}"


def _sources_block(row: dict) -> str:
    """The public 'Sources:' list for a feed item, or '' for 0-1 sources.

    From sources.job_sources (public form, no source text). Feed rows carry
    digest_sources as a raw JSON string, which is parsed first."""
    try:
        from .. import sources as _sources_mod

        job = dict(row)
        raw = job.get("digest_sources")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                job["digest_sources"] = parsed if isinstance(parsed, list) else None
            except Exception:
                job["digest_sources"] = None
        items = _sources_mod.job_sources(job)
    except Exception:
        return ""
    if len(items) <= 1:
        return ""
    return "Sources:\n" + "\n".join(_format_source_line(i, s) for i, s in enumerate(items))


def _setting_str(key: str) -> str:
    try:
        return str(get_setting(key) or "").strip()
    except Exception:
        return ""


def _split_setting(key: str, default: int) -> int:
    try:
        val = int(float(_setting_str(key) or default))
    except ValueError:
        val = default
    return min(100, max(0, val))


def _show_num_for_slug(slug: str) -> str | None:
    """Resolve a show slug to its numeric index.

    Accepts numeric form first (as jobs.show_slug stores it via _show_index_for):
    - '1', 's1' -> check show.1.name exists, return '1'
    Falls back to name-based lookup: 'my-show' -> show.<n>.name case-insensitive match.
    Returns None if not found or on any error."""
    from ..settings_store import all_settings

    try:
        all_settings_dict = all_settings()
    except Exception:
        return None

    # First try numeric form (strip one optional leading 's') or 'default'
    clean = slug.strip()
    if clean.lower() == "default" and all_settings_dict.get("show.name"):
        return "default"
    candidate = clean[1:] if clean[:1].lower() == "s" else clean
    if candidate.isdigit() and all_settings_dict.get(f"show.{candidate}.name"):
        return candidate

    # Fall back to name-based lookup over every show that exists (gaps included: the old loop stopped at
    # the first missing number, so after deleting show 1 no later show was found by name)
    from ..settings_store import show_numbers

    name = slug.replace("-", " ").strip().casefold()
    if not name:
        return None
    for i in show_numbers():
        if str(all_settings_dict.get(f"show.{i}.name") or "").strip().casefold() == name:
            return str(i)
    return None


def _watchlist_show_num(watchlist: dict) -> str:
    """The show a watchlist's episodes belong to: its show_slug ('default', 's<n>' or '<n>'), else the
    default show (also when that show was deleted)."""
    slug = str(watchlist.get("show_slug") or "").strip()
    if not slug or slug.lower() == "default":
        return "default"
    return _show_num_for_slug(slug) or "default"


def _job_show_num(job) -> str:
    """The show an episode belongs to: its show_slug, else its show_name, else its watchlist's show, else
    the default show (also when its show was deleted). Feeds and access.job_is_public use this one rule,
    so a feed link and the media gate never disagree about an episode."""
    keys = job.keys() if hasattr(job, "keys") else ()
    for field in ("show_slug", "show_name"):
        value = str((job[field] if field in keys else "") or "").strip()
        if value:
            num = _show_num_for_slug(value.replace(" ", "-") if field == "show_name" else value)
            if num:
                return num
    wid = str((job["watchlist_id"] if "watchlist_id" in keys else "") or "").strip()
    if wid:
        try:
            from ..watchlist import get_watchlist

            return _watchlist_show_num(get_watchlist(wid))
        except Exception:
            # a deleted watchlist: its episodes follow the default show, like those of a deleted show
            logger.debug("episode's watchlist %s not found; default show", wid, exc_info=True)
    return "default"


def _public_checker():
    """Per request: is an episode public (its show public and with RSS on)? Cached per show, so a feed of
    300 episodes reads the settings once per show, not once per episode."""
    cache: dict[str, bool] = {}

    def is_public(job) -> bool:
        num = _job_show_num(job)
        if num not in cache:
            cache[num] = _feed_is_public(num) and resolve_show_rss(num) == "1"
        return cache[num]

    return is_public


def _done_rows(where: str = "", params: tuple = ()) -> list:
    from ..jobs import DB_PATH

    sql = f"SELECT * FROM jobs WHERE state='done'{where} ORDER BY created_at DESC LIMIT ?"
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, (*params, FEED_MAX_ITEMS)).fetchall()


def _filter_rows_by_rss(rows: list) -> list:
    """Filter out episodes whose show has rss disabled ('0')."""
    filtered = []
    for row in rows:
        show_slug = row["show_slug"] if "show_slug" in row.keys() else ""  # noqa: SIM118
        if not show_slug:
            # No show association - include (default show behavior)
            filtered.append(row)
            continue
        show_num = _show_num_for_slug(show_slug)
        if show_num is None:
            # Show not found in settings - include
            filtered.append(row)
            continue
        if resolve_show_rss(show_num) == "1":
            filtered.append(row)
    return filtered


def _master_meta(row: dict) -> dict:
    try:
        stages = json.loads(row.get("stages") or "[]")
        master = next((s for s in stages if s.get("name") == "master"), {})
        return master.get("meta") or {}
    except Exception:
        return {}


def _chapters_xml(row: dict) -> str:
    try:
        chapters = json.loads(row["chapters"]) if row.get("chapters") else None
        script = json.loads(row["script"]) if row.get("script") else None
    except Exception:
        return ""
    if not chapters or not isinstance(chapters, list):
        return ""
    from ..main import _format_vtt_ts

    script_lines = script if isinstance(script, list) else []
    parts: list[str] = []
    for i, ch in enumerate(chapters):
        ch_title = htmllib.escape(str(ch.get("title", f"Chapter {i + 1}")), quote=True)
        start_ts = _format_vtt_ts(0.0)
        word_offset = ch.get("word_offset", 0)
        cum_words = 0
        for sl in script_lines:
            sl_words = len(str(sl.get("text", "")).split())
            if cum_words + sl_words > word_offset:
                try:
                    start_ts = _format_vtt_ts(float(sl.get("t0", 0.0)))
                except (ValueError, TypeError):
                    start_ts = _format_vtt_ts(0.0)
                break
            cum_words += sl_words
        parts.append(f'<podcast:chapter index="{i}" start="{start_ts}" title="{ch_title}" />')
    return "<podcast:chapters>" + "".join(parts) + "</podcast:chapters>" if parts else ""


def _value_xml(dur_ms, recipients: list[tuple[str, str, int]]) -> str:
    """DUE-021 value-for-value block; empty without a creator address."""
    if not recipients or recipients[0][0] != "creator":
        return ""
    try:
        dur_s = float(dur_ms) / 1000.0 if dur_ms is not None else 0.0
    except Exception:
        dur_s = 0.0
    sat = max(5, round(dur_s * 0.5)) if dur_s > 0 else 10
    recips = "".join(
        f'<podcast:valueRecipient name="{name}" type="node" address="{htmllib.escape(addr, quote=True)}" split="{split}" />'
        for name, addr, split in recipients
    )
    return f'<podcast:value type="lightning" method="keysend" suggested="{sat / 1e8:.11f}">{recips}</podcast:value>'


def _disclosure_text(row: dict) -> str:
    """AI disclosure sentence for feeds and episode page, or '' when disabled."""
    try:
        if get_setting("disclosure.ai_label") != "1":
            return ""
    except Exception:
        return ""
    try:
        stages_raw = row.get("stages")
        if isinstance(stages_raw, str):
            stages = json.loads(stages_raw) if stages_raw else []
        else:
            stages = stages_raw or []
        stages_dict = {s["name"]: s for s in stages} if isinstance(stages, list) else stages  # type: ignore[arg-type]
        script_meta = stages_dict.get("script", {}).get("meta", {}) if isinstance(stages_dict.get("script"), dict) else {}
        voice_meta = stages_dict.get("voice", {}).get("meta", {}) if isinstance(stages_dict.get("voice"), dict) else {}
        llm_model = script_meta.get("llm_model") or script_meta.get("llm_provider") or "AI"
        tts_engine = voice_meta.get("engine") or "AI"
        return f"AI-generated: script by {llm_model}, voices by {tts_engine}."
    except Exception:
        return ""


def _now_rfc() -> str:
    return email.utils.formatdate(usegmt=True)


def _feed_item(row: dict, base: str, now_rfc: str, recipients: list[tuple[str, str, int]],
               key_q: str = "", is_public=None) -> str:
    from ..main import _job_source_urls

    jid = row["id"]
    title = htmllib.escape((row.get("title") or row.get("url") or jid), quote=True)
    desc_raw = (row.get("description") or "").strip()
    if not desc_raw:
        desc_raw = (
            f"{row.get('style') or 'balanced'} · {row.get('format') or 'dialog'} · "
            f"{len(json.loads(row.get('script') or '[]'))} turns"
        )
    exec_summary, tks = _extract_insights_from_row(row)
    enriched = _enrich_description_for_feed(desc_raw, exec_summary, tks)
    enriched = _with_source_attribution(enriched, _job_source_urls(row))
    sources_block = _sources_block(row)
    if sources_block:
        enriched = f"{enriched}\n\n{sources_block}" if enriched.strip() else sources_block
    disclosure = _disclosure_text(row)
    if disclosure:
        enriched = f"{enriched}\n\n{disclosure}"
    desc = htmllib.escape(enriched, quote=True)
    try:
        pub = email.utils.formatdate(float(row.get("created_at") or 0), usegmt=True)
    except Exception:
        pub = now_rfc
    # A private episode's links carry the key when the feed was opened with it; a public one's never do.
    # The guid never carries the key.
    ep_is_public = (is_public or _public_checker())(row)
    item_key_q = key_q if key_q and not ep_is_public else ""
    # A private feed's media links carry the feed key (key_q), or podcast apps outside the host get 404
    # (GHSA-crq5-73gf-fv2h). The guid stays without it, so a key change does not duplicate episodes.
    audio_url = htmllib.escape(f"{base}/audio/{jid}.mp3{item_key_q}", quote=True)
    guid = htmllib.escape(f"{base}/e/{jid}", quote=True)
    page_url = htmllib.escape(f"{base}/e/{jid}{item_key_q}", quote=True)
    meta = _master_meta(row)
    dur_ms = row.get("duration_ms")
    if dur_ms is None and isinstance(meta.get("duration_ms"), (int, float)):
        dur_ms = meta["duration_ms"]
    dur_tag = f"<itunes:duration>{_format_duration(int(dur_ms))}</itunes:duration>" if dur_ms is not None else ""
    audio_bytes = (meta.get("audio") or {}).get("bytes")
    length = str(audio_bytes) if isinstance(audio_bytes, int) else "0"
    expl_tag = "<itunes:explicit>yes</itunes:explicit>" if row.get("explicit") else ""
    # Cover image from og_image: only on episodes that have one.
    # Private episodes carry the key on the image link.
    og_image = str(row.get("og_image") or "")
    image_tag = _itunes_image_xml(og_image if og_image else None, item_key_q, base)
    return (
        f"<item><title>{title}</title>"
        f"<link>{page_url}</link>"
        f"<guid isPermaLink=\"true\">{guid}</guid>"
        f"<description>{desc}</description>"
        f"<itunes:summary>{desc}</itunes:summary>"
        f"{expl_tag}"
        f"{_value_xml(dur_ms, recipients)}"
        f'<podcast:transcript url="{htmllib.escape(f"{base}/vtt/{jid}.vtt{key_q}", quote=True)}" type="text/vtt" />'
        f"{_chapters_xml(row)}"
        f"<pubDate>{pub}</pubDate>"
        f"<enclosure url=\"{audio_url}\" length=\"{length}\" type=\"audio/mpeg\" />"
        f"{image_tag}"
        f"{dur_tag}</item>"
    )


def _p20_key(show_num: str | None, field: str) -> str:
    """Settings key of a channel value: the default show (whose feed is also the main feed) uses
    show.<field> like its name and author, every other show show.<num>.<field>."""
    return f"show.{field}" if show_num in (None, "default") else f"show.{show_num}.{field}"


def _compute_guid(feed_url: str, self_path: str) -> str:
    """podcast:guid of one feed: UUIDv5 (the spec's namespace) over its URL without scheme, query and
    trailing slash, stored the first time under the feed's path (feed.guids) and from then on read,
    never recomputed, so it survives a new public address or feed key. Per path, because a show's
    feed and the feeds of its watchlists are different feeds and need different guids."""
    import uuid

    try:
        guids = json.loads(_setting_str("feed.guids") or "{}")
        if not isinstance(guids, dict):
            guids = {}
    except (json.JSONDecodeError, TypeError):
        logger.warning("feed.guids is not JSON; starting a new map")
        guids = {}
    stored = str(guids.get(self_path) or "").strip()
    if stored:
        return stored
    clean = feed_url.split("?", 1)[0].split("://", 1)[-1].rstrip("/")
    guid = str(uuid.uuid5(uuid.UUID("ead4c236-bf58-58c6-a2c6-a6b28d128cb6"), clean))
    guids[self_path] = guid
    try:
        from ..settings_store import set_setting

        set_setting("feed.guids", json.dumps(guids, sort_keys=True))
    except Exception:
        # the feed still renders; without the stored value the guid would follow the next address change
        logger.warning("could not store the guid of %s", self_path, exc_info=True)
    return guid


def _podcast_txt_xml(show_num: str | None) -> str:
    """podcast:txt from a JSON list of {"purpose", "value"} (how a show is claimed in the index)."""
    raw = _setting_str(_p20_key(show_num, "txt"))
    if not raw:
        return ""
    try:
        entries = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("%s is not JSON; no podcast:txt", _p20_key(show_num, "txt"))
        return ""
    if not isinstance(entries, list):
        return ""
    parts: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not str(entry.get("value") or "").strip():
            continue
        purpose = htmllib.escape(str(entry.get("purpose") or "").strip(), quote=True)
        value = htmllib.escape(str(entry["value"]).strip(), quote=True)
        attr = f' purpose="{purpose}"' if purpose else ""
        parts.append(f"<podcast:txt{attr}>{value}</podcast:txt>")
    return "".join(parts)


def _podcast_locked_xml(show_num: str | None) -> str:
    """podcast:locked: only when the feed is locked and the owner e-mail (one for all shows) is set."""
    if _setting_str(_p20_key(show_num, "locked")) != "1":
        return ""
    owner_email = _setting_str("show.owner_email")
    if not owner_email:
        return ""
    return f'<podcast:locked owner="{htmllib.escape(owner_email, quote=True)}">yes</podcast:locked>'


_FREQ = {
    "daily": ("FREQ=DAILY", "Daily"),
    "weekly": ("FREQ=WEEKLY", "Weekly"),
    "biweekly": ("FREQ=WEEKLY;INTERVAL=2", "Every two weeks"),
    "monthly": ("FREQ=MONTHLY", "Monthly"),
}
_FREQ_DAYS = {"daily": 1, "weekly": 7, "biweekly": 14, "monthly": 30}


def _podcast_update_frequency(rows: list, show_num: str | None = None, watchlist_id: str = "") -> str:
    """podcast:updateFrequency: a feed fed by a scheduled watchlist says its schedule; otherwise the
    gaps between the feed's last five episodes decide (all within 20 % of 1, 7, 14 or 30 days);
    no clear rhythm or fewer than three episodes: no tag."""
    label = ""
    try:
        from ..watchlist import list_watchlists

        for wl in list_watchlists():
            if watchlist_id and wl.get("id") != watchlist_id:
                continue
            if not watchlist_id and (show_num is None or _watchlist_show_num(wl) != show_num):
                continue
            schedule = str(wl.get("schedule") or "").strip().lower()
            label = "daily" if schedule.startswith("daily") else "weekly" if schedule.startswith("weekly") else ""
            if label:
                break
    except Exception:
        # no watchlist table yet or a broken row: fall back to the episode gaps below
        logger.debug("watchlist schedules unreadable for updateFrequency", exc_info=True)
    if not label:
        times = sorted(float(dict(r).get("created_at") or 0) for r in rows)
        times = [t for t in times if t > 0][-5:]
        gaps = [b - a for a, b in pairwise(times)]
        if len(gaps) >= 2:
            for name, days in _FREQ_DAYS.items():
                ref = days * 86400.0
                if all(abs(g - ref) <= 0.2 * ref for g in gaps):
                    label = name
                    break
    if not label:
        return ""
    rrule, text = _FREQ[label]
    return f'<podcast:updateFrequency rrule="{rrule}">{text}</podcast:updateFrequency>'


def _itunes_image_xml(og_image: str | None, item_key_q: str, base: str) -> str:
    """itunes:image tag on item level when the episode has cover art.

    On private episodes (item_key_q is set), the image URL carries the key."""
    if not og_image:
        return ""
    # og_image is stored as a filename; if it's a full URL use it as-is
    if og_image.startswith("http"):
        url = og_image
    else:
        url = f"{base}/img/{og_image}"
    # Private episodes: image link carries the feed key
    if item_key_q:
        url = f"{url}{item_key_q}"
    return f'<itunes:image href="{htmllib.escape(url, quote=True)}" />'


def _render_feed(request: Request, rows: list, *, self_path: str, key: str | None,
                 show_num: str | None = None, show_title: str | None = None,
                 watchlist_id: str = "") -> Response:
    """One RSS builder for the main feed and the per-show feeds."""
    base = public_base(request)
    creator_addr = _setting_str("feed.creator.address")
    recipients: list[tuple[str, str, int]] = []
    if creator_addr:
        for name, default in (("creator", 70), ("source", 20), ("app", 10)):
            addr = _setting_str(f"feed.{name}.address")
            split = _split_setting(f"feed.{name}.split", default)
            if addr and split > 0:
                recipients.append((name, addr, split))
    now_rfc = _now_rfc()
    # Opened with the valid key: every link may carry it, and each episode decides in _feed_item (a public
    # episode's links stay without it). Deciding by the feed's own show lost the key on private episodes
    # in a master feed whose default show is public.
    valid_key = bool(key) and hmac.compare_digest(str(key).encode(), get_private_feed_key().encode())
    key_q = f"?key={quote(key)}" if valid_key else ""
    is_public = _public_checker()
    items = "".join(_feed_item(dict(r), base, now_rfc, recipients, key_q, is_public) for r in rows)

    # A private feed's self link must carry the key, or apps that refresh
    # through atom:link lose access.
    self_url = f"{base}{self_path}" + key_q
    funding_tag = (
        f'<podcast:funding url="lightning:{htmllib.escape(creator_addr, quote=True)}">Support the show</podcast:funding>'
        if creator_addr
        else ""
    )
    title = htmllib.escape(show_title or _setting_str("show.name") or "Vozonda", quote=True)
    show_desc_val = (_setting_str(f"show.{show_num}.description") if show_num else "") or _setting_str("show.description")
    show_desc = htmllib.escape(
        show_desc_val or "Vozonda: Sovereign audio overviews. Your voices, your feeds. Open source & private.",
        quote=True,
    )
    show_author = htmllib.escape(_setting_str("show.author") or creator_addr or "Vozonda", quote=True)
    show_category = htmllib.escape(_setting_str("show.category") or "Technology", quote=True)
    # Channel tags Apple Podcasts and Spotify require (#58). itunes:owner only with an e-mail:
    # the directories send their verification code there.
    explicit_val = "true" if _setting_str("show.explicit") == "1" else "false"
    owner_email = _setting_str("show.owner_email")
    owner_name = _setting_str("show.owner_name") or show_author
    owner_tag = ""
    if owner_email:
        owner_tag = (
            f"<itunes:owner><itunes:name>{htmllib.escape(owner_name, quote=True)}</itunes:name>"
            f"<itunes:email>{htmllib.escape(owner_email, quote=True)}</itunes:email></itunes:owner>"
        )
    show_language = _setting_str("show.language") or "en"
    # Build channel-level Podcast 2.0 identity tags
    self_url_clean = f"{base}{self_path}"
    guid_tag = f'<podcast:guid>{_compute_guid(self_url_clean, self_path)}</podcast:guid>'
    txt_tag = _podcast_txt_xml(show_num)
    locked_tag = _podcast_locked_xml(show_num)
    freq_tag = _podcast_update_frequency(rows, show_num, watchlist_id)

    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:podcast="https://podcastindex.org/namespace/1.0">'
        "<channel>"
        f"<title>{title}</title>"
        f"<link>{htmllib.escape(f'{base}/', quote=True)}</link>"
        f"<description>{show_desc}</description>"
        f"<language>{htmllib.escape(show_language, quote=True)}</language>"
        f"<itunes:author>{show_author}</itunes:author>"
        f"{owner_tag}"
        f"<itunes:explicit>{explicit_val}</itunes:explicit>"
        f"<itunes:category text=\"{show_category}\" />"
        f'{guid_tag}'
        f'{txt_tag}'
        f'{locked_tag}'
        f'{freq_tag}'
        f'<atom:link href="{htmllib.escape(self_url, quote=True)}" rel="self" type="application/rss+xml" />'
        f"<lastBuildDate>{now_rfc}</lastBuildDate>"
        "<generator>Vozonda</generator>"
        f'<itunes:image href="{base}/img/og-default.png" />'
        + funding_tag
        + items
        + "</channel></rss>"
    )
    # The build time changes every second; hash everything else so channel and
    # item edits still change the ETag. Only the lastBuildDate element is
    # dropped: replacing every occurrence of the time also blanked the pubDate
    # of an episode created in the same second, so the next request got a new
    # ETag (flaky test_show_feed_etag_is_stable, 2026-09-25).
    stable = rss.replace(f"<lastBuildDate>{now_rfc}</lastBuildDate>", "", 1)
    etag = f'"{hashlib.sha256(stable.encode()).hexdigest()}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(content=rss, media_type="application/rss+xml", headers={"ETag": etag})


@router.get("/feed/private-url", dependencies=[Depends(_require_write_auth)])
async def feed_private_url(request: Request) -> dict:
    """Full private feed URL for the settings screen (write-authed only)."""
    base = public_base(request)
    key = get_private_feed_key()
    return {
        "url": f"{base}/feed.xml?key={key}",
        "key": key,
        "public": _feed_is_public("default"),
    }


@router.get("/feed.xml", include_in_schema=False)
async def feed(request: Request, key: str | None = None) -> Response:
    """Master feed: without key, only episodes from public shows with RSS on.
    With valid key, all episodes from shows with RSS on."""
    has_valid_key = False
    if key:
        expected = get_private_feed_key()
        if hmac.compare_digest(str(key).encode(), expected.encode()):
            has_valid_key = True
    # Check default show RSS
    if resolve_show_rss("default") != "1":
        raise HTTPException(404, "not found")
    all_rows = _filter_rows_by_rss(_done_rows())
    if has_valid_key:
        # With key: all episodes from shows with RSS on
        rows = all_rows
    else:
        # Without key: only episodes from public shows with RSS on
        is_public = _public_checker()
        rows = [row for row in all_rows if is_public(row)]
    # For public feeds, return 200 even if empty; for private feeds without key, 404
    if not rows and not has_valid_key and not _feed_is_public("default"):
        raise HTTPException(404, "not found")
    return _render_feed(request, rows, self_path="/feed.xml", key=key, show_num="default")


@router.get("/{creator}/{show}/feed.xml", include_in_schema=False)
async def feed_hierarchical(creator: str, show: str, request: Request, key: str | None = None) -> Response:
    """Per-show feed (#231 / #232): the watchlist's episodes, else episodes whose
    show_name matches the slug exactly (hyphens read as spaces)."""
    show_num = _show_num_for_slug(show)
    watchlist = None
    if show_num is None:
        try:
            from ..watchlist import get_watchlist

            watchlist = get_watchlist(show)
            if not watchlist.get("id"):
                watchlist = None
        except Exception:
            watchlist = None  # no watchlist with this id: the show part names a show
    if watchlist:
        # a watchlist's feed belongs to the watchlist's show (the default show when it names none), so
        # private/public and RSS follow that show, as for every episode in it (_job_show_num)
        show_num = _watchlist_show_num(watchlist)
    if show_num is not None and resolve_show_rss(show_num) != "1":
        raise HTTPException(404, "not found")
    _require_feed_access(key, show_num)
    if watchlist:
        rows = _done_rows(" AND watchlist_id = ?", (watchlist["id"],))
    else:
        # exact, case-insensitive; the old LIKE let '%' in the URL match every show
        rows = _done_rows(" AND lower(show_name) IN (lower(?), lower(?))", (show, show.replace("-", " ")))
    return _render_feed(
        request, rows, key=key, show_num=show_num, watchlist_id=(watchlist or {}).get("id") or "",
        self_path=f"/{quote(creator, safe='')}/{quote(show, safe='')}/feed.xml",
        show_title=_setting_str("show.name") or show.replace("-", " "),
    )
