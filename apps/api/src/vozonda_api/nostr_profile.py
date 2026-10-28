"""Nostr profile (kind 0) lookup helpers for vozonda."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from .nostr_auth import _bech32_decode, _convert_bits, compute_event_id, normalize_pubkey, schnorr_verify
from .nostr_relay import _connect

logger = logging.getLogger(__name__)

PROFILE_TIMEOUT_S = 5.0


def decode_nip19_entity(entity: str) -> tuple[str, dict[str, Any]]:
    """Decode an npub, nprofile, note, or nevent bech32 string."""
    hrp, data = _bech32_decode(entity.strip())
    if hrp is None or data is None:
        raise ValueError(f"invalid bech32: {entity}")
    decoded = _convert_bits(data, 5, 8, False)
    if decoded is None:
        raise ValueError(f"invalid payload: {entity}")
    raw_bytes = bytes(decoded)
    if hrp == "npub":
        return "npub", {"pubkey": raw_bytes.hex()}
    if hrp in ("nprofile", "nevent", "naddr"):
        pos = 0
        tlv: dict[str, Any] = {}
        while pos + 2 <= len(raw_bytes):
            t = raw_bytes[pos]
            l = raw_bytes[pos + 1]
            pos += 2
            if pos + l > len(raw_bytes):
                break
            v = raw_bytes[pos : pos + l]
            pos += l
            if t == 0:
                if hrp == "nprofile":
                    tlv["pubkey"] = v.hex()
                elif hrp == "nevent":
                    tlv["id"] = v.hex()
            elif t == 2 and hrp == "nevent":
                tlv["pubkey"] = v.hex()
        return hrp, tlv
    return hrp, {}


def extract_nostr_pubkey(url_or_entity: str) -> str | None:
    """Extract a 64-char hex pubkey from a Nostr URI, gateway URL, npub, or nprofile."""
    s = url_or_entity.strip()
    m = re.search(r"\b(npub1[a-z0-9]+|nprofile1[a-z0-9]+|nevent1[a-z0-9]+)\b", s, re.IGNORECASE)
    if m:
        try:
            _, data = decode_nip19_entity(m.group(1))
            if "pubkey" in data:
                return data["pubkey"]
        except Exception:
            logger.debug("Failed to decode NIP-19 entity %s", m.group(1), exc_info=True)
    if s.lower().startswith("nostr:"):
        candidate = s[6:].strip()
        if re.fullmatch(r"[0-9a-fA-F]{64}", candidate):
            return candidate.lower()
    try:
        return normalize_pubkey(s)
    # silent: not a standard pubkey
    except Exception:
        pass
    return None


def _profile_relays() -> list[str]:
    """The operator's relays (setting nostr.relays), else the zap defaults."""
    from .nostr_orchestrator import _load_relay_urls
    from .nostr_zaps import DEFAULT_RELAYS

    return _load_relay_urls() or list(DEFAULT_RELAYS)


def _signed_by(event: Any, pubkey: str) -> bool:
    """A kind 0 event counts only if pubkey signed it: a relay could otherwise hand out
    any lud16 and the source's sats would go to whoever wrote it."""
    try:
        if not isinstance(event, dict) or event.get("kind") != 0 or str(event.get("pubkey", "")).lower() != pubkey:
            return False
        eid = compute_event_id(pubkey, int(event["created_at"]), 0, list(event.get("tags") or []),
                               str(event.get("content", "")))
        if eid != str(event.get("id", "")).lower():
            return False
        return schnorr_verify(bytes.fromhex(eid), bytes.fromhex(pubkey), bytes.fromhex(str(event["sig"])))
    except (KeyError, TypeError, ValueError):
        return False


async def lookup_profile(pubkey_or_identifier: str) -> dict[str, Any] | None:
    """The newest signed kind 0 profile of a Nostr author, or None.

    Without a pubkey in the input there is no relay call at all: a source URL must
    never reach a public relay (it would tell the relay what the user reads)."""
    pubkey = extract_nostr_pubkey(pubkey_or_identifier)
    if not pubkey:
        return None
    req = json.dumps(["REQ", "sub_profile", {"kinds": [0], "authors": [pubkey], "limit": 1}])
    best: dict[str, Any] | None = None
    for relay in _profile_relays():
        try:
            ws = await asyncio.wait_for(_connect(relay), timeout=PROFILE_TIMEOUT_S)
            async with ws:
                await ws.send(req)
                while True:
                    data = json.loads(await asyncio.wait_for(ws.recv(), timeout=PROFILE_TIMEOUT_S))
                    if not isinstance(data, list) or len(data) < 2:
                        continue
                    if data[0] == "EOSE":
                        break
                    if data[0] != "EVENT" or len(data) < 3 or data[1] != "sub_profile":
                        continue
                    ev = data[2] if isinstance(data[2], dict) else {}
                    newer = best is None or int(ev.get("created_at", 0)) > int(best["created_at"])
                    if newer and _signed_by(ev, pubkey):
                        best = ev
        except Exception:
            logger.debug("profile lookup failed on %s", relay, exc_info=True)
            continue
        if best is not None:
            break
    if best is None:
        return None
    try:
        profile = json.loads(best["content"])
    except ValueError:
        logger.debug("profile content of %s is not JSON", pubkey)
        return None
    return profile if isinstance(profile, dict) else None
