"""Tell the operator when a newer Vozonda release exists, and how to install it.

One GET to the GitHub releases API (api.github.com/repos/Vozonda/vozonda/releases/latest) at most every
six hours, only while the web UI asks for it, and never when the setting update.check is "0". GitHub sees the
install's IP address and nothing else; no data about the install is sent. A failed check stays silent.

Updating stays a command the operator runs (git pull && docker compose up -d --build): a button that updates
the install itself would need control over Docker, which means root on the host.
"""
from __future__ import annotations

import re
import time

import httpx

from .settings_store import get_setting
from .version import BASE_VERSION

RELEASES_API = "https://api.github.com/repos/Vozonda/vozonda/releases/latest"
TTL = 6 * 3600
_cache: dict = {"at": 0.0, "release": None}


def _parse(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-", 1)[0])
    return tuple(int(n) for n in nums[:3]) or (0,)


def enabled() -> bool:
    return str(get_setting("update.check") or "1").strip() != "0"


async def _latest() -> dict | None:
    now = time.time()
    if now - _cache["at"] < TTL:
        return _cache["release"]
    release = None
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            r = await client.get(RELEASES_API, headers={"Accept": "application/vnd.github+json",
                                                        "User-Agent": "vozonda-update-check"})
        if r.status_code == 200:
            data = r.json()
            release = {"tag": str(data.get("tag_name") or ""), "url": str(data.get("html_url") or ""),
                       "body": str(data.get("body") or "")}
    except (httpx.HTTPError, ValueError):
        release = None
    _cache.update(at=now, release=release)
    return release


async def check() -> dict:
    """{"current", "enabled", "available", "latest", "security", "url", "command"}."""
    out = {"current": BASE_VERSION, "enabled": enabled(), "available": False}
    if not out["enabled"]:
        return out
    rel = await _latest()
    if not rel or not rel["tag"]:
        return out
    latest = rel["tag"].lstrip("v")
    if _parse(latest) > _parse(BASE_VERSION):
        out.update(available=True, latest=latest, url=rel["url"],
                   # the release notes come from the CHANGELOG section, which has "### Security" for fixes
                   security="### Security" in rel["body"],
                   command="git pull && docker compose up -d --build")
    return out
