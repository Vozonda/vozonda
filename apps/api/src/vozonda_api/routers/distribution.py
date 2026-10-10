"""Distribution routes (VOZONDA-DISTRIBUTION).

Per-show reach: RSS feed, Nostr, both, or private.
"""

from urllib.parse import quote

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

from ..env import env
from ..settings_store import (
    all_settings,
    get_setting,
    resolve_show_nostr,
    resolve_show_rss,
    set_setting,
)

router = APIRouter()


async def _require_write_auth(authorization: str | None = Header(None)) -> None:
    from ..main import require_write_auth

    await require_write_auth(authorization)


@router.get("/distribution")
async def get_distribution(request: Request) -> dict:
    """Return distribution defaults, public URL reachability, and per-show reach."""
    # Defaults
    rss_default = get_setting("distribution.rss_default") or "1"
    nostr_publish_default = get_setting("nostr.publish_default") or "0"

    # Public URL and reachability
    public_url = env("PUBLIC_URL", "").strip()
    reachable: bool | None = None
    if public_url:
        health_url = public_url.rstrip("/") + "/health"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(health_url)
                reachable = resp.status_code == 200
        except Exception:
            reachable = False

    # Per-show reach: every numbered show (gaps included) plus the default show, whose
    # feed is the master feed. Feed URLs use the public address: podcast apps fetch them
    # from outside (VOZONDA_PUBLIC_URL), not from the address this request came in on.
    from ..settings_store import show_numbers

    base = (public_url or str(request.base_url)).rstrip("/")
    # A private feed (the default) answers only with its key: the links to copy must carry it, or a
    # podcast app gets 404. Only authorised callers reach this endpoint from outside (access.py).
    from ..settings_store import get_private_feed_key
    from .feeds import _feed_is_public

    key_q = "" if _feed_is_public() else f"?key={quote(get_private_feed_key(), safe='')}"
    shows = []
    all_settings_dict = all_settings()
    for i in show_numbers():
        name = all_settings_dict[f"show.{i}.name"]
        slug = f"s{i}"
        rss = resolve_show_rss(str(i))
        show_name_hyphen = quote(name.replace(" ", "-"), safe="")
        shows.append({
            "slug": slug,
            "name": name,
            "author": all_settings_dict.get(f"show.{i}.author") or "",
            "category": all_settings_dict.get(f"show.{i}.category") or "",
            "rss": rss,
            "nostr": resolve_show_nostr(str(i)),
            "feed_url": f"{base}/{slug}/{show_name_hyphen}/feed.xml{key_q}" if rss == "1" else None,
        })
    default_name = all_settings_dict.get("show.name") or ""
    if default_name:
        # the unnumbered default show: its episodes are in the master feed; no own key
        default_rss = resolve_show_rss("default")
        shows.append({"slug": "default", "name": default_name, "rss": default_rss, "nostr": "0",
                      "feed_url": f"{base}/feed.xml{key_q}" if default_rss == "1" else None, "fixed": True})

    # Directory help (static links)
    directory_help = {
        "apple_podcasts_connect": "https://podcastsconnect.apple.com/",
        "spotify_for_creators": "https://creators.spotify.com/",
        "podcast_index": "https://podcastindex.org/podcast/add",
    }

    return {
        "defaults": {
            "rss_default": rss_default,
            "nostr_publish_default": nostr_publish_default,
        },
        "public_url": public_url or None,
        "feed_private": bool(key_q),
        "reachable": reachable,
        "shows": shows,
        "directory_help": directory_help,
    }


@router.put("/shows/{slug}/rss")
async def put_show_rss(
    slug: str,
    body: dict,
    request: Request,
    authorization: str | None = Header(None),
) -> dict:
    """Enable or disable RSS feed for a show. Requires write auth."""
    await _require_write_auth(authorization)

    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(422, "enabled must be a boolean")
    value = "1" if enabled else "0"

    if slug == "default":
        # the undeletable master show: private (feed 404) or podcast apps
        set_setting("show.default.rss", value)
        base = (env("PUBLIC_URL", "").strip() or str(request.base_url)).rstrip("/")
        return {"slug": slug, "rss": value, "feed_url": f"{base}/feed.xml" if value == "1" else None}

    # Parse numeric index from slug (s1 -> 1, s2 -> 2, or bare number)
    show_num = slug.lstrip("s")
    try:
        idx = int(show_num)
    except (ValueError, TypeError):
        raise HTTPException(404, "show not found")

    # Verify the show exists
    all_settings_dict = all_settings()
    if f"show.{idx}.name" not in all_settings_dict or not all_settings_dict.get(f"show.{idx}.name"):
        raise HTTPException(404, "show not found")

    try:
        set_setting(f"show.{idx}.rss", value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    base = str(request.base_url).rstrip("/")
    all_settings_dict = all_settings()
    name = all_settings_dict.get(f"show.{idx}.name", "")
    show_name_hyphen = quote(name.replace(" ", "-"), safe="")
    return {
        "slug": slug,
        "rss": value,
        "feed_url": f"{base}/{slug}/{show_name_hyphen}/feed.xml" if value == "1" else None,
    }