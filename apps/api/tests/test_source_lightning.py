"""Tests for Source Lightning address detection, migration, API, and storage."""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import vozonda_api.jobs as jobs_mod
from vozonda_api import settings_store as ss
from vozonda_api import sources as sources_mod
from vozonda_api.main import app


@pytest.fixture(autouse=True)
def _own_db(tmp_path, monkeypatch):
    """Isolated DB for each test."""
    db_file = tmp_path / "jobs.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", db_file)
    monkeypatch.setattr(ss, "DB_PATH", db_file)
    monkeypatch.setenv("VOZONDA_HOST", "127.0.0.1")
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "false")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    monkeypatch.delenv("VOZONDA_PUBLIC_URL", raising=False)

    jobs_mod.init_db()
    ss.ensure_table()
    sources_mod.init_sources_db()
    yield


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------


def test_migration_on_old_database_adds_columns_without_data_loss(tmp_path, monkeypatch):
    """An old database lacking lightning_address columns gains them idempotently."""
    old_db = tmp_path / "old_sources.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", old_db)
    monkeypatch.setattr(ss, "DB_PATH", old_db)

    # 1. Create old table schema without lightning_address columns
    with sqlite3.connect(str(old_db)) as c:
        c.execute("""
            CREATE TABLE sources (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              origin_url TEXT,
              title TEXT NOT NULL DEFAULT '',
              text TEXT,
              words INTEGER NOT NULL DEFAULT 0,
              chars INTEGER NOT NULL DEFAULT 0,
              language TEXT,
              status TEXT NOT NULL DEFAULT 'ready',
              error_code TEXT,
              error_hint TEXT,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            );
        """)
        c.execute(
            "INSERT INTO sources "
            "(id, kind, origin_url, title, text, words, chars, language, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "src-old1",
                "article",
                "https://example.org/art",
                "Old Article",
                "Hello world this is test text",
                6,
                30,
                "en",
                "ready",
                1700000000.0,
                1700000000.0,
            ),
        )

    # 2. Re-open via sources_mod._db() which triggers _migrate_columns
    with sources_mod._db() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sources)").fetchall()]
        assert "lightning_address" in cols
        assert "lightning_address_origin" in cols

        # Check existing row is preserved
        row = conn.execute("SELECT * FROM sources WHERE id = 'src-old1'").fetchone()
        assert row["title"] == "Old Article"
        assert row["lightning_address"] is None
        assert row["lightning_address_origin"] is None

    # 3. Running migration again is idempotent
    with sources_mod._db() as conn:
        sources_mod._migrate_columns(conn)


# ---------------------------------------------------------------------------
# Detection tests: HTML meta and link
# ---------------------------------------------------------------------------


def test_detection_from_html_meta():
    """Detect lightning address from <meta name="lightning" content="..."> or property="lightning"."""
    # name="lightning"
    html1 = '<html><head><meta name="lightning" content="alice@example.org"></head><body>hello</body></html>'
    addr, origin = sources_mod.detect_html_lightning_address(html1)
    assert addr == "alice@example.org"
    assert origin == "detected:html_meta"

    # property="lightning" with lightning: prefix
    html2 = '<html><head><meta property="lightning" content="lightning:bob@example.net"></head><body>hello</body></html>'
    addr, origin = sources_mod.detect_html_lightning_address(html2)
    assert addr == "bob@example.net"
    assert origin == "detected:html_meta"

    # inverted attribute order (content before name)
    html3 = '<html><head><meta content="carol@example.net" name="lightning"></head><body>hello</body></html>'
    addr, origin = sources_mod.detect_html_lightning_address(html3)
    assert addr == "carol@example.net"
    assert origin == "detected:html_meta"


def test_detection_from_html_link():
    """Detect lightning address from <link rel="lightning" href="lightning:...">."""
    html1 = '<html><head><link rel="lightning" href="lightning:dave@example.net"></head><body>hello</body></html>'
    addr, origin = sources_mod.detect_html_lightning_address(html1)
    assert addr == "dave@example.net"
    assert origin == "detected:html_link"

    # href before rel
    html2 = '<html><head><link href="lightning:eve@example.net" rel="lightning"></head><body>hello</body></html>'
    addr, origin = sources_mod.detect_html_lightning_address(html2)
    assert addr == "eve@example.net"
    assert origin == "detected:html_link"


# ---------------------------------------------------------------------------
# Detection tests: RSS lnaddress recipient and funding
# ---------------------------------------------------------------------------


def test_detection_from_rss_podcast_value_lnaddress():
    """Detect lightning address from podcast:value recipient of type lnaddress."""
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:podcast="https://podcastindex.org/namespace/1.0">
      <channel>
        <title>Tech Pod</title>
        <podcast:value type="lightning" method="keysend">
          <podcast:valueRecipient name="Host" type="lnaddress" address="podcaster@example.org" split="100" />
        </podcast:value>
      </channel>
    </rss>
    """
    addr, origin = sources_mod.detect_rss_lightning_address(rss_xml)
    assert addr == "podcaster@example.org"
    assert origin == "detected:podcast_value"


def test_detection_from_rss_podcast_funding():
    """Detect lightning address from podcast:funding tag with a lightning: URL."""
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:podcast="https://podcastindex.org/namespace/1.0">
      <channel>
        <title>Dev Show</title>
        <podcast:funding url="lightning:support@example.net">Send sats to support the show</podcast:funding>
      </channel>
    </rss>
    """
    addr, origin = sources_mod.detect_rss_lightning_address(rss_xml)
    assert addr == "support@example.net"
    assert origin == "detected:podcast_funding"


# ---------------------------------------------------------------------------
# Detection tests: Nostr profile lookup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detection_from_nostr_profile():
    """Detect lightning address from Nostr author kind 0 profile lud16 (mocked lookup)."""
    nostr_url = "nostr:npub180cvv07tjdrrgpa0j7j7tmnyl2yr6yr7l8j4s3evf6u64th6gkwsyjh6w6"

    with patch("vozonda_api.sources.lookup_profile", new_callable=AsyncMock) as mock_lookup:
        mock_lookup.return_value = {
            "name": "Nostr Creator",
            "lud16": "nostr_author@example.org",
            "about": "Testing nostr",
        }
        addr, origin = await sources_mod.detect_nostr_lightning_address(nostr_url)
        assert addr == "nostr_author@example.org"
        assert origin == "detected:nostr_profile"


# ---------------------------------------------------------------------------
# Edge cases: Invalid address ignored, broken page succeeds without address
# ---------------------------------------------------------------------------


def test_invalid_address_is_ignored():
    """Invalid or malformed addresses are discarded and return None, None."""
    # Invalid HTML meta
    html_bad = '<html><head><meta name="lightning" content="not-an-address"></head><body>hello</body></html>'
    addr, origin = sources_mod.detect_html_lightning_address(html_bad)
    assert addr is None
    assert origin is None

    # Invalid RSS valueRecipient
    rss_bad = """<rss xmlns:podcast="https://podcastindex.org/namespace/1.0">
      <channel><podcast:valueRecipient type="lnaddress" address="invalid@@format" /></channel>
    </rss>"""
    addr, origin = sources_mod.detect_rss_lightning_address(rss_bad)
    assert addr is None
    assert origin is None


@pytest.mark.asyncio
async def test_fetch_of_broken_page_still_succeeds_without_address():
    """Detection never fails a fetch; malformed page returns no address and does not raise."""
    broken_content = "<<<invalid XML & HTML content that confuses parsers >>>"
    addr, origin = await sources_mod.detect_lightning_address("https://example.org/broken", broken_content)
    assert addr is None
    assert origin is None


# ---------------------------------------------------------------------------
# Priority & First Hit Wins
# ---------------------------------------------------------------------------


def test_first_hit_wins_meta_over_link():
    """First valid tag wins: HTML meta tag takes precedence over HTML link tag."""
    html = """<html>
      <head>
        <meta name="lightning" content="first@example.org">
        <link rel="lightning" href="lightning:second@example.org">
      </head>
      <body>content</body>
    </html>"""
    addr, origin = sources_mod.detect_html_lightning_address(html)
    assert addr == "first@example.org"
    assert origin == "detected:html_meta"


# ---------------------------------------------------------------------------
# API tests: Manual update, validation (422), clear, and manual origin preservation
# ---------------------------------------------------------------------------


def test_api_manual_update_validates_and_records_manual_origin(client):
    """Manual update via PATCH sets lightning address, validates, and records origin manual."""
    # 1. Create a note source
    res = client.post("/sources", json={"text": "Note with enough text to be a valid source item."})
    assert res.status_code == 202
    sid = res.json()["id"]

    # 2. Get source initially has no lightning address
    src = client.get(f"/sources/{sid}").json()
    assert src["lightning_address"] is None
    assert src["lightning_address_origin"] is None

    # 3. Manual update with valid address
    patch_res = client.patch(f"/sources/{sid}", json={"lightning_address": "alice@example.org"})
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["lightning_address"] == "alice@example.org"
    assert updated["lightning_address_origin"] == "manual"

    # Verify GET returns updated data
    src = client.get(f"/sources/{sid}").json()
    assert src["lightning_address"] == "alice@example.org"
    assert src["lightning_address_origin"] == "manual"

    # 4. Manual update with invalid address returns 422
    bad_res = client.patch(f"/sources/{sid}", json={"lightning_address": "not_an_email"})
    assert bad_res.status_code == 422

    # 5. Clearing the address by sending empty string or None sets them to null
    clear_res = client.patch(f"/sources/{sid}", json={"lightning_address": ""})
    assert clear_res.status_code == 200
    assert clear_res.json()["lightning_address"] is None
    assert clear_res.json()["lightning_address_origin"] is None


def test_manual_lightning_address_is_preserved_when_read_completes():
    """If a manual address is set, subsequent _set_ready call preserves it."""
    sid = sources_mod._insert("article", "https://example.org/post")

    # Manually set lightning address before fetch finishes
    sources_mod.set_lightning_address(sid, "manual_author@example.org")

    # Background fetch finishes with a detected address
    sources_mod._set_ready(
        sid,
        kind="article",
        title="Detected Article Title",
        text="Sufficient article content to pass validation in test.",
        lightning_address="detected@example.org",
        lightning_address_origin="detected:html_meta",
    )

    src = sources_mod.get(sid)
    assert src is not None
    assert src["lightning_address"] == "manual_author@example.org"
    assert src["lightning_address_origin"] == "manual"


# ---------------------------------------------------------------------------
# Privacy and authenticity of the Nostr profile lookup
# ---------------------------------------------------------------------------


def _no_relay(*_a, **_k):
    raise AssertionError("a relay was contacted")


@pytest.mark.asyncio
async def test_a_non_nostr_source_never_contacts_a_relay(monkeypatch):
    """Reading a plain article must not tell any public relay what the user reads."""
    from vozonda_api import nostr_profile

    monkeypatch.setattr(nostr_profile, "_connect", _no_relay)
    html = "<html><head><title>No tags</title></head><body>text</body></html>"
    assert await sources_mod.detect_lightning_address("https://example.org/article", html) == (None, None)
    assert await nostr_profile.lookup_profile("https://example.org/article") is None


def _signed_profile(pk, content: dict, created_at: int, tamper: bool = False) -> dict:
    import json
    import secrets

    from vozonda_api.nostr_auth import compute_event_id

    pub = pk.public_key.format(compressed=True)[1:].hex()
    body = json.dumps(content)
    eid = compute_event_id(pub, created_at, 0, [], body)
    sig = pk.sign_schnorr(bytes.fromhex(eid), secrets.token_bytes(32)).hex()
    if tamper:
        body = json.dumps({**content, "lud16": "thief@example.net"})
    return {"id": eid, "pubkey": pub, "created_at": created_at, "kind": 0, "tags": [], "content": body, "sig": sig}


class _FakeRelay:
    def __init__(self, events):
        import json

        self._msgs = [json.dumps(["EVENT", "sub_profile", e]) for e in events] + [json.dumps(["EOSE", "sub_profile"])]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def send(self, _msg):
        return None

    async def recv(self):
        return self._msgs.pop(0)


async def _lookup_with(monkeypatch, pub: str, events: list) -> dict | None:
    from vozonda_api import nostr_profile
    from vozonda_api.nostr_auth import hex_to_npub

    async def connect(_url, **_k):
        return _FakeRelay(events)

    monkeypatch.setattr(nostr_profile, "_connect", connect)
    monkeypatch.setattr(nostr_profile, "_profile_relays", lambda: ["wss://relay.example.org"])
    return await nostr_profile.lookup_profile("nostr:" + hex_to_npub(pub))


@pytest.mark.asyncio
async def test_the_newest_signed_profile_wins(monkeypatch):
    from coincurve import PrivateKey

    pk = PrivateKey()
    pub = pk.public_key.format(compressed=True)[1:].hex()
    old = _signed_profile(pk, {"lud16": "old@example.org"}, 1_700_000_000)
    new = _signed_profile(pk, {"lud16": "new@example.org"}, 1_700_000_500)
    assert (await _lookup_with(monkeypatch, pub, [old, new]))["lud16"] == "new@example.org"


@pytest.mark.asyncio
async def test_a_forged_or_foreign_profile_is_ignored(monkeypatch):
    """A relay could hand out any lud16; only the author's own signature counts."""
    from coincurve import PrivateKey

    pk, other = PrivateKey(), PrivateKey()
    pub = pk.public_key.format(compressed=True)[1:].hex()
    forged = _signed_profile(pk, {"lud16": "author@example.org"}, 1_700_000_000, tamper=True)
    foreign = _signed_profile(other, {"lud16": "other@example.org"}, 1_700_000_900)
    assert await _lookup_with(monkeypatch, pub, [forged, foreign]) is None


def test_profile_relays_follow_the_setting(monkeypatch):
    from vozonda_api import nostr_profile
    from vozonda_api.nostr_zaps import DEFAULT_RELAYS

    monkeypatch.setattr(ss, "get_setting", lambda k: "wss://relay.example.org, wss://two.example.net" if k == "nostr.relays" else None)
    assert nostr_profile._profile_relays() == ["wss://relay.example.org", "wss://two.example.net"]
    monkeypatch.setattr(ss, "get_setting", lambda k: None)
    assert nostr_profile._profile_relays() == DEFAULT_RELAYS
