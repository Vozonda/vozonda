import email.utils
import hashlib
import hmac
import html as htmllib
import json
import sqlite3
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from ..env import env
from ..settings_store import get_private_feed_key, get_setting, resolve_show_rss

router = APIRouter()

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


def _feed_is_public() -> bool:
    """Private unless the owner opted in: an unset value is private (the UI
    default says so too), and a settings error fails closed."""
    try:
        return str(get_setting("feed.public") or "0").strip() == "1"
    except Exception:
        return False


def _require_feed_access(key: str | None) -> None:
    """Feeds are private by default: a wrong or missing key is a 404, never
    a 401, so the feed's existence is not revealed."""
    if _feed_is_public():
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

    # Fall back to name-based lookup
    name = slug.replace("-", " ").strip().casefold()
    if not name:
        return None
    i = 1
    while all_settings_dict.get(f"show.{i}.name"):
        if str(all_settings_dict[f"show.{i}.name"]).strip().casefold() == name:
            return str(i)
        i += 1
    return None


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


def _feed_item(row: dict, base: str, now_rfc: str, recipients: list[tuple[str, str, int]], key_q: str = "") -> str:
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
    # A private feed's media links carry the feed key (key_q), or podcast apps outside the host get 404
    # (GHSA-crq5-73gf-fv2h). The guid stays without it, so a key change does not duplicate episodes.
    audio_url = htmllib.escape(f"{base}/audio/{jid}.mp3{key_q}", quote=True)
    guid = htmllib.escape(f"{base}/e/{jid}", quote=True)
    page_url = htmllib.escape(f"{base}/e/{jid}{key_q}", quote=True)
    meta = _master_meta(row)
    dur_ms = row.get("duration_ms")
    if dur_ms is None and isinstance(meta.get("duration_ms"), (int, float)):
        dur_ms = meta["duration_ms"]
    dur_tag = f"<itunes:duration>{_format_duration(int(dur_ms))}</itunes:duration>" if dur_ms is not None else ""
    audio_bytes = (meta.get("audio") or {}).get("bytes")
    length = str(audio_bytes) if isinstance(audio_bytes, int) else "0"
    expl_tag = "<itunes:explicit>yes</itunes:explicit>" if row.get("explicit") else ""
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
        f"{dur_tag}</item>"
    )


def _render_feed(request: Request, rows: list, *, self_path: str, key: str | None,
                 show_title: str | None = None) -> Response:
    """One RSS builder for the main feed and the per-show feeds."""
    base = str(request.base_url).rstrip("/")
    creator_addr = _setting_str("feed.creator.address")
    recipients: list[tuple[str, str, int]] = []
    if creator_addr:
        for name, default in (("creator", 70), ("source", 20), ("app", 10)):
            addr = _setting_str(f"feed.{name}.address")
            split = _split_setting(f"feed.{name}.split", default)
            if addr and split > 0:
                recipients.append((name, addr, split))
    now_rfc = _now_rfc()
    key_q = f"?key={quote(key)}" if key and not _feed_is_public() else ""
    items = "".join(_feed_item(dict(r), base, now_rfc, recipients, key_q) for r in rows)

    # A private feed's self link must carry the key, or apps that refresh
    # through atom:link lose access.
    self_url = f"{base}{self_path}" + (f"?key={quote(key)}" if key and not _feed_is_public() else "")
    funding_tag = (
        f'<podcast:funding url="lightning:{htmllib.escape(creator_addr, quote=True)}">Support the show</podcast:funding>'
        if creator_addr
        else ""
    )
    title = htmllib.escape(show_title or _setting_str("show.name") or "Vozonda", quote=True)
    show_desc = htmllib.escape(
        _setting_str("show.description") or "Vozonda: Sovereign audio overviews. Your voices, your feeds. Open source & private.",
        quote=True,
    )
    show_author = htmllib.escape(_setting_str("show.author") or creator_addr or "Vozonda", quote=True)
    show_category = htmllib.escape(_setting_str("show.category") or "Technology", quote=True)
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:podcast="https://podcastindex.org/namespace/1.0">'
        "<channel>"
        f"<title>{title}</title>"
        f"<link>{htmllib.escape(f'{base}/', quote=True)}</link>"
        f"<description>{show_desc}</description>"
        "<language>en</language>"
        f"<itunes:author>{show_author}</itunes:author>"
        f"<itunes:category text=\"{show_category}\" />"
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
    etag = f'"{hashlib.md5(stable.encode()).hexdigest()}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(content=rss, media_type="application/rss+xml", headers={"ETag": etag})


@router.get("/feed/private-url", dependencies=[Depends(_require_write_auth)])
async def feed_private_url(request: Request) -> dict:
    """Full private feed URL for the settings screen (write-authed only)."""
    base = str(request.base_url).rstrip("/")
    key = get_private_feed_key()
    return {
        "url": f"{base}/feed.xml?key={key}",
        "key": key,
        "public": _feed_is_public(),
    }


@router.get("/feed.xml", include_in_schema=False)
async def feed(request: Request, key: str | None = None) -> Response:
    _require_feed_access(key)
    if resolve_show_rss("default") != "1":
        raise HTTPException(404, "not found")
    rows = _filter_rows_by_rss(_done_rows())
    return _render_feed(request, rows, self_path="/feed.xml", key=key)


@router.get("/{creator}/{show}/feed.xml", include_in_schema=False)
async def feed_hierarchical(creator: str, show: str, request: Request, key: str | None = None) -> Response:
    """Per-show feed (#231 / #232): the watchlist's episodes, else episodes whose
    show_name matches the slug exactly (hyphens read as spaces)."""
    _require_feed_access(key)
    # Check if this show has RSS enabled
    show_num = _show_num_for_slug(show)
    if show_num is not None and resolve_show_rss(show_num) != "1":
        # Show exists but RSS is disabled - return 404
        raise HTTPException(404, "not found")
    try:
        from ..watchlist import get_watchlist

        watchlist_id = get_watchlist(show)["id"]
    except Exception:
        watchlist_id = None
    if watchlist_id:
        from ..watchlist import get_watchlist as _get_wl

        try:
            wl_show = str((_get_wl(watchlist_id).get("show_slug") or "").strip())
        except Exception:
            wl_show = ""
        if wl_show:
            wl_num = "default" if wl_show.lower() == "default" else (wl_show[1:] if wl_show[:1].lower() == "s" else wl_show)
            if (wl_num.isdigit() or wl_num == "default") and resolve_show_rss(wl_num) != "1":
                raise HTTPException(404, "not found")
        rows = _done_rows(" AND watchlist_id = ?", (watchlist_id,))
    else:
        # exact, case-insensitive; the old LIKE let '%' in the URL match every show
        rows = _done_rows(" AND lower(show_name) IN (lower(?), lower(?))", (show, show.replace("-", " ")))
    return _render_feed(
        request, rows, key=key,
        self_path=f"/{quote(creator, safe='')}/{quote(show, safe='')}/feed.xml",
        show_title=_setting_str("show.name") or show.replace("-", " "),
    )
