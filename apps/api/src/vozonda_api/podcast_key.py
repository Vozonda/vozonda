"""Per-show podcast Nostr keypair and BIP-340 signing with coincurve.

Keys are stored as 32-byte hex in VOZONDA_SECRETS_DIR/nostr/<show_id>.key
(mode 0600, directory 0700). Never in the database, never logged, never
returned by any API. The pure-Python schnorr_verify in nostr_auth.py is
used for cross-implementation verification.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
from pathlib import Path

from coincurve import PrivateKey

from . import nostr_auth
from .config import VOZONDA_SECRETS_DIR

logger = logging.getLogger(__name__)


def _get_nostr_secret_dir() -> Path:
    """Get the nostr secret directory path at runtime (allows monkeypatching)."""
    return VOZONDA_SECRETS_DIR / "nostr"


def _ensure_secret_dir() -> None:
    """Create the secrets directory with mode 0700."""
    _get_nostr_secret_dir().mkdir(parents=True, exist_ok=True, mode=0o700)


_SHOW_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def _key_path(show_id: str) -> Path:
    """Return the path to the show's secret key file.

    show_id goes into a file name: only [A-Za-z0-9_-], so '../x' or 'a/b' can
    never point outside the key directory."""
    if not isinstance(show_id, str) or not _SHOW_ID.fullmatch(show_id):
        raise ValueError("invalid show id for a key file")
    return _get_nostr_secret_dir() / f"{show_id}.key"


def generate_keypair(show_id: str) -> tuple[str, str]:
    """Generate a new BIP-340 keypair for a show.

    Returns (secret_hex, pubkey_hex). The secret is written to disk
    with mode 0600.
    """
    _key_path(show_id)  # validate the id before touching the disk
    _ensure_secret_dir()

    # Generate 32 random bytes for the secret key
    seckey_bytes = secrets.token_bytes(32)

    # Use coincurve to derive the x-only public key
    pk = PrivateKey(seckey_bytes)
    pubkey_bytes = pk.public_key.format(compressed=False)[1:33]  # x-coordinate only

    seckey_hex = seckey_bytes.hex()
    pubkey_hex = pubkey_bytes.hex()

    # Create the file with mode 0600 from the start (write-then-chmod left it readable
    # in between) and refuse to replace an existing key: that would destroy the show's
    # Nostr identity, which no one can restore.
    key_file = _key_path(show_id)
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(seckey_hex)

    return seckey_hex, pubkey_hex


def load_keypair(show_id: str) -> tuple[str, str]:
    """Load an existing keypair for a show.

    Returns (secret_hex, pubkey_hex). Raises FileNotFoundError if not found.
    """
    key_file = _key_path(show_id)
    if not key_file.exists():
        raise FileNotFoundError(f"no key for show {show_id!r}")

    seckey_hex = key_file.read_text().strip()
    seckey_bytes = bytes.fromhex(seckey_hex)

    # Derive pubkey from secret
    pk = PrivateKey(seckey_bytes)
    pubkey_bytes = pk.public_key.format(compressed=False)[1:33]
    pubkey_hex = pubkey_bytes.hex()

    return seckey_hex, pubkey_hex


def pubkey_to_npub(pubkey_hex: str) -> str:
    """Convert a 32-byte hex pubkey to npub (NIP-19)."""
    return nostr_auth.hex_to_npub(pubkey_hex)


def npub_to_pubkey(npub: str) -> str:
    """Convert an npub to 32-byte hex pubkey."""
    return nostr_auth.npub_to_hex(npub)


def seckey_to_nsec(seckey_hex: str) -> str:
    """Convert a 32-byte hex secret key to nsec (NIP-19)."""
    # nsec uses the same bech32 encoding as npub but with hrp "nsec"
    data = list(bytes.fromhex(seckey_hex))
    converted = nostr_auth._convert_bits(data, 8, 5, True)
    assert converted is not None
    return nostr_auth._bech32_encode("nsec", converted)


def nsec_to_seckey(nsec: str) -> str:
    """Convert an nsec to 32-byte hex secret key."""
    hrp, data = nostr_auth._bech32_decode(nsec)
    if hrp != "nsec" or data is None:
        raise ValueError(f"invalid nsec: {nsec!r}")
    decoded = nostr_auth._convert_bits(data, 5, 8, False)
    if decoded is None or len(decoded) != 32:
        raise ValueError(f"invalid nsec payload: {nsec!r}")
    return bytes(decoded).hex()


def export_nsec(show_id: str) -> str:
    """Export the nsec for a show (explicit user backup action).

    This is the only function that returns the secret in any form.
    """
    seckey_hex, _ = load_keypair(show_id)
    return seckey_to_nsec(seckey_hex)


def _serialize_event(pubkey: str, created_at: int, kind: int, tags: list, content: str) -> bytes:
    """Serialize event for NIP-01 id computation (matches nostr_auth)."""
    arr = [0, pubkey, created_at, kind, tags, content]
    return json.dumps(arr, separators=(",", ":"), ensure_ascii=False).encode()


def compute_event_id(pubkey: str, created_at: int, kind: int, tags: list, content: str) -> str:
    """Compute the NIP-01 event id (sha256 of serialized event)."""
    serialized = _serialize_event(pubkey, created_at, kind, tags, content)
    return hashlib.sha256(serialized).hexdigest()


def sign_event(
    show_id: str,
    event: dict,
    *,
    created_at: int | None = None,
    kind: int | None = None,
    tags: list | None = None,
    content: str | None = None,
) -> dict:
    """Sign a Nostr event for a show.

    The event dict may contain created_at, kind, tags, content. Any missing
    fields will be filled from the event dict or use defaults.
    Returns the event with id, pubkey, and sig populated.
    """
    seckey_hex, pubkey_hex = load_keypair(show_id)
    seckey_bytes = bytes.fromhex(seckey_hex)

    # Fill in event fields
    created_at = created_at if created_at is not None else event.get("created_at", int(__import__("time").time()))
    kind = kind if kind is not None else event.get("kind", 1)
    tags = tags if tags is not None else event.get("tags", [])
    content = content if content is not None else event.get("content", "")

    # Compute event id
    event_id = compute_event_id(pubkey_hex, created_at, kind, tags, content)

    # Sign the event id (32-byte message) using BIP-340 Schnorr
    # coincurve's sign_schnorr takes (message, aux_randomness) where aux_randomness is 32 bytes
    aux_rand = secrets.token_bytes(32)
    pk = PrivateKey(seckey_bytes)
    sig = pk.sign_schnorr(bytes.fromhex(event_id), aux_rand)
    sig_hex = sig.hex()

    return {
        "id": event_id,
        "pubkey": pubkey_hex,
        "created_at": created_at,
        "kind": kind,
        "tags": tags,
        "content": content,
        "sig": sig_hex,
    }


def verify_event_signature(event: dict) -> bool:
    """Verify a Nostr event's signature using the pure Python BIP-340 implementation.

    This uses the same verification as nostr_auth.schnorr_verify for
    cross-implementation consistency.
    """
    try:
        pubkey_hex = event.get("pubkey", "")
        sig_hex = event.get("sig", "")
        event_id = event.get("id", "")

        if not (pubkey_hex and sig_hex and event_id):
            return False

        return nostr_auth.schnorr_verify(
            bytes.fromhex(event_id),
            bytes.fromhex(pubkey_hex),
            bytes.fromhex(sig_hex)
        )
    except Exception:
        return False


def delete_keypair(show_id: str) -> bool:
    """Delete a show's keypair. Returns True if deleted, False if not found."""
    key_file = _key_path(show_id)
    if key_file.exists():
        key_file.unlink()
        return True
    return False


def has_keypair(show_id: str) -> bool:
    """Check if a show has a keypair."""
    return _key_path(show_id).exists()