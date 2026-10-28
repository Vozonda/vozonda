"""Podping integration (VOZONDA-PODPING).

Announces new episodes on public RSS feeds to podcast apps via
podping.cloud.  Never raises, never changes job state.
"""

import asyncio
import json
import logging
import time
from urllib.parse import quote

import httpx

from . import __version__
from .jobs import JobStore
from .public_address import configured_base
from .routers.feeds import _job_show_num, _public_checker
from .settings_store import get_setting, set_setting

logger = logging.getLogger(__name__)

# In-memory debounce cache: {url: last_ping_timestamp}
_DEBOUNCE_CACHE: dict[str, float] = {}
_DEBOUNCE_SECONDS = 60.0


def _build_feed_url(base: str, job: dict) -> str | None:
    """The public feed URL of a job's show, built as routers/distribution.py builds the
    feed_url the settings screen shows: {base}/feed.xml for the default show,
    {base}/s<n>/<show name, spaces as hyphens, quoted>/feed.xml for a numbered one."""
    show_num = _job_show_num(job)
    if show_num == "default":
        return f"{base}/feed.xml"
    name = get_setting(f"show.{show_num}.name") or ""
    if not name:
        return None
    return f"{base}/s{show_num}/{quote(name.replace(' ', '-'), safe='')}/feed.xml"


async def ping_job(job_id: str) -> None:
    """Ping Podping.cloud for a job's feed URL if it qualifies.

    Never raises, never changes job state, logs at info/warning.
    """
    try:
        # 1. podping.enabled must be '1'
        if get_setting("podping.enabled") != "1":
            return

        # 2. token must be non-empty
        token = get_setting("podping.token")
        if not token:
            return

        # 3. privacy.mode must not be 'confidential' (missing key is fine)
        if get_setting("privacy.mode") == "confidential":
            return

        # 4. job must exist and be public with RSS on
        store = JobStore()
        job = store.get(job_id)
        if not job:
            logger.warning("podping: job %s not found", job_id)
            return

        if not _public_checker()(job):
            return

        # 5. public address must be non-empty and not loopback/private
        base = configured_base()
        if not base:
            logger.warning("podping: no public address configured")
            return

        from .public_address import _extract_host, _is_loopback, _is_private_network

        host = _extract_host(base)
        if not host or _is_loopback(host) or _is_private_network(host):
            logger.warning("podping: public address is loopback or private")
            return

        # 6. Build feed URL and sanity-check it never carries key=
        feed_url = _build_feed_url(base, job)
        if not feed_url:
            logger.warning("podping: show of job %s has no name; nothing to announce", job_id)
            return
        if "key=" in feed_url:  # a private feed's key must never reach podping
            logger.warning("podping: refused a feed URL that carries a key")
            return

        # 7. Debounce: skip if pinged within 60 s
        now = time.time()
        last_ping = _DEBOUNCE_CACHE.get(feed_url)
        if last_ping and now - last_ping < _DEBOUNCE_SECONDS:
            logger.info("podping: debounced %s", feed_url)
            return

        # 8. Send the ping (one retry on 5xx / connection error)
        status_code = None
        exc_msg = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    params = {
                        "url": feed_url,
                        "reason": "update",
                        "medium": "podcast",
                    }
                    headers = {
                        "Authorization": token,
                        "User-Agent": f"Vozonda/{__version__}",
                    }
                    resp = await client.get(
                        "https://podping.cloud/",
                        params=params,
                        headers=headers,
                    )
                status_code = resp.status_code
                if 200 <= status_code < 300:
                    logger.info("podping: success for %s", feed_url)
                    _DEBOUNCE_CACHE[feed_url] = now
                    break
                elif 500 <= status_code < 600:
                    if attempt == 1:
                        logger.warning(
                            "podping: failed for %s (attempt %d): %d",
                            feed_url,
                            attempt + 1,
                            status_code,
                        )
                    else:
                        await asyncio.sleep(1.0)
                else:
                    # 4xx and others: do not retry, record and give up
                    logger.warning(
                        "podping: failed for %s: %d", feed_url, status_code
                    )
                    break
            except httpx.HTTPError as exc:
                exc_msg = str(exc)
                if attempt == 1:
                    logger.warning(
                        "podping: failed for %s (attempt %d): %s",
                        feed_url,
                        attempt + 1,
                        exc_msg,
                    )
                else:
                    await asyncio.sleep(1.0)

        # 9. Record last result (without the token)
        result = {
            "url": feed_url,
            "at": int(now),
            "status": status_code if status_code else f"error: {exc_msg}" if exc_msg else "error",
        }
        try:
            set_setting("podping.last", json.dumps(result))
        except Exception:
            logger.warning("podping: failed to record last result", exc_info=True)

    except Exception:
        logger.exception("podping: unexpected error for job %s", job_id)
