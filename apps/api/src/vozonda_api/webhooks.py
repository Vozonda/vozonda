"""Webhook delivery for agent job completion notifications.

Delivers a JSON completion event to job['callback_url'] with SSRF protection,
optional HMAC-SHA256 signature, and capped exponential backoff retries.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any

from . import __version__
from .env import env
from .fetcher import FetchError, guarded_client

logger = logging.getLogger("vozonda_api.webhooks")

WEBHOOK_TIMEOUT = 10.0
MAX_ATTEMPTS = 3
RETRY_DELAYS = [1.0, 4.0]


async def deliver(job: dict[str, Any]) -> bool:
    """Deliver a job completion event to the job's callback_url.

    POSTs {"id", "state", "title", "audio_url", "duration_ms", "error"} as JSON.
    SSRF-guarded via guarded_client so private/loopback targets are refused.
    If VOZONDA_WEBHOOK_SECRET is set, adds header X-Vozonda-Signature: sha256=<hex hmac>.
    Retries up to 3 attempts with 1s/4s backoff; logs and gives up afterwards;
    never raises into the caller.
    Returns True on successful delivery (2xx), False otherwise.
    """
    try:
        callback_url = (job.get("callback_url") or "").strip()
        if not callback_url:
            return False

        job_id = str(job.get("id") or "")
        state = str(job.get("state") or "")
        audio_url = job.get("audio_url")
        if audio_url is None and state == "done":
            audio_url = f"/audio/{job_id}.mp3"

        # VOZONDA-AGENT-3: absolute audio_url and feed_url; the configured address first (address.public,
        # then VOZONDA_PUBLIC_URL), else the address the job was created on
        from .public_address import configured_base

        base = configured_base() or (job.get("public_base") or "").rstrip("/")
        if base:
            audio_url = f"{base}/audio/{job_id}.mp3" if state == "done" else audio_url
            feed_url = f"{base}/feed.xml"
        else:
            feed_url = None

        payload = {
            "id": job_id,
            "state": state,
            "title": job.get("title") or "",
            "audio_url": audio_url,
            "feed_url": feed_url,
            "duration_ms": job.get("duration_ms"),
            "error": job.get("error"),
        }

        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": f"vozonda/{__version__} (webhook-delivery)",
        }

        secret = env("WEBHOOK_SECRET")
        if secret:
            digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            headers["X-Vozonda-Signature"] = f"sha256={digest}"
            headers["X-Vozonda-Signature"] = f"sha256={digest}"

        for attempt in range(MAX_ATTEMPTS):
            try:
                async with guarded_client(timeout=WEBHOOK_TIMEOUT) as client:
                    resp = await client.post(callback_url, content=raw_body, headers=headers)
                    if resp.is_success:
                        logger.info("Webhook delivered successfully for job %s to %s", job_id, callback_url)
                        return True
                    logger.warning(
                        "Webhook delivery attempt %d/%d for job %s returned HTTP %d",
                        attempt + 1,
                        MAX_ATTEMPTS,
                        job_id,
                        resp.status_code,
                    )
            except FetchError as exc:
                # SSRF guard refused target (private/loopback or DNS resolution failure)
                logger.warning(
                    "Webhook delivery refused by SSRF guard for job %s to %s: %s",
                    job_id,
                    callback_url,
                    exc,
                )
                return False
            except Exception as exc:
                logger.warning(
                    "Webhook delivery attempt %d/%d failed for job %s: %s",
                    attempt + 1,
                    MAX_ATTEMPTS,
                    job_id,
                    exc,
                )

            if attempt < len(RETRY_DELAYS):
                await asyncio.sleep(RETRY_DELAYS[attempt])

        logger.warning("Webhook delivery for job %s failed after %d attempts", job_id, MAX_ATTEMPTS)
        return False
    except Exception as exc:
        logger.warning("Unexpected error during webhook delivery: %s", exc)
        return False
