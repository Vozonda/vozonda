"""VOZONDA-RENAME-PROTOCOL: user agent, Nostr ai tag, MCP name and feeds.

The rename must not break subscribers:
- RSS item <guid> values and the show's podcast:guid stay byte-identical.
- Visible texts (generator, default description, titles) say Vozonda.
- fetcher User-Agent and Nostr ai tag use vozonda/<version>.
- MCP server name is vozonda.
"""

import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _public_feed(monkeypatch):
    import vozonda_api.routers.feeds as feeds_mod

    monkeypatch.setattr(feeds_mod, "_feed_is_public", lambda: True)


def _fixed_row():
    return {
        "id": "test-rename-guid-1",
        "title": "Rename Test Episode",
        "description": "desc",
        "url": "https://example.com/a",
        "style": "balanced",
        "format": "dialog",
        "script": "[]",
        "created_at": 1700000000,
        "duration_ms": 60000,
        "explicit": False,
        "chapters": None,
    }


# Pre-rename values, computed by running the pre-rename code before the change.
# The item guid is base + /e/<job id>; it never contained the product name.
EXPECTED_GUID = "http://127.0.0.1:8787/e/test-rename-guid-1"
EXPECTED_GUID_TAG = '<guid isPermaLink="true">http://127.0.0.1:8787/e/test-rename-guid-1</guid>'
# Pre-rename code emitted no <podcast:guid> channel tag; absence is the stable value.
EXPECTED_PODCAST_GUID_COUNT = 0


def test_feed_item_guid_is_byte_identical_to_pre_rename():
    import vozonda_api.routers.feeds as feeds_mod

    row = _fixed_row()
    xml = feeds_mod._feed_item(dict(row), "http://127.0.0.1:8787", "Thu, 01 Jan 1970 00:00:00 GMT", [])
    assert EXPECTED_GUID_TAG in xml
    m = re.search(r"<guid[^>]*>(.*?)</guid>", xml)
    assert m is not None
    assert m.group(1) == EXPECTED_GUID


def test_feed_channel_guid_and_podcast_guid_stable(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod
    from vozonda_api.settings_store import set_setting

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    store = jobs_mod.JobStore()
    set_setting("disclosure.ai_label", "0")
    store.create("test-rename-guid-1", "https://example.com/a")
    store.update("test-rename-guid-1", title="Rename Test Episode", description="desc", duration_ms=60000)
    store.finish("test-rename-guid-1")

    client = TestClient(main_mod.app)
    res = client.get("/feed.xml")
    assert res.status_code == 200
    assert EXPECTED_GUID_TAG.replace("http://127.0.0.1:8787", "http://testserver") in res.text
    # podcast:guid stability: pre-rename emitted none, post-rename emits none.
    assert res.text.count("<podcast:guid") == EXPECTED_PODCAST_GUID_COUNT
    # visible texts carry the new name.
    assert "<generator>Vozonda</generator>" in res.text
    assert ("hear" + "say") not in res.text.lower()


def test_user_agent_uses_vozonda():
    from vozonda_api import __version__
    from vozonda_api.fetcher import FETCH_HEADERS

    ua = FETCH_HEADERS["User-Agent"]
    assert ua == f"vozonda/{__version__} (self-hosted audio overviews)"
    assert ("hear" + "say") not in ua.lower()


def test_nostr_ai_tag_uses_vozonda():
    from vozonda_api import __version__
    from vozonda_api.nostr_publish import build_episode_event, build_show_event

    show = {"name": "Test Show"}
    show_ev = build_show_event(show, "abcd" * 16)
    ai = [t for t in show_ev["tags"] if t[0] == "ai"]
    assert len(ai) == 1
    assert ai[0][:3] == ["ai", "vozonda", "generated"]
    assert ai[0][3] == f"vozonda/{__version__}"

    job = {"title": "Ep", "description": "", "url": "https://example.com/1"}
    ep_ev = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
    ai2 = [t for t in ep_ev["tags"] if t[0] == "ai"]
    assert len(ai2) == 1
    assert ai2[0][:3] == ["ai", "vozonda", "generated"]
    assert ai2[0][3] == f"vozonda/{__version__}"


def test_mcp_server_name_is_vozonda():
    from vozonda_api import mcp_server

    assert mcp_server.mcp.name == "vozonda"
