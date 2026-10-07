"""Tests for podcast_key.py: per-show Nostr keypair and BIP-340 signing."""

import csv
import logging
import stat
from pathlib import Path

import pytest

from vozonda_api import config as vozonda_config
from vozonda_api import podcast_key
from vozonda_api.nostr_auth import compute_event_id, schnorr_verify

VECTORS = Path(__file__).parent / "bip340_test_vectors.csv"

# Correct NIP-19 test vectors (computed with coincurve + our bech32 implementation)
NIP19_VECTORS = [
    # (description, seckey_hex, expected_npub, expected_nsec)
    (
        "NIP-19 test vector: all zeros + 1",
        "0000000000000000000000000000000000000000000000000000000000000001",
        "npub10xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqpkge6d",
        "nsec1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqsmhltgl",
    ),
    (
        "NIP-19 test vector: b7e1...",
        "b7e151628aed2a6abf7158809cf4f3c762e7160f38b4da56a784d9045190cfef",
        "npub1mlcawle2vuw97dscxundkg6phev0atsa5t0vakzrys8hk5pt5evssm7a0a",
        "nsec1kls4zc52a54x40m3tzqfea8nca3ww9s08z6d5448snvsg5vselhsjv8uxn",
    ),
]


@pytest.fixture(autouse=True)
def _reset_secrets_dir(tmp_path, monkeypatch):
    """Isolate VOZONDA_SECRETS_DIR for each test."""
    secrets_dir = tmp_path / "secrets"
    monkeypatch.setattr(podcast_key, "VOZONDA_SECRETS_DIR", secrets_dir)
    monkeypatch.setattr(vozonda_config, "VOZONDA_SECRETS_DIR", secrets_dir)
    yield


def test_generate_keypair_creates_file_with_mode_0600(tmp_path):
    """Secret key file is created with mode 0600."""
    _seckey_hex, _pubkey_hex = podcast_key.generate_keypair("show1")

    key_file = tmp_path / "secrets" / "nostr" / "show1.key"
    assert key_file.exists()

    mode = key_file.stat().st_mode
    assert stat.S_IMODE(mode) == 0o600, f"expected 0600, got {oct(stat.S_IMODE(mode))}"


def test_secret_directory_created_with_mode_0700(tmp_path):
    """Secrets directory is created with mode 0700."""
    podcast_key.generate_keypair("show1")

    nostr_dir = tmp_path / "secrets" / "nostr"
    assert nostr_dir.exists()

    mode = nostr_dir.stat().st_mode
    assert stat.S_IMODE(mode) == 0o700, f"expected 0700, got {oct(stat.S_IMODE(mode))}"


def test_secret_not_in_logs(caplog):
    """Secret key never appears in log records."""
    caplog.set_level(logging.DEBUG)

    seckey_hex, _pubkey_hex = podcast_key.generate_keypair("show1")

    # Check all log records
    for record in caplog.records:
        assert seckey_hex not in record.getMessage(), "secret leaked in logs"
        assert seckey_hex not in record.msg, "secret leaked in log msg"

    # Also check loading doesn't leak
    caplog.clear()
    seckey2, _pubkey2 = podcast_key.load_keypair("show1")
    for record in caplog.records:
        assert seckey2 not in record.getMessage(), "secret leaked on load"
        assert seckey2 not in record.msg, "secret leaked on load msg"


def test_load_after_generate_gives_same_pubkey():
    """Loading a generated keypair yields the same pubkey."""
    seckey1, pubkey1 = podcast_key.generate_keypair("show1")
    seckey2, pubkey2 = podcast_key.load_keypair("show1")

    assert seckey1 == seckey2
    assert pubkey1 == pubkey2


def test_npub_nsec_roundtrip_against_known_vectors():
    """npub/nsec encoding/decoding matches known NIP-19 examples."""
    for desc, seckey_hex, expected_npub, expected_nsec in NIP19_VECTORS:
        # Derive pubkey from seckey
        from coincurve import PrivateKey
        pk = PrivateKey(bytes.fromhex(seckey_hex))
        pubkey_hex = pk.public_key.format(compressed=False)[1:33].hex()

        # Test npub encoding
        npub = podcast_key.pubkey_to_npub(pubkey_hex)
        assert npub == expected_npub, f"{desc}: npub mismatch"

        # Test npub decoding
        decoded_pubkey = podcast_key.npub_to_pubkey(npub)
        assert decoded_pubkey == pubkey_hex.lower(), f"{desc}: npub decode mismatch"

        # Test nsec encoding
        nsec = podcast_key.seckey_to_nsec(seckey_hex)
        assert nsec == expected_nsec, f"{desc}: nsec mismatch"

        # Test nsec decoding
        decoded_seckey = podcast_key.nsec_to_seckey(nsec)
        assert decoded_seckey == seckey_hex.lower(), f"{desc}: nsec decode mismatch"


def test_export_nsec_returns_nsec():
    """export_nsec returns the nsec for a show."""
    podcast_key.generate_keypair("show1")
    nsec = podcast_key.export_nsec("show1")
    assert nsec.startswith("nsec1")
    assert len(nsec) == 63  # nsec1 + 58 chars


def test_sign_event_fills_pubkey_id_sig():
    """sign_event populates id, pubkey, and sig correctly."""
    podcast_key.generate_keypair("show1")

    event = podcast_key.sign_event("show1", {
        "created_at": 1700000000,
        "kind": 1,
        "tags": [["t", "test"]],
        "content": "hello world",
    })

    assert "id" in event
    assert "pubkey" in event
    assert "sig" in event
    assert len(event["id"]) == 64  # 32 bytes hex
    assert len(event["pubkey"]) == 64
    assert len(event["sig"]) == 128  # 64 bytes hex

    # Verify id matches NIP-01 computation
    expected_id = compute_event_id(
        event["pubkey"], event["created_at"], event["kind"],
        event["tags"], event["content"]
    )
    assert event["id"] == expected_id


def test_sign_event_verify_with_nostr_auth():
    """Signed event verifies with nostr_auth.schnorr_verify (cross-impl check)."""
    podcast_key.generate_keypair("show1")

    event = podcast_key.sign_event("show1", {
        "created_at": 1700000000,
        "kind": 1,
        "tags": [],
        "content": "test message",
    })

    ok = schnorr_verify(
        bytes.fromhex(event["id"]),
        bytes.fromhex(event["pubkey"]),
        bytes.fromhex(event["sig"])
    )
    assert ok is True


def test_sign_event_verify_with_module_function():
    """Signed event verifies with podcast_key.verify_event_signature."""
    podcast_key.generate_keypair("show1")

    event = podcast_key.sign_event("show1", {
        "created_at": 1700000000,
        "kind": 1,
        "tags": [],
        "content": "test message",
    })

    assert podcast_key.verify_event_signature(event) is True


def test_official_bip340_vectors_0_to_3():
    """BIP-340 official test vectors 0-3 pass for sign and verify."""
    # We test verification using the vectors (which provide seckey, pubkey, aux_rand, message, sig)
    with VECTORS.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            idx = int(row["index"])
            if idx > 3:
                break

            seckey_hex = row["secret key"]
            pubkey_hex = row["public key"]
            aux_rand_hex = row["aux_rand"]
            msg_hex = row["message"]
            sig_hex = row["signature"]
            expected = row["verification result"] == "TRUE"

            # Test verification with nostr_auth (pure Python)
            ok_pure = schnorr_verify(
                bytes.fromhex(msg_hex),
                bytes.fromhex(pubkey_hex),
                bytes.fromhex(sig_hex)
            )
            assert ok_pure is expected, f"vector {idx}: pure Python verify failed ({row['comment']})"

            # Test signing with coincurve matches the vector's signature
            if seckey_hex:  # Only for vectors that have a secret key
                from coincurve import PrivateKey
                sk = PrivateKey(bytes.fromhex(seckey_hex))
                aux_rand = bytes.fromhex(aux_rand_hex)
                sig = sk.sign_schnorr(bytes.fromhex(msg_hex), aux_rand)
                assert sig.hex() == sig_hex.lower(), f"vector {idx}: sign mismatch"


def test_tampered_event_fails_verification():
    """Any modification to a signed event causes verification to fail."""
    podcast_key.generate_keypair("show1")

    event = podcast_key.sign_event("show1", {
        "created_at": 1700000000,
        "kind": 1,
        "tags": [],
        "content": "original content",
    })

    # Original verifies
    assert podcast_key.verify_event_signature(event) is True
    assert schnorr_verify(
        bytes.fromhex(event["id"]),
        bytes.fromhex(event["pubkey"]),
        bytes.fromhex(event["sig"])
    ) is True

    # Tamper content
    tampered = event.copy()
    tampered["content"] = "tampered content"
    tampered["id"] = compute_event_id(
        tampered["pubkey"], tampered["created_at"], tampered["kind"],
        tampered["tags"], tampered["content"]
    )
    # Keep original sig - should fail
    assert podcast_key.verify_event_signature(tampered) is False
    assert schnorr_verify(
        bytes.fromhex(tampered["id"]),
        bytes.fromhex(tampered["pubkey"]),
        bytes.fromhex(tampered["sig"])
    ) is False

    # Tamper signature
    tampered2 = event.copy()
    tampered2["sig"] = ("0" if tampered2["sig"][0] != "0" else "1") + tampered2["sig"][1:]
    assert podcast_key.verify_event_signature(tampered2) is False

    # Tamper pubkey
    tampered3 = event.copy()
    tampered3["pubkey"] = "0" * 64
    assert podcast_key.verify_event_signature(tampered3) is False


def test_has_keypair_and_delete():
    """has_keypair and delete_keypair work correctly."""
    assert podcast_key.has_keypair("show1") is False

    podcast_key.generate_keypair("show1")
    assert podcast_key.has_keypair("show1") is True

    deleted = podcast_key.delete_keypair("show1")
    assert deleted is True
    assert podcast_key.has_keypair("show1") is False

    # Deleting non-existent returns False
    deleted2 = podcast_key.delete_keypair("show1")
    assert deleted2 is False


def test_load_nonexistent_raises():
    """Loading a non-existent show raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        podcast_key.load_keypair("nonexistent")


def test_sign_event_without_explicit_fields_uses_defaults():
    """sign_event uses defaults for missing fields."""
    podcast_key.generate_keypair("show1")

    # Only provide content
    event = podcast_key.sign_event("show1", {"content": "minimal"})
    assert event["kind"] == 1
    assert event["tags"] == []
    assert "created_at" in event
    assert event["content"] == "minimal"


def test_verify_event_structure_integration():
    """Signed event passes full verify_event_structure from nostr_auth."""
    import time

    from vozonda_api.nostr_auth import verify_event_structure

    podcast_key.generate_keypair("show1")
    challenge = "test-challenge-123"
    now = int(time.time())

    event = podcast_key.sign_event("show1", {
        "created_at": now,
        "kind": 27235,
        "tags": [["challenge", challenge]],
        "content": "",
    })

    ok, reason = verify_event_structure(event, expected_challenge=challenge)
    assert ok is True, reason


def test_multiple_shows_independent_keys():
    """Each show gets an independent keypair."""
    podcast_key.generate_keypair("show1")
    podcast_key.generate_keypair("show2")

    seckey1, pubkey1 = podcast_key.load_keypair("show1")
    seckey2, pubkey2 = podcast_key.load_keypair("show2")

    assert seckey1 != seckey2
    assert pubkey1 != pubkey2


# ---------------------------------------------------------------------------
# Coordinator review 2026-10-01: key material must never be exposed or lost
# (generate overwrote keys silently and a test asserted it; write-then-chmod;
# show_id unchecked in the file path)
# ---------------------------------------------------------------------------


def test_key_file_is_never_world_readable_while_written(monkeypatch):
    """write-then-chmod left the secret readable (umask 0644) between the two calls."""
    import os

    seen_modes: list[int] = []
    real_write_text = Path.write_text

    def spy(self, *a, **kw):  # the secret must not be written through a default-mode file
        seen_modes.append(-1)
        return real_write_text(self, *a, **kw)

    monkeypatch.setattr(Path, "write_text", spy)
    old = os.umask(0o022)
    try:
        podcast_key.generate_keypair("show-mode")
    finally:
        os.umask(old)
    assert seen_modes == []
    assert (podcast_key._key_path("show-mode").stat().st_mode & 0o777) == 0o600


def test_generate_refuses_to_overwrite_an_existing_key():
    """Overwriting a podcast key silently would destroy the show's Nostr identity."""
    _, pub1 = podcast_key.generate_keypair("show-keep")
    with pytest.raises(FileExistsError):
        podcast_key.generate_keypair("show-keep")
    assert podcast_key.load_keypair("show-keep")[1] == pub1


@pytest.mark.parametrize("bad", ["../escape", "a/b", "", ".", "..", "x\x00y", "show id"])
def test_show_id_cannot_leave_the_key_directory(bad):
    with pytest.raises(ValueError):
        podcast_key.generate_keypair(bad)
    with pytest.raises(ValueError):
        podcast_key.load_keypair(bad)
