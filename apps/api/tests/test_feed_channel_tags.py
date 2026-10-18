"""#58: channel tags Apple Podcasts and Spotify require (owner e-mail, explicit, language)."""

import pytest
from fastapi.testclient import TestClient

from vozonda_api import jobs as jobs_mod
from vozonda_api import main as main_mod
from vozonda_api import settings_store as ss


@pytest.fixture()
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "vozonda-test.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", db)
    monkeypatch.setattr(ss, "DB_PATH", db)
    jobs_mod.init_db()
    ss.ensure_table()
    ss.set_setting("feed.public", "1")
    return TestClient(main_mod.app)


def test_defaults_english_not_explicit_no_owner(client: TestClient) -> None:
    txt = client.get("/feed.xml").text
    assert "<language>en</language>" in txt
    assert txt.count("<itunes:explicit>false</itunes:explicit>") == 1     # channel level only, no items
    assert "<itunes:owner>" not in txt


def test_settings_reach_the_channel(client: TestClient) -> None:
    ss.set_setting("show.owner_email", "host@example.org")
    ss.set_setting("show.owner_name", "Host & Co")
    ss.set_setting("show.explicit", "1")
    ss.set_setting("show.language", "de")
    txt = client.get("/feed.xml").text
    assert "<language>de</language>" in txt
    assert "<itunes:explicit>true</itunes:explicit>" in txt
    assert ("<itunes:owner><itunes:name>Host &amp; Co</itunes:name>"
            "<itunes:email>host@example.org</itunes:email></itunes:owner>") in txt


def test_owner_name_falls_back_to_the_author(client: TestClient) -> None:
    ss.set_setting("show.author", "Jane Doe")
    ss.set_setting("show.owner_email", "jane@example.org")
    txt = client.get("/feed.xml").text
    assert "<itunes:owner><itunes:name>Jane Doe</itunes:name>" in txt


@pytest.mark.parametrize("key, value", [
    ("show.owner_email", "nope"),
    ("show.owner_email", "a@b"),
    ("show.explicit", "yes"),
    ("show.language", "German"),
])
def test_invalid_values_are_refused(client: TestClient, key: str, value: str) -> None:
    with pytest.raises(ValueError):
        ss.set_setting(key, value)


def test_empty_values_are_allowed(client: TestClient) -> None:
    ss.set_setting("show.owner_email", "")
    ss.set_setting("show.language", "")
    assert "<language>en</language>" in client.get("/feed.xml").text
