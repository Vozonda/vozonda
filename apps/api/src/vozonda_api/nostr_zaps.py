"""NIP-57 Zap helpers for vozonda.

Pure helpers for the NIP-57 flow:
  LNURL pay params -> kind 9734 zap request -> callback -> BOLT11 invoice -> kind 9735 receipt

All functions are stdlib-only and network-free (fetching is done by the caller).
See spec: https://github.com/nostr-protocol/nips/blob/master/57.md
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PRESET_AMOUNTS_SATS: list[int] = [21, 100, 500, 1000, 5000, 21000]
DEFAULT_RELAYS: list[str] = ["wss://relay.damus.io", "wss://nos.lol"]
MAX_COMMENT_LENGTH = 300
ZAP_REQUEST_KIND = 9734
ZAP_RECEIPT_KIND = 9735
# LNURL payRequest tag must be "payRequest"
LNURL_TAG = "payRequest"

_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_HEX128_RE = re.compile(r"^[0-9a-fA-F]{128}$")
_LUD16_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# BOLT11 is bech32: ln + (bc|tb|bcrt) + amount? + 1 + data. Minimal validation.
_BOLT11_RE = re.compile(r"^ln(bc|tb|bcrt)[0-9a-z]+$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# LN address helpers
# ---------------------------------------------------------------------------
def parse_lightning_address(address: str) -> tuple[str, str]:
    """Parse 'user@domain' into (user, domain). Raises ValueError on bad format."""
    addr = address.strip()
    if not _LUD16_RE.match(addr):
        raise ValueError(f"invalid lightning address: {addr!r}")
    user, domain = addr.split("@", 1)
    if not user or not domain or "." not in domain:
        raise ValueError(f"invalid lightning address: {addr!r}")
    return user, domain


def lightning_address_to_url(address: str) -> str:
    """Convert lightning address to LNURL-pay metadata URL.

    Example: alice@example.com -> https://example.com/.well-known/lnurlp/alice
    """
    user, domain = parse_lightning_address(address)
    # user is path-encoded, domain is lowercased
    user_enc = urllib.parse.quote(user, safe="")
    return f"https://{domain.lower()}/.well-known/lnurlp/{user_enc}"


def is_valid_lightning_address(address: str) -> bool:
    try:
        parse_lightning_address(address)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Amount helpers
# ---------------------------------------------------------------------------
def sats_to_msats(sats: int) -> int:
    if sats < 0:
        raise ValueError("sats must be >= 0")
    return sats * 1000


def msats_to_sats(msats: int) -> int:
    if msats < 0:
        raise ValueError("msats must be >= 0")
    return msats // 1000


def validate_zap_amount(
    amount_msats: int,
    min_msats: int,
    max_msats: int,
) -> int:
    """Validate amount is within [min, max] and is positive. Returns amount."""
    if not isinstance(amount_msats, int):
        raise TypeError("amount must be integer msats")
    if amount_msats <= 0:
        raise ValueError("amount must be > 0")
    if min_msats is not None and amount_msats < min_msats:
        raise ValueError(f"amount {amount_msats} below min {min_msats}")
    if max_msats is not None and amount_msats > max_msats:
        raise ValueError(f"amount {amount_msats} above max {max_msats}")
    return amount_msats


validate_amount_msats = validate_zap_amount


# ---------------------------------------------------------------------------
# LNURL pay params validation (NIP-57)
# ---------------------------------------------------------------------------
def validate_lnurl_pay_params(params: dict[str, Any]) -> tuple[bool, str]:
    """Validate LNURL payRequest params.

    Required fields per LUD-06 + NIP-57:
      callback, minSendable, maxSendable, tag == payRequest
      For NIP-57 zaps: allowsNostr == True and nostrPubkey present (hex 64)

    Returns (ok, reason).
    """
    if not isinstance(params, dict):
        return False, "params must be object"
    if params.get("tag") != LNURL_TAG:
        return False, f"tag must be {LNURL_TAG!r}"
    callback = params.get("callback")
    if not isinstance(callback, str) or not callback.startswith("https://"):
        return False, "callback must be https URL"
    try:
        min_s = int(params.get("minSendable", 0))
        max_s = int(params.get("maxSendable", 0))
    except Exception:
        return False, "minSendable/maxSendable must be integers"
    if min_s <= 0 or max_s <= 0 or min_s > max_s:
        return False, "invalid min/maxSendable range"
    # NIP-57 specific
    if not params.get("allowsNostr"):
        return False, "allowsNostr must be true for NIP-57"
    npub = params.get("nostrPubkey", "")
    if not isinstance(npub, str) or not _HEX64_RE.match(npub):
        return False, "nostrPubkey must be 64 hex"
    # commentAllowed is optional but if present must be int >=0
    ca = params.get("commentAllowed")
    if ca is not None:
        try:
            ca_i = int(ca)
            if ca_i < 0:
                return False, "commentAllowed must be >= 0"
        except Exception:
            return False, "commentAllowed must be integer"
    return True, "ok"


def build_lnurl_callback_url(
    callback: str,
    amount_msats: int,
    nostr_event_json: str,
    comment: str | None = None,
    lnurl: str | None = None,
) -> str:
    """Build the LNURL callback URL with query params.

    Appends amount (msats), nostr (url-encoded JSON), comment, lnurl.
    Uses proper url-encoding for the nostr JSON as required by NIP-57.
    """
    if not callback.startswith("https://"):
        raise ValueError("callback must be https")
    if amount_msats <= 0:
        raise ValueError("amount must be > 0")
    # comment length check
    if comment is not None and len(comment) > MAX_COMMENT_LENGTH:
        raise ValueError(f"comment too long (max {MAX_COMMENT_LENGTH})")
    parsed = urllib.parse.urlparse(callback)
    qs: dict[str, str] = dict(urllib.parse.parse_qsl(parsed.query))
    qs["amount"] = str(amount_msats)
    qs["nostr"] = nostr_event_json
    if comment:
        qs["comment"] = comment
    if lnurl:
        qs["lnurl"] = lnurl
    new_query = urllib.parse.urlencode(qs, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def encode_nostr_param(event_json: str) -> str:
    """URL-encode the nostr event JSON for the callback nostr param."""
    return urllib.parse.quote(event_json, safe="")


# ---------------------------------------------------------------------------
# Zap request (kind 9734)
# ---------------------------------------------------------------------------
def build_zap_request(
    sender_pubkey: str,
    recipient_pubkey: str,
    amount_msats: int,
    relays: list[str],
    content: str = "",
    lnurl: str | None = None,
    event_id: str | None = None,
    created_at: int | None = None,
) -> dict[str, Any]:
    """Build a NIP-57 zap request event template (kind 9734, unsigned).

    Returns dict with kind, content, tags, pubkey, created_at.
    Caller must sign via NIP-07 / Amber. Amount tag is in msats as string.
    """
    if not _HEX64_RE.match(sender_pubkey or ""):
        raise ValueError("invalid sender pubkey (64 hex required)")
    if not _HEX64_RE.match(recipient_pubkey or ""):
        raise ValueError("invalid recipient pubkey (64 hex required)")
    if amount_msats <= 0:
        raise ValueError("amount must be > 0")
    if content and len(content) > MAX_COMMENT_LENGTH:
        raise ValueError(f"content too long (max {MAX_COMMENT_LENGTH})")
    if not relays:
        relays = DEFAULT_RELAYS
    # validate relays are wss/https
    for r in relays:
        if not isinstance(r, str) or not r.startswith(("wss://", "ws://")):
            raise ValueError(f"invalid relay: {r!r}")

    import time as _time

    tags: list[list[str]] = [
        ["p", recipient_pubkey.lower()],
        ["amount", str(amount_msats)],
        ["relays", *relays],
    ]
    if lnurl:
        tags.append(["lnurl", lnurl])
    if event_id:
        if not _HEX64_RE.match(event_id):
            raise ValueError("event_id must be 64 hex")
        tags.append(["e", event_id.lower()])

    return {
        "kind": ZAP_REQUEST_KIND,
        "content": content or "",
        "tags": tags,
        "pubkey": sender_pubkey.lower(),
        "created_at": int(created_at) if created_at is not None else int(_time.time()),
    }


def validate_zap_request(
    event: dict[str, Any],
    expected_recipient: str | None = None,
    expected_amount_msats: int | None = None,
) -> tuple[bool, str]:
    """Validate structure of a kind 9734 zap request (unsigned ok)."""
    if not isinstance(event, dict):
        return False, "event must be object"
    if event.get("kind") != ZAP_REQUEST_KIND:
        return False, f"kind must be {ZAP_REQUEST_KIND}"
    pubkey = event.get("pubkey", "")
    if not isinstance(pubkey, str) or not _HEX64_RE.match(pubkey):
        return False, "invalid pubkey"
    content = event.get("content", "")
    if not isinstance(content, str):
        return False, "content must be string"
    if len(content) > MAX_COMMENT_LENGTH:
        return False, "content too long"
    tags = event.get("tags", [])
    if not isinstance(tags, list):
        return False, "tags must be array"
    # must have p tag
    p_tags = [t for t in tags if isinstance(t, list) and len(t) >= 2 and t[0] == "p"]
    if not p_tags:
        return False, "missing p tag"
    for t in p_tags:
        if not _HEX64_RE.match(t[1]):
            return False, "invalid p tag pubkey"
    if expected_recipient and not any(t[1].lower() == expected_recipient.lower() for t in p_tags):
        return False, "recipient mismatch"
    amt_tags = [t for t in tags if isinstance(t, list) and t[0] == "amount" and len(t) >= 2]
    if amt_tags:
        try:
            amt = int(amt_tags[0][1])
            if amt <= 0:
                return False, "amount must be > 0"
            if expected_amount_msats is not None and amt != expected_amount_msats:
                return False, "amount mismatch"
        except Exception:
            return False, "invalid amount tag"
    # relays tag must exist
    relays_tags = [t for t in tags if isinstance(t, list) and t[0] == "relays"]
    if not relays_tags:
        return False, "missing relays tag"
    # lnurl tag optional but if present must be string
    return True, "ok"


# ---------------------------------------------------------------------------
# BOLT11
# ---------------------------------------------------------------------------
def is_valid_bolt11(pr: str) -> bool:
    """Minimal BOLT11 check: starts with lnbc/lntb/lnbcrt and matches bech32 charset."""
    if not isinstance(pr, str):
        return False
    pr = pr.strip().lower()
    if not _BOLT11_RE.match(pr):
        return False
    # BOLT11 must contain separator '1' after prefix
    # pr is lnbc...1... – basic check
    # Find '1' after at least 4 chars (prefix)
    try:
        sep = pr.index("1", 4)
        if sep < 4:
            return False
        # data part after separator should be at least 10 chars
        return len(pr) - sep > 10
    except ValueError:
        return False


def validate_bolt11_amount(pr: str, expected_msats: int | None = None) -> tuple[bool, str]:
    """Validate BOLT11 and optionally check amount encoding.

    For now we only validate shape; amount decoding is optional because
    BOLT11 amount decoding is non-trivial. If expected_msats given, we try
    to extract amount from human readable part and compare, else skip.
    """
    if not is_valid_bolt11(pr):
        return False, "invalid bolt11"
    if expected_msats is None:
        return True, "ok"
    # Try to parse amount from prefix: lnbc<amount><multiplier>1...
    # multiplier: m=1e-3, u=1e-6, n=1e-9, p=1e-12 BTC
    m = re.match(r"^ln(bc|tb|bcrt)(\d+)([munp]?)1", pr, re.IGNORECASE)
    if not m:
        # no amount encoded (amountless invoice) -> cannot compare strictly, accept
        return True, "ok (amountless invoice)"
    amount_str = m.group(2)
    mult = m.group(3)
    try:
        amount = int(amount_str)
    except Exception:
        return False, "invalid bolt11 amount"
    # Simplify: compute sats via BTC * 1e8
    btc = amount * {"": 1, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}[mult]
    sats = round(btc * 100_000_000)
    msats = sats * 1000
    if msats != expected_msats:
        return False, f"bolt11 amount {msats} != expected {expected_msats}"
    return True, "ok"


def parse_lnurl_callback_response(data: dict[str, Any]) -> tuple[bool, str, str | None]:
    """Parse LNURL callback JSON.

    Expected success: {"pr": "<bolt11>", "verify": "...", "successAction": ...}
    Expected error: {"status": "ERROR", "reason": "..."}

    Returns (ok, reason, pr_or_none)
    """
    if not isinstance(data, dict):
        return False, "response must be object", None
    if data.get("status") == "ERROR":
        return False, str(data.get("reason", "lnurl error")), None
    pr = data.get("pr")
    if not isinstance(pr, str) or not pr.strip():
        return False, "missing pr (bolt11)", None
    if not is_valid_bolt11(pr):
        return False, "invalid bolt11 in pr", None
    return True, "ok", pr.strip()


# ---------------------------------------------------------------------------
# Zap receipt (kind 9735) helpers - for relay listening
# ---------------------------------------------------------------------------
def is_valid_zap_receipt(event: dict[str, Any]) -> tuple[bool, str]:
    """Validate kind 9735 zap receipt structure (minimal)."""
    if not isinstance(event, dict):
        return False, "event must be object"
    if event.get("kind") != ZAP_RECEIPT_KIND:
        return False, f"kind must be {ZAP_RECEIPT_KIND}"
    tags = event.get("tags", [])
    if not isinstance(tags, list):
        return False, "tags must be array"
    # receipt must contain bolt11 tag and description (zap request) tag?
    # Per NIP-57: receipt tags include p, bolt11, description (zap request json)
    bolt11 = [t for t in tags if isinstance(t, list) and t[0] == "bolt11" and len(t) >= 2]
    # Some relays use ["bolt11", pr] and ["description", zapRequestJson]
    if not bolt11:
        # alternative: some use lnurl callback to put pr in bolt11 tag as first after kind?
        return False, "missing bolt11 tag"
    if not is_valid_bolt11(bolt11[0][1]):
        return False, "invalid bolt11 in receipt"
    return True, "ok"


def extract_zap_amount_from_receipt(event: dict[str, Any]) -> int | None:
    """Try to extract amount sats from receipt's bolt11 tag or amount tag."""
    try:
        tags = event.get("tags", [])
        for t in tags:
            if isinstance(t, list) and t[0] == "amount" and len(t) >= 2:
                return int(t[1]) // 1000  # msats -> sats
        # fallback: parse bolt11 amount if present
        for t in tags:
            if isinstance(t, list) and t[0] == "bolt11" and len(t) >= 2:
                pr = t[1]
                # try amount parse - reuse validate helper but just return msats
                # we cannot reliably extract without full decoder, return None
                _ = pr
                return None
        return None
    except Exception:
        return None
