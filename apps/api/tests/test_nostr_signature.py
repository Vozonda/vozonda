"""Nostr login verifies the BIP-340 signature (audit 2026-09-22).

Vectors: tests/bip340_test_vectors.csv, the official file from
github.com/bitcoin/bips/blob/master/bip-0340/test-vectors.csv. The signer
below is test-only (ported from the BIP-340 reference); production code only
verifies.
"""

import csv
import hashlib
import time
from pathlib import Path

import pytest

from vozonda_api import nostr_auth
from vozonda_api.nostr_auth import compute_event_id, schnorr_verify, verify_event_structure

VECTORS = Path(__file__).parent / "bip340_test_vectors.csv"


def _vectors():
    with VECTORS.open() as fh:
        for row in csv.DictReader(fh):
            yield pytest.param(row, id=f"vector-{row['index']}")


@pytest.mark.parametrize("row", list(_vectors()))
def test_official_bip340_vectors(row):
    ok = schnorr_verify(bytes.fromhex(row["message"]), bytes.fromhex(row["public key"]),
                        bytes.fromhex(row["signature"]))
    assert ok is (row["verification result"] == "TRUE"), row["comment"]


def _sign(msg: bytes, seckey: int) -> tuple[bytes, bytes]:
    """Test-only BIP-340 signer (deterministic, aux_rand = 0)."""
    n, g = nostr_auth._BIP340_N, nostr_auth._BIP340_G
    pub = nostr_auth._bip340_mul(g, seckey)
    d = seckey if pub[1] % 2 == 0 else n - seckey
    pub_b = pub[0].to_bytes(32, "big")
    t = (d ^ int.from_bytes(nostr_auth._bip340_tagged_hash("BIP0340/aux", bytes(32)), "big")).to_bytes(32, "big")
    k0 = int.from_bytes(nostr_auth._bip340_tagged_hash("BIP0340/nonce", t + pub_b + msg), "big") % n
    r_point = nostr_auth._bip340_mul(g, k0)
    k = k0 if r_point[1] % 2 == 0 else n - k0
    r_b = r_point[0].to_bytes(32, "big")
    e = int.from_bytes(nostr_auth._bip340_tagged_hash("BIP0340/challenge", r_b + pub_b + msg), "big") % n
    return pub_b, r_b + ((k + e * d) % n).to_bytes(32, "big")


def _signed_event(challenge: str = "c0ffee") -> dict:
    seckey = int.from_bytes(hashlib.sha256(b"vozonda-test-key").digest(), "big") % nostr_auth._BIP340_N
    pub_b, _ = _sign(bytes(32), seckey)
    pubkey = pub_b.hex()
    created_at, kind, tags, content = int(time.time()), 27235, [["challenge", challenge]], ""
    eid = compute_event_id(pubkey, created_at, kind, tags, content)
    _, sig = _sign(bytes.fromhex(eid), seckey)
    return {"id": eid, "pubkey": pubkey, "created_at": created_at, "kind": kind,
            "tags": tags, "content": content, "sig": sig.hex()}


def test_a_properly_signed_event_verifies():
    ok, reason = verify_event_structure(_signed_event(), expected_challenge="c0ffee")
    assert ok, reason


def test_a_forged_signature_is_rejected():
    event = _signed_event()
    event["sig"] = ("0" if event["sig"][0] != "0" else "1") + event["sig"][1:]
    assert verify_event_structure(event) == (False, "invalid signature")


def test_someone_elses_pubkey_cannot_reuse_a_valid_signature():
    event = _signed_event()
    other = _signed_event()  # same key, so build a second key instead
    seckey2 = int.from_bytes(hashlib.sha256(b"attacker").digest(), "big") % nostr_auth._BIP340_N
    pub2, _ = _sign(bytes(32), seckey2)
    event["pubkey"] = pub2.hex()
    event["id"] = compute_event_id(event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"])
    assert other["sig"]  # keep the original signature, now claimed by another pubkey
    ok, reason = verify_event_structure(event)
    assert not ok and reason == "invalid signature"


def test_malformed_input_never_raises():
    assert schnorr_verify(b"", b"", b"") is False
    assert schnorr_verify(bytes(32), bytes(31), bytes(64)) is False
