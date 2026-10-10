"""Distribution routes (VOZONDA-DISTRIBUTION).

Per-show reach: RSS feed, Nostr, both, or private.
"""

import secrets
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from ..env import env
from ..public_address import address_info, public_base
from ..settings_store import (
    all_settings,
    get_private_feed_key,
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

    # The address other devices use, what kind it is, and whether it answers. The check is async and
    # only for an address that was set: the request's own address answers by definition.
    addr_info = address_info(request)
    addr_info["answers"] = None
    if addr_info["source"] != "none" and addr_info["scope"] != "this-computer":
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(addr_info["url"] + "/health")
            addr_info["answers"] = resp.status_code == 200
        except Exception:
            addr_info["answers"] = False

    # Per-show reach: every numbered show (gaps included) plus the default show, whose
    # feed is the master feed. Feed URLs use the public address: podcast apps fetch them
    # from outside, not from the address this request came in on.
    from ..settings_store import show_numbers

    base = public_base(request)
    # Feed URLs carry ?key= only for private shows (feeds._feed_is_public decides, per show)
    from .feeds import _feed_is_public

    shows = []
    all_settings_dict = all_settings()
    for i in show_numbers():
        name = all_settings_dict[f"show.{i}.name"]
        slug = f"s{i}"
        rss = resolve_show_rss(str(i))
        pub = "1" if _feed_is_public(str(i)) else "0"
        show_name_hyphen = quote(name.replace(" ", "-"), safe="")
        feed_url = f"{base}/{slug}/{show_name_hyphen}/feed.xml" if rss == "1" else None
        if feed_url and pub != "1":
            # Private show: add feed key
            feed_url += f"?key={quote(get_private_feed_key(), safe='')}"
        shows.append({
            "slug": slug,
            "name": name,
            "author": all_settings_dict.get(f"show.{i}.author") or "",
            "category": all_settings_dict.get(f"show.{i}.category") or "",
            "rss": rss,
            "public": pub,
            "nostr": resolve_show_nostr(str(i)),
            "feed_url": feed_url,
        })
    default_name = all_settings_dict.get("show.name") or ""
    if default_name:
        # the unnumbered default show: its episodes are in the master feed
        default_rss = resolve_show_rss("default")
        default_pub = "1" if _feed_is_public("default") else "0"
        feed_url = f"{base}/feed.xml" if default_rss == "1" else None
        if feed_url and default_pub != "1":
            feed_url += f"?key={quote(get_private_feed_key(), safe='')}"
        shows.append({"slug": "default", "name": default_name, "rss": default_rss, "public": default_pub, "nostr": "0",
                      "feed_url": feed_url, "fixed": True})

    # Directory help (static links)
    directory_help = {
        "apple_podcasts_connect": "https://podcastsconnect.apple.com/",
        "spotify_for_creators": "https://creators.spotify.com/",
        "podcast_index": "https://podcastindex.org/podcast/add",
    }

    # Legacy fields for backward compatibility
    legacy_public_url = addr_info["url"] if addr_info["source"] != "none" else None
    legacy_reachable = addr_info["answers"]

    return {
        "defaults": {
            "rss_default": rss_default,
            "nostr_publish_default": nostr_publish_default,
        },
        "address": addr_info,
        "public_url": legacy_public_url,
        # some show's feed needs the key: its link to copy carries it (settings note)
        "feed_private": any(s["feed_url"] and s.get("public") != "1" for s in shows),
        "reachable": legacy_reachable,
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


@router.put("/shows/{slug}/public")
async def put_show_public(
    slug: str,
    body: dict,
    request: Request,
    authorization: str | None = Header(None),
) -> dict:
    """Enable or disable public access for a show's feed. Requires write auth."""
    await _require_write_auth(authorization)

    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(422, "enabled must be a boolean")
    value = "1" if enabled else "0"

    if slug == "default":
        set_setting("show.default.public", value)
        return {"slug": slug, "public": value}

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
        set_setting(f"show.{idx}.public", value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    return {"slug": slug, "public": value}


@router.post("/feed/key/rotate", dependencies=[Depends(_require_write_auth)])
async def rotate_feed_key() -> dict:
    """Generate a new random feed key and store it. Old key links become invalid (404)."""
    new_key = secrets.token_urlsafe(24)
    set_setting("feed.private_key", new_key)
    return {"key": new_key}
