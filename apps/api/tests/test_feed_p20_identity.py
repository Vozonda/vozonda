"""Tests for Podcasting 2.0 namespace 1.0 feed identity:
podcast:guid, podcast:txt, podcast:locked, podcast:updateFrequency, and item itunes:image.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

import vozonda_api.jobs as jobs_mod
from vozonda_api import settings_store as ss
from vozonda_api.main import app
from vozonda_api.watchlist import create_watchlist, init_watchlist_db

NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "podcast": "https://podcastindex.org/namespace/1.0",
    "atom": "http://www.w3.org/2005/Atom",
}


@pytest.fixture(autouse=True)
def _own_db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setenv("VOZONDA_HOST", "127.0.0.1")
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "false")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    monkeypatch.delenv("VOZONDA_PUBLIC_URL", raising=False)
    jobs_mod.init_db()
    ss.ensure_table()
    init_watchlist_db()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _show(client: TestClient, name: str) -> str:
    return client.post("/shows", json={"name": name}).json()["slug"]


def _job(
    job_id: str,
    show_slug: str = "",
    created_at: float = 1700000000,
    og_image: str | None = None,
    show_name: str | None = None,
) -> None:
    if show_name is None and show_slug:
        show_name = show_slug.replace("s", "").replace("-", " ").title()
    with sqlite3.connect(str(jobs_mod.DB_PATH)) as c:
        c.execute(
            "INSERT OR REPLACE INTO jobs (id, url, state, title, created_at, show_slug, updated_at, og_image, show_name) "
            "VALUES (?, ?, 'done', ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                "https://example.com/" + job_id,
                job_id,
                created_at,
                show_slug,
                created_at,
                og_image,
                show_name or "",
            ),
        )


def _feed_path(client: TestClient, slug: str) -> str:
    show = next(s for s in client.get("/distribution").json()["shows"] if s["slug"] == slug)
    return show["feed_url"].split("testserver", 1)[1].split("?")[0]


def test_podcast_guid_computed_per_spec_and_stored_once(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    ss.set_setting("show.name", "Main Show")
    ss.set_setting("show.default.public", "1")

    # In TestClient, request.base_url is http://testserver, self_path is /feed.xml
    # Spec: UUIDv5 with namespace ead4c236-bf58-58c6-a2c6-a6b28d128cb6
    # over feed URL without scheme, trailing slash, or ?key=
    spec_ns = uuid.UUID("ead4c236-bf58-58c6-a2c6-a6b28d128cb6")
    expected_guid = str(uuid.uuid5(spec_ns, "testserver/feed.xml"))

    res = client.get("/feed.xml")
    assert res.status_code == 200
    root = ET.fromstring(res.text)
    channel = root.find("channel")
    assert channel is not None
    guid_elem = channel.find("podcast:guid", NS)
    assert guid_elem is not None
    assert guid_elem.text == expected_guid

    # Stored once, per feed path
    assert json.loads(ss.get_setting("feed.guids"))["/feed.xml"] == expected_guid

    # Change public URL: the stored guid must stay unchanged
    monkeypatch.setenv("VOZONDA_PUBLIC_URL", "https://podcast.example.org")
    res2 = client.get("/feed.xml")
    assert res2.status_code == 200
    root2 = ET.fromstring(res2.text)
    channel2 = root2.find("channel")
    assert channel2 is not None
    guid_elem2 = channel2.find("podcast:guid", NS)
    assert guid_elem2 is not None
    assert guid_elem2.text == expected_guid

    # Fetch with key: guid stays the same
    res3 = client.get("/feed.xml?key=randomkey")
    root3 = ET.fromstring(res3.text)
    channel3 = root3.find("channel")
    assert channel3 is not None
    guid_elem3 = channel3.find("podcast:guid", NS)
    assert guid_elem3 is not None
    assert guid_elem3.text == expected_guid


def test_podcast_guid_hand_set_wins(client: TestClient) -> None:
    ss.set_setting("show.name", "Main Show")
    ss.set_setting("show.default.public", "1")
    hand_set = "99999999-8888-7777-6666-555555555555"
    ss.set_setting("feed.guids", json.dumps({"/feed.xml": hand_set}))

    res = client.get("/feed.xml")
    assert res.status_code == 200
    root = ET.fromstring(res.text)
    channel = root.find("channel")
    assert channel is not None
    guid_elem = channel.find("podcast:guid", NS)
    assert guid_elem is not None
    assert guid_elem.text == hand_set


def test_podcast_guid_per_show(client: TestClient) -> None:
    slug = _show(client, "Tech Trends")
    ss.set_setting(f"show.{slug[1:]}.public", "1")
    feed_path = _feed_path(client, slug)

    spec_ns = uuid.UUID("ead4c236-bf58-58c6-a2c6-a6b28d128cb6")
    clean_url = f"testserver{feed_path}"
    expected_guid = str(uuid.uuid5(spec_ns, clean_url))

    res = client.get(feed_path)
    assert res.status_code == 200
    root = ET.fromstring(res.text)
    channel = root.find("channel")
    assert channel is not None
    guid_elem = channel.find("podcast:guid", NS)
    assert guid_elem is not None
    assert guid_elem.text == expected_guid
    guids = json.loads(ss.get_setting("feed.guids"))
    assert guids[feed_path] == expected_guid
    # the main feed is a different feed and gets its own guid
    ss.set_setting("show.name", "Main Show")
    ss.set_setting("show.default.public", "1")
    assert client.get("/feed.xml").status_code == 200
    assert json.loads(ss.get_setting("feed.guids"))["/feed.xml"] != expected_guid


def test_podcast_txt_tag_escaped(client: TestClient) -> None:
    ss.set_setting("show.name", "Main Show")
    ss.set_setting("show.default.public", "1")
    txt_data = [
        {"purpose": "verify", "value": "abc123token & <safe>"},
        {"purpose": "claim", "value": "quoted \"value\" & test"},
    ]
    ss.set_setting("show.txt", json.dumps(txt_data))

    res = client.get("/feed.xml")
    assert res.status_code == 200
    assert "abc123token &amp; &lt;safe&gt;" in res.text

    root = ET.fromstring(res.text)
    channel = root.find("channel")
    assert channel is not None
    txt_elems = channel.findall("podcast:txt", NS)
    assert len(txt_elems) == 2
    assert txt_elems[0].attrib.get("purpose") == "verify"
    assert txt_elems[0].text == "abc123token & <safe>"
    assert txt_elems[1].attrib.get("purpose") == "claim"
    assert txt_elems[1].text == 'quoted "value" & test'


def test_podcast_txt_absent_when_empty(client: TestClient) -> None:
    ss.set_setting("show.name", "Main Show")
    ss.set_setting("show.default.public", "1")

    res = client.get("/feed.xml")
    assert res.status_code == 200
    root = ET.fromstring(res.text)
    channel = root.find("channel")
    assert channel is not None
    assert channel.find("podcast:txt", NS) is None


def test_podcast_locked_requires_owner_email(client: TestClient) -> None:
    ss.set_setting("show.name", "Main Show")
    ss.set_setting("show.default.public", "1")

    # show.locked = 1 without owner email: no tag
    ss.set_setting("show.locked", "1")
    res1 = client.get("/feed.xml")
    root1 = ET.fromstring(res1.text)
    channel1 = root1.find("channel")
    assert channel1 is not None
    assert channel1.find("podcast:locked", NS) is None

    # owner email without show.locked = 1: no tag
    ss.set_setting("show.locked", "0")
    ss.set_setting("show.owner_email", "podcaster@example.org")
    res2 = client.get("/feed.xml")
    root2 = ET.fromstring(res2.text)
    channel2 = root2.find("channel")
    assert channel2 is not None
    assert channel2.find("podcast:locked", NS) is None

    # Both show.locked = 1 and owner_email set: writes tag
    ss.set_setting("show.locked", "1")
    res3 = client.get("/feed.xml")
    root3 = ET.fromstring(res3.text)
    channel3 = root3.find("channel")
    assert channel3 is not None
    locked_elem = channel3.find("podcast:locked", NS)
    assert locked_elem is not None
    assert locked_elem.text == "yes"
    assert locked_elem.attrib.get("owner") == "podcaster@example.org"


def test_update_frequency_watchlist_schedule(client: TestClient) -> None:
    ss.set_setting("show.name", "Main Show")
    ss.set_setting("show.default.public", "1")

    # Daily watchlist schedule
    create_watchlist(
        feed_url="https://example.com/daily.rss",
        schedule="daily@08:30",
        show_slug="default",
    )
    res_daily = client.get("/feed.xml")
    root_daily = ET.fromstring(res_daily.text)
    channel_daily = root_daily.find("channel")
    assert channel_daily is not None
    freq_daily = channel_daily.find("podcast:updateFrequency", NS)
    assert freq_daily is not None
    assert freq_daily.attrib.get("rrule") == "FREQ=DAILY"
    assert freq_daily.text == "Daily"

    # Weekly watchlist schedule on a per-show feed
    slug = _show(client, "Weekly News")
    ss.set_setting(f"show.{slug[1:]}.public", "1")
    create_watchlist(
        feed_url="https://example.com/weekly.rss",
        schedule="weekly@tue@12:00",
        show_slug=slug,
    )
    feed_path = _feed_path(client, slug)
    res_weekly = client.get(feed_path)
    root_weekly = ET.fromstring(res_weekly.text)
    channel_weekly = root_weekly.find("channel")
    assert channel_weekly is not None
    freq_weekly = channel_weekly.find("podcast:updateFrequency", NS)
    assert freq_weekly is not None
    assert freq_weekly.attrib.get("rrule") == "FREQ=WEEKLY"
    assert freq_weekly.text == "Weekly"


def test_update_frequency_episode_gaps(client: TestClient) -> None:
    ss.set_setting("show.name", "Rhythm Show")
    ss.set_setting("show.default.public", "1")

    # 4 episodes with weekly gaps (7 days = 604800s)
    t0 = 1700000000.0
    day = 86400.0
    _job("ep1", created_at=t0)
    _job("ep2", created_at=t0 + 7.1 * day)
    _job("ep3", created_at=t0 + 14.2 * day)
    _job("ep4", created_at=t0 + 21.0 * day)

    res = client.get("/feed.xml")
    root = ET.fromstring(res.text)
    channel = root.find("channel")
    assert channel is not None
    freq = channel.find("podcast:updateFrequency", NS)
    assert freq is not None
    assert freq.attrib.get("rrule") == "FREQ=WEEKLY"
    assert freq.text == "Weekly"

    # Daily gaps: 1 day apart
    with sqlite3.connect(str(jobs_mod.DB_PATH)) as c:
        c.execute("DELETE FROM jobs")
    _job("d1", created_at=t0)
    _job("d2", created_at=t0 + 1.0 * day)
    _job("d3", created_at=t0 + 2.1 * day)
    _job("d4", created_at=t0 + 3.0 * day)

    res_d = client.get("/feed.xml")
    root_d = ET.fromstring(res_d.text)
    channel_d = root_d.find("channel")
    assert channel_d is not None
    freq_d = channel_d.find("podcast:updateFrequency", NS)
    assert freq_d is not None
    assert freq_d.attrib.get("rrule") == "FREQ=DAILY"
    assert freq_d.text == "Daily"

    # Every two weeks: 14 days apart
    with sqlite3.connect(str(jobs_mod.DB_PATH)) as c:
        c.execute("DELETE FROM jobs")
    _job("w2_1", created_at=t0)
    _job("w2_2", created_at=t0 + 14.0 * day)
    _job("w2_3", created_at=t0 + 28.5 * day)

    res_w2 = client.get("/feed.xml")
    root_w2 = ET.fromstring(res_w2.text)
    channel_w2 = root_w2.find("channel")
    assert channel_w2 is not None
    freq_w2 = channel_w2.find("podcast:updateFrequency", NS)
    assert freq_w2 is not None
    assert freq_w2.attrib.get("rrule") == "FREQ=WEEKLY;INTERVAL=2"
    assert freq_w2.text == "Every two weeks"

    # Monthly: 30 days apart
    with sqlite3.connect(str(jobs_mod.DB_PATH)) as c:
        c.execute("DELETE FROM jobs")
    _job("m1", created_at=t0)
    _job("m2", created_at=t0 + 29.0 * day)
    _job("m3", created_at=t0 + 59.0 * day)

    res_m = client.get("/feed.xml")
    root_m = ET.fromstring(res_m.text)
    channel_m = root_m.find("channel")
    assert channel_m is not None
    freq_m = channel_m.find("podcast:updateFrequency", NS)
    assert freq_m is not None
    assert freq_m.attrib.get("rrule") == "FREQ=MONTHLY"
    assert freq_m.text == "Monthly"

    # Irregular gaps: no tag
    with sqlite3.connect(str(jobs_mod.DB_PATH)) as c:
        c.execute("DELETE FROM jobs")
    _job("irr1", created_at=t0)
    _job("irr2", created_at=t0 + 2.0 * day)
    _job("irr3", created_at=t0 + 25.0 * day)

    res_irr = client.get("/feed.xml")
    root_irr = ET.fromstring(res_irr.text)
    channel_irr = root_irr.find("channel")
    assert channel_irr is not None
    assert channel_irr.find("podcast:updateFrequency", NS) is None

    # Fewer than 3 episodes: no tag
    with sqlite3.connect(str(jobs_mod.DB_PATH)) as c:
        c.execute("DELETE FROM jobs")
    _job("few1", created_at=t0)
    _job("few2", created_at=t0 + 7.0 * day)

    res_few = client.get("/feed.xml")
    root_few = ET.fromstring(res_few.text)
    channel_few = root_few.find("channel")
    assert channel_few is not None
    assert channel_few.find("podcast:updateFrequency", NS) is None


def test_item_artwork_key_only_on_private_episodes(client: TestClient) -> None:
    ss.set_setting("show.name", "Main")
    priv = _show(client, "Priv Show")
    pub = _show(client, "Pub Show")
    ss.set_setting(f"show.{pub[1:]}.public", "1")

    _job("ep-pub", show_slug=pub, og_image="pub-art.png", show_name="Pub Show")
    _job("ep-pub-no-img", show_slug=pub, og_image=None, show_name="Pub Show")
    _job("ep-priv", show_slug=priv, og_image="priv-art.png", show_name="Priv Show")

    # Public show feed without key
    pub_feed_path = _feed_path(client, pub)
    res_pub = client.get(pub_feed_path)
    root_pub = ET.fromstring(res_pub.text)
    items_pub = root_pub.findall(".//item")
    assert len(items_pub) == 2

    ep_pub_item = next(it for it in items_pub if it.find("title").text == "ep-pub")
    pub_img = ep_pub_item.find("itunes:image", NS)
    assert pub_img is not None
    assert pub_img.attrib.get("href") == "http://testserver/img/pub-art.png"
    assert "key=" not in pub_img.attrib.get("href", "")

    ep_no_img_item = next(it for it in items_pub if it.find("title").text == "ep-pub-no-img")
    assert ep_no_img_item.find("itunes:image", NS) is None

    # Private show feed with key: image carries key
    key = ss.get_private_feed_key()
    priv_feed_path = _feed_path(client, priv)
    res_priv = client.get(f"{priv_feed_path}?key={key}")
    root_priv = ET.fromstring(res_priv.text)
    priv_item = root_priv.find(".//item")
    assert priv_item is not None
    priv_img = priv_item.find("itunes:image", NS)
    assert priv_img is not None
    assert priv_img.attrib.get("href") == f"http://testserver/img/priv-art.png?key={key}"


def test_locked_per_show_uses_the_one_owner_email(client: TestClient) -> None:
    slug = _show(client, "Locked Show")
    num = slug[1:]
    ss.set_setting(f"show.{num}.public", "1")
    ss.set_setting(f"show.{num}.locked", "1")
    path = _feed_path(client, slug)
    channel = ET.fromstring(client.get(path).text).find("channel")
    assert channel.find("podcast:locked", NS) is None          # no owner e-mail yet
    ss.set_setting("show.owner_email", "owner@example.org")
    locked = ET.fromstring(client.get(path).text).find("channel").find("podcast:locked", NS)
    assert locked is not None and locked.attrib["owner"] == "owner@example.org" and locked.text == "yes"


def test_txt_setting_is_validated(client: TestClient) -> None:
    assert client.put("/settings/show.txt", json={"value": "not json"}).status_code in (400, 422)
    assert client.put("/settings/show.txt", json={"value": json.dumps([{"purpose": "verify"}])}).status_code in (400, 422)
    ok = client.put("/settings/show.txt", json={"value": json.dumps([{"purpose": "verify", "value": "abc"}])})
    assert ok.status_code == 200
