"""Nostr relay publisher (NIP-01 / NIP-42).

Sends signed Nostr events to one or more relays over WebSocket and returns
per-relay results.  A relay that challenges with NIP-42 AUTH or returns
['OK', id, false, ...] is tracked but never fails the publish of other
relays.

The ``websockets`` package is a required dependency for this module.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RelayResult:
    relay: str
    ok: bool | None  # True/False from relay, None on skip/error
    reason: str | None


async def _connect(url: str, **kwargs):
    """Open a websocket to a relay (patched in tests)."""
    import websockets

    return await websockets.connect(url, **kwargs)


async def _publish_to_relay(relay_url: str, event: dict, timeout: float) -> RelayResult:
    """Send one EVENT frame and wait for the OK that answers THIS event (NIP-01).

    Relays may send NOTICE frames or OKs for other events first; they are skipped, not
    taken as the answer. NIP-42: an AUTH challenge or an OK false starting with
    'auth-required:' means the relay wants a signed-in client; vozonda publishes with
    the podcast key only, so such a relay is skipped with that reason (no AUTH is sent)."""
    try:
        ws = await asyncio.wait_for(_connect(relay_url), timeout=timeout)
    except Exception as exc:
        logger.debug("relay connect failed for %s: %s", relay_url, exc)
        return RelayResult(relay=relay_url, ok=None, reason=f"connect: {exc}")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    auth_challenged = False
    notices: list[str] = []
    try:
        await asyncio.wait_for(ws.send(json.dumps(["EVENT", event], separators=(",", ":"))), timeout=timeout)
        while True:
            left = deadline - loop.time()
            if left <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=left)
            except TimeoutError:
                break
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(msg, list) or not msg:
                continue
            if msg[0] == "OK" and len(msg) >= 3 and msg[1] == event.get("id"):
                text = str(msg[3]) if len(msg) > 3 and msg[3] is not None else ""
                if msg[2] is True:
                    return RelayResult(relay=relay_url, ok=True, reason=None)
                if text.startswith("auth-required"):
                    return RelayResult(relay=relay_url, ok=None, reason=f"auth required, skipped ({text})")
                return RelayResult(relay=relay_url, ok=False, reason=text or "rejected")
            if msg[0] == "AUTH":
                auth_challenged = True
            elif msg[0] == "NOTICE" and len(msg) > 1:
                notices.append(str(msg[1])[:200])
        if auth_challenged:
            return RelayResult(relay=relay_url, ok=None, reason="auth required, skipped")
        reason = "timeout" + (f" (notice: {notices[-1]})" if notices else "")
        return RelayResult(relay=relay_url, ok=None, reason=reason)
    except Exception as exc:
        return RelayResult(relay=relay_url, ok=None, reason=str(exc))
    finally:
        try:
            await ws.close()
        except Exception:
            logger.debug("relay %s: close failed", relay_url, exc_info=True)


async def publish_async(event: dict, relays: list[str], timeout: float = 10.0) -> list[RelayResult]:
    """Publish a signed event to every relay concurrently; one relay failing never
    affects the others. Use this from async code (the API, the orchestrator)."""
    return list(await asyncio.gather(*(_publish_to_relay(r, event, timeout) for r in relays)))


def publish(event: dict, relays: list[str], timeout: float = 10.0) -> list[RelayResult]:
    """Synchronous wrapper for scripts and tests. Inside a running event loop (the API)
    asyncio.run cannot work; that is refused with a pointer to publish_async."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(publish_async(event, relays, timeout))
    raise RuntimeError("nostr_relay.publish called inside a running event loop; await publish_async instead")
