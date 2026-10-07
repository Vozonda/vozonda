"""Nostr Multi-Signer auth helpers: NIP-19 bech32 + NIP-07 / NIP-46 ready.

Never stores nsec. Only npub/hex pubkey plus ephemeral challenge nonces.
Pure stdlib: bech32 BIP173 reference implementation inlined, no extra deps.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import time

logger = logging.getLogger(__name__)


def _add_column(c, table: str, column_ddl: str) -> None:
    """ALTER TABLE ADD COLUMN that skips existing columns.

    Only a duplicate-column OperationalError is swallowed; any other
    error is logged and re-raised so a broken schema fails at startup.
    """
    import sqlite3

    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column_ddl}")
    except sqlite3.OperationalError as exc:
        if "duplicate column" in str(exc).lower():
            return
        logger.exception("nostr migration failed adding %s to %s", column_ddl, table)
        raise

# ---------------------------------------------------------------------------
# bech32 (BIP173) - reference impl, trimmed for vozonda needs
# ---------------------------------------------------------------------------
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_GEN = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]


def _bech32_polymod(values: list[int]) -> int:
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= _BECH32_GEN[i] if ((top >> i) & 1) else 0
    return chk


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_verify_checksum(hrp: str, data: list[int]) -> bool:
    return _bech32_polymod(_bech32_hrp_expand(hrp) + data) == 1


def _bech32_create_checksum(hrp: str, data: list[int]) -> list[int]:
    values = _bech32_hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def _convert_bits(data: list[int], from_bits: int, to_bits: int, pad: bool = True) -> list[int] | None:
    acc = 0
    bits = 0
    ret: list[int] = []
    maxv = (1 << to_bits) - 1
    max_acc = (1 << (from_bits + to_bits - 1)) - 1
    for value in data:
        if value < 0 or (value >> from_bits):
            return None
        acc = ((acc << from_bits) | value) & max_acc
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (to_bits - bits)) & maxv)
    elif bits >= from_bits or ((acc << (to_bits - bits)) & maxv):
        return None
    return ret


def _bech32_encode(hrp: str, data: list[int]) -> str:
    combined = data + _bech32_create_checksum(hrp, data)
    return hrp + "1" + "".join(_BECH32_CHARSET[d] for d in combined)


def _bech32_decode(bech: str) -> tuple[str | None, list[int] | None]:
    if any(ord(x) < 33 or ord(x) > 126 for x in bech):
        return None, None
    if bech.lower() != bech and bech.upper() != bech:
        return None, None
    bech = bech.lower()
    pos = bech.rfind("1")
    if pos < 1 or pos + 7 > len(bech) or len(bech) > 90:
        return None, None
    if not all(x in _BECH32_CHARSET for x in bech[pos + 1:]):
        return None, None
    hrp = bech[:pos]
    data = [_BECH32_CHARSET.find(x) for x in bech[pos + 1:]]
    if not _bech32_verify_checksum(hrp, data):
        return None, None
    return hrp, data[:-6]


# ---------------------------------------------------------------------------
# NIP-19 helpers
# ---------------------------------------------------------------------------
_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def is_valid_hex_pubkey(s: str) -> bool:
    return bool(_HEX_RE.match(s.strip()))


def is_valid_npub(s: str) -> bool:
    s = s.strip()
    hrp, data = _bech32_decode(s)
    if hrp != "npub" or data is None:
        return False
    decoded = _convert_bits(data, 5, 8, False)
    return decoded is not None and len(decoded) == 32


def is_valid_nsec(s: str) -> bool:
    s = s.strip()
    hrp, data = _bech32_decode(s)
    if hrp != "nsec" or data is None:
        return False
    decoded = _convert_bits(data, 5, 8, False)
    return decoded is not None and len(decoded) == 32


def npub_to_hex(npub: str) -> str:
    npub = npub.strip()
    hrp, data = _bech32_decode(npub)
    if hrp != "npub" or data is None:
        raise ValueError(f"invalid npub: {npub!r}")
    decoded = _convert_bits(data, 5, 8, False)
    if decoded is None or len(decoded) != 32:
        raise ValueError(f"invalid npub payload: {npub!r}")
    return bytes(decoded).hex()


def hex_to_npub(hex_pubkey: str) -> str:
    hex_pubkey = hex_pubkey.strip().lower()
    if not is_valid_hex_pubkey(hex_pubkey):
        raise ValueError(f"invalid hex pubkey: {hex_pubkey!r}")
    data = list(bytes.fromhex(hex_pubkey))
    converted = _convert_bits(data, 8, 5, True)
    assert converted is not None
    return _bech32_encode("npub", converted)


def normalize_pubkey(inp: str) -> str:
    """Accept hex or npub, return lowercase hex. Raises ValueError on invalid."""
    inp = inp.strip()
    if is_valid_hex_pubkey(inp):
        return inp.lower()
    if is_valid_npub(inp):
        return npub_to_hex(inp)
    raise ValueError(f"invalid pubkey (expected hex 64 or npub): {inp!r}")


def validate_npub(npub: str) -> bool:
    return is_valid_npub(npub)


# ---------------------------------------------------------------------------
# Challenge store (ephemeral, in-memory, single-process)
# ---------------------------------------------------------------------------
_CHALLENGES: dict[str, float] = {}
_CHALLENGE_TTL = 300  # seconds


def create_challenge() -> tuple[str, float]:
    """Create a random 32-byte hex challenge. Returns (challenge, expires_at)."""
    # purge expired
    now = time.time()
    for k, exp in list(_CHALLENGES.items()):
        if exp < now:
            _CHALLENGES.pop(k, None)
    # 32 bytes = 64 hex chars, prefixed for readability
    chal = secrets.token_hex(32)
    exp = now + _CHALLENGE_TTL
    _CHALLENGES[chal] = exp
    return chal, exp


def consume_challenge(challenge: str) -> bool:
    """Return True if challenge exists and not expired, then delete it (one-time use)."""
    now = time.time()
    exp = _CHALLENGES.get(challenge)
    if exp is None:
        return False
    if exp < now:
        _CHALLENGES.pop(challenge, None)
        return False
    _CHALLENGES.pop(challenge, None)
    return True


def peek_challenge(challenge: str) -> bool:
    """Check without consuming."""
    exp = _CHALLENGES.get(challenge)
    if exp is None:
        return False
    if exp < time.time():
        _CHALLENGES.pop(challenge, None)
        return False
    return True


# ---------------------------------------------------------------------------
# NIP-01 event helpers (id + structural verify)
# ---------------------------------------------------------------------------
def _serialize_event(pubkey: str, created_at: int, kind: int, tags: list, content: str) -> bytes:
    import json

    arr = [0, pubkey, created_at, kind, tags, content]
    return json.dumps(arr, separators=(",", ":"), ensure_ascii=False).encode()


def compute_event_id(pubkey: str, created_at: int, kind: int, tags: list, content: str) -> str:
    serialized = _serialize_event(pubkey, created_at, kind, tags, content)
    return hashlib.sha256(serialized).hexdigest()


def verify_event_structure(event: dict, expected_challenge: str | None = None) -> tuple[bool, str]:
    """Structure, id hash, BIP-340 signature, challenge and freshness. Returns (ok, reason)."""
    try:
        pubkey = event.get("pubkey", "")
        if not is_valid_hex_pubkey(str(pubkey)):
            return False, "invalid pubkey"
        sig = event.get("sig", "")
        if not re.fullmatch(r"[0-9a-fA-F]{128}", str(sig or "")):
            return False, "invalid signature format (expected 64 bytes hex)"
        eid = event.get("id", "")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", str(eid or "")):
            return False, "invalid id format"
        created_at = event.get("created_at")
        kind = event.get("kind")
        tags = event.get("tags")
        content = event.get("content", "")
        if not isinstance(created_at, int):
            return False, "created_at must be int"
        if not isinstance(kind, int):
            return False, "kind must be int"
        if not isinstance(tags, list):
            return False, "tags must be array"
        if not isinstance(content, str):
            return False, "content must be string"
        # recomputed id must match
        computed = compute_event_id(str(pubkey).lower(), int(created_at), int(kind), list(tags), str(content))
        if computed.lower() != str(eid).lower():
            return False, "id mismatch (event tampered)"
        # The signature is what proves the pubkey signed this event; the checks
        # above only prove it is well formed. Without this anyone could "log in"
        # as any pubkey (audit 2026-09-22).
        if not schnorr_verify(bytes.fromhex(str(eid)), bytes.fromhex(str(pubkey)), bytes.fromhex(str(sig))):
            return False, "invalid signature"
        if expected_challenge is not None:
            # challenge may be in content or in a ["challenge", "<hex>"] tag
            tag_chals = [t[1] for t in tags if isinstance(t, list) and len(t) >= 2 and t[0] == "challenge"]
            content_match = expected_challenge in str(content)
            tag_match = expected_challenge in tag_chals
            if not (content_match or tag_match):
                return False, "challenge not found in event"
        # basic freshness: created_at within 5 min skew
        now = int(time.time())
        if abs(now - int(created_at)) > 600:
            return False, "event timestamp out of range"
        return True, "ok"
    except Exception as exc:
        return False, f"verify error: {exc}"


# BIP-340 Schnorr verification, pure Python, ported from the reference
# implementation (github.com/bitcoin/bips/blob/master/bip-0340/reference.py).
# Nostr event ids are the 32-byte message and pubkeys are x-only (BIP-340).
# Verification only needs public data, so no secret-key code lives here.
_BIP340_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_BIP340_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_BIP340_G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
             0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _bip340_tagged_hash(tag: str, msg: bytes) -> bytes:
    tag_hash = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(tag_hash + tag_hash + msg).digest()


def _bip340_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    if p1[0] == p2[0] and p1[1] != p2[1]:
        return None
    p = _BIP340_P
    if p1 == p2:
        lam = (3 * p1[0] * p1[0] * pow(2 * p1[1], p - 2, p)) % p
    else:
        lam = ((p2[1] - p1[1]) * pow(p2[0] - p1[0], p - 2, p)) % p
    x3 = (lam * lam - p1[0] - p2[0]) % p
    return (x3, (lam * (p1[0] - x3) - p1[1]) % p)


def _bip340_mul(point, scalar: int):
    result = None
    for i in range(256):
        if (scalar >> i) & 1:
            result = _bip340_add(result, point)
        point = _bip340_add(point, point)
    return result


def _bip340_lift_x(x: int):
    p = _BIP340_P
    if x >= p:
        return None
    y_sq = (pow(x, 3, p) + 7) % p
    y = pow(y_sq, (p + 1) // 4, p)
    if pow(y, 2, p) != y_sq:
        return None
    return (x, y if y & 1 == 0 else p - y)


def schnorr_verify(msg: bytes, pubkey: bytes, sig: bytes) -> bool:
    """BIP-340 verification. False for any malformed input, never raises."""
    if len(pubkey) != 32 or len(sig) != 64:
        return False
    point = _bip340_lift_x(int.from_bytes(pubkey, "big"))
    r = int.from_bytes(sig[:32], "big")
    s = int.from_bytes(sig[32:], "big")
    if point is None or r >= _BIP340_P or s >= _BIP340_N:
        return False
    e = int.from_bytes(_bip340_tagged_hash("BIP0340/challenge", sig[:32] + pubkey + msg), "big") % _BIP340_N
    big_r = _bip340_add(_bip340_mul(_BIP340_G, s), _bip340_mul(point, _BIP340_N - e))
    return big_r is not None and big_r[1] % 2 == 0 and big_r[0] == r


# ---------------------------------------------------------------------------
# Persistent identity table (npub <-> token binding for recovery)
# ---------------------------------------------------------------------------
def ensure_nostr_tables() -> None:
    """Create nostr_identities table in same DB as jobs."""
    from .jobs import DB_PATH, init_db

    init_db()
    import sqlite3

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS nostr_identities (
                pubkey TEXT PRIMARY KEY,
                npub TEXT NOT NULL,
                signer TEXT NOT NULL DEFAULT 'unknown',
                created_at REAL NOT NULL,
                last_login REAL NOT NULL
            )"""
        )
        # add signer col if old db
        _add_column(c, "nostr_identities", "signer TEXT NOT NULL DEFAULT 'unknown'")


def store_identity(pubkey_hex: str, signer: str = "unknown") -> dict:
    """Upsert identity; returns {pubkey, npub, signer, created_at, last_login}."""
    import sqlite3
    import time as _time

    from .jobs import DB_PATH

    ensure_nostr_tables()
    pubkey_hex = pubkey_hex.lower()
    npub = hex_to_npub(pubkey_hex)
    now = _time.time()
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT * FROM nostr_identities WHERE pubkey = ?", (pubkey_hex,)).fetchone()
        if row is None:
            c.execute(
                "INSERT INTO nostr_identities (pubkey, npub, signer, created_at, last_login) VALUES (?, ?, ?, ?, ?)",
                (pubkey_hex, npub, signer, now, now),
            )
        else:
            c.execute(
                "UPDATE nostr_identities SET npub = ?, signer = ?, last_login = ? WHERE pubkey = ?",
                (npub, signer, now, pubkey_hex),
            )
        row2 = c.execute("SELECT * FROM nostr_identities WHERE pubkey = ?", (pubkey_hex,)).fetchone()
        assert row2 is not None
        return dict(row2)


def list_identities() -> list[dict]:
    import sqlite3

    from .jobs import DB_PATH

    ensure_nostr_tables()
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM nostr_identities ORDER BY last_login DESC").fetchall()
        return [dict(r) for r in rows]


def remove_identity(pubkey_hex: str) -> bool:
    import sqlite3

    from .jobs import DB_PATH

    ensure_nostr_tables()
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute("DELETE FROM nostr_identities WHERE pubkey = ?", (pubkey_hex.lower(),))
        return cur.rowcount > 0
