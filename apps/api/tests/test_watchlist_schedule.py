"""Tests for watchlist scheduled digests (VOZONDA-WATCH-SCHEDULE).

Covers:
- Schedule and timezone validation (bad formats rejected with 422)
- GET /watchlist returns schedule, schedule_tz, last_scheduled_run
- Injected/frozen clock: daily fires once per day
- Injected/frozen clock: weekly only on its weekday
- Repeated polls inside the slot do not fire twice
- Missed-run catch-up fires once (not once per missed slot)
- No new entries: no episode, one log line, last_scheduled_run recorded
- No-schedule path still renders per entry
"""

import asyncio
import datetime

from fastapi.testclient import TestClient
import pytest

from vozonda_api import jobs as jobs_mod
from vozonda_api.jobs import JobStore
from vozonda_api.main import app
from vozonda_api.watchlist import (
    create_watchlist,
    get_watchlist,
    init_watchlist_db,
    update_watchlist,
    validate_schedule,
    validate_timezone,
)
from vozonda_api.watchlist_poller import is_schedule_due, poll_single

SAMPLE_RSS_3 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Tech Dispatch</title>
    <link>https://example.com</link>
    <item>
      <title>Article Alpha</title>
      <link>https://example.com/alpha</link>
      <guid>https://example.com/alpha</guid>
    </item>
    <item>
      <title>Article Beta</title>
      <link>https://example.com/beta</link>
      <guid>https://example.com/beta</guid>
    </item>
    <item>
      <title>Article Gamma</title>
      <link>https://example.com/gamma</link>
      <guid>https://example.com/gamma</guid>
    </item>
  </channel>
</rss>
"""

SAMPLE_RSS_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Empty Feed</title>
    <link>https://example.com</link>
  </channel>
</rss>
"""


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Isolated SQLite database for jobs and watchlists."""
    db_file = tmp_path / "test_jobs.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", db_file)
    monkeypatch.setenv("VOZONDA_DB", str(db_file))
    # Loopback and billing off to keep write auth open for tests
    monkeypatch.setenv("VOZONDA_HOST", "127.0.0.1")
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "false")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)

    jobs_mod.init_db()
    init_watchlist_db()

    # The tests poll with fixed 2026-10-01 timestamps; create_watchlist stamps created_at
    # with the real clock, so after 08:00 UTC that day every slot looked older than the
    # watchlist and the tests started failing. Pin the wall clock (time.time, restored after
    # each test) to midnight before all slots; the tests pass their poll time explicitly.
    import vozonda_api.watchlist as watchlist_mod

    _t0 = datetime.datetime(2026, 10, 1, 0, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    monkeypatch.setattr(watchlist_mod.time, "time", lambda: _t0)

    # Stub out background pipeline execution
    async def fake_run(job_id, runner=None):
        pass

    monkeypatch.setattr("vozonda_api.main._run", fake_run)
    monkeypatch.setattr("vozonda_api.watchlist_poller._run", fake_run, raising=False)

    yield db_file


@pytest.fixture
def client(test_db):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Unit tests: validate_schedule and validate_timezone
# ---------------------------------------------------------------------------

def test_validate_schedule_valid():
    assert validate_schedule("daily@08:00") == "daily@08:00"
    assert validate_schedule("daily@8:00") == "daily@08:00"
    assert validate_schedule("DAILY@23:59") == "daily@23:59"
    assert validate_schedule("daily@00:00") == "daily@00:00"
    assert validate_schedule("weekly@mon@09:30") == "weekly@mon@09:30"
    assert validate_schedule("weekly@sun@18:00") == "weekly@sun@18:00"
    assert validate_schedule("weekly@FRI@00:00") == "weekly@fri@00:00"
    assert validate_schedule(None) is None


@pytest.mark.parametrize(
    "bad_schedule",
    [
        "",
        "   ",
        "daily",
        "daily@",
        "daily@24:00",
        "daily@08:60",
        "daily@abc",
        "daily@08:00:00",
        "weekly",
        "weekly@mon",
        "weekly@12:00",
        "weekly@monday@08:00",
        "weekly@tuesday@08:00",
        "weekly@foo@08:00",
        "hourly@08:00",
        "monthly@01@08:00",
        "random string",
    ],
)
def test_validate_schedule_invalid_raises(bad_schedule):
    with pytest.raises(ValueError):
        validate_schedule(bad_schedule)


def test_validate_timezone_valid():
    assert validate_timezone("UTC") == "UTC"
    assert validate_timezone("America/New_York") == "America/New_York"
    assert validate_timezone("Europe/Berlin") == "Europe/Berlin"
    assert validate_timezone("Asia/Tokyo") == "Asia/Tokyo"


@pytest.mark.parametrize(
    "bad_tz",
    [
        "",
        "   ",
        "Mars/Phobos",
        "Invalid/Timezone",
        "UTC+2",
    ],
)
def test_validate_timezone_invalid_raises(bad_tz):
    with pytest.raises(ValueError):
        validate_timezone(bad_tz)


# ---------------------------------------------------------------------------
# API tests: POST /watchlist and PUT /watchlist/{wid} validation
# ---------------------------------------------------------------------------

def test_api_rejects_bad_schedule_format(client):
    resp = client.post(
        "/watchlist",
        json={"feed_url": "https://example.com/rss.xml", "schedule": "daily@25:00"},
    )
    assert resp.status_code == 422

    resp = client.post(
        "/watchlist",
        json={"feed_url": "https://example.com/rss.xml", "schedule": "weekly@monday@08:00"},
    )
    assert resp.status_code == 422

    resp = client.post(
        "/watchlist",
        json={"feed_url": "https://example.com/rss.xml", "schedule": "hourly@12:00"},
    )
    assert resp.status_code == 422


def test_api_rejects_unknown_timezone(client):
    resp = client.post(
        "/watchlist",
        json={
            "feed_url": "https://example.com/rss.xml",
            "schedule": "daily@08:00",
            "schedule_tz": "Atlantis/Deep",
        },
    )
    assert resp.status_code == 422


def test_api_accepts_valid_schedule_and_get_returns_them(client):
    resp = client.post(
        "/watchlist",
        json={
            "feed_url": "https://example.com/rss.xml",
            "schedule": "daily@08:00",
            "schedule_tz": "America/New_York",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["schedule"] == "daily@08:00"
    assert data["schedule_tz"] == "America/New_York"
    assert data["last_scheduled_run"] is None
    wid = data["id"]

    # GET /watchlist returns schedule columns
    list_resp = client.get("/watchlist")
    assert list_resp.status_code == 200
    watchlists = list_resp.json()["watchlist"]
    matched = next((w for w in watchlists if w["id"] == wid), None)
    assert matched is not None
    assert matched["schedule"] == "daily@08:00"
    assert matched["schedule_tz"] == "America/New_York"
    assert matched["last_scheduled_run"] is None

    # GET /watchlist/{wid} returns schedule columns
    item_resp = client.get(f"/watchlist/{wid}")
    assert item_resp.status_code == 200
    item_data = item_resp.json()
    assert item_data["schedule"] == "daily@08:00"
    assert item_data["schedule_tz"] == "America/New_York"

    # PUT /watchlist/{wid} update schedule and timezone
    put_resp = client.put(
        f"/watchlist/{wid}",
        json={"schedule": "weekly@mon@09:30", "schedule_tz": "Europe/Berlin"},
    )
    assert put_resp.status_code == 200
    updated = put_resp.json()
    assert updated["schedule"] == "weekly@mon@09:30"
    assert updated["schedule_tz"] == "Europe/Berlin"

    # PUT /watchlist/{wid} with invalid schedule fails
    bad_put = client.put(f"/watchlist/{wid}", json={"schedule": "bad_format"})
    assert bad_put.status_code == 422

    # PUT /watchlist/{wid} with None clears schedule
    clear_put = client.put(f"/watchlist/{wid}", json={"schedule": None})
    assert clear_put.status_code == 200
    assert clear_put.json()["schedule"] is None


# ---------------------------------------------------------------------------
# Injected / frozen clock tests: is_schedule_due
# ---------------------------------------------------------------------------

def test_is_schedule_due_daily():
    schedule = "daily@08:00"
    tz = "UTC"

    # 2026-10-01 07:59:00 UTC - before slot
    t_before = datetime.datetime(2026, 10, 1, 7, 59, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert not is_schedule_due(schedule, tz, None, t_before, created_at=t_before)

    # 2026-10-01 08:00:00 UTC - slot arrived
    t_at = datetime.datetime(2026, 10, 1, 8, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert is_schedule_due(schedule, tz, None, t_at, created_at=t_before)

    # 2026-10-01 08:00:30 UTC - inside slot, already run at 08:00:00
    t_inside = datetime.datetime(2026, 10, 1, 8, 0, 30, tzinfo=datetime.timezone.utc).timestamp()
    assert not is_schedule_due(schedule, tz, t_at, t_inside, created_at=t_before)

    # 2026-10-01 15:00:00 UTC - later same day
    t_later = datetime.datetime(2026, 10, 1, 15, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert not is_schedule_due(schedule, tz, t_at, t_later, created_at=t_before)

    # 2026-10-02 07:59:00 UTC - next day before slot
    t_next_day_before = datetime.datetime(2026, 10, 2, 7, 59, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert not is_schedule_due(schedule, tz, t_at, t_next_day_before, created_at=t_before)

    # 2026-10-02 08:00:00 UTC - next day at slot
    t_next_day_at = datetime.datetime(2026, 10, 2, 8, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert is_schedule_due(schedule, tz, t_at, t_next_day_at, created_at=t_before)


def test_is_schedule_due_weekly():
    # Wednesday 10:00 UTC
    schedule = "weekly@wed@10:00"
    tz = "UTC"

    # 2026-10-05 (Monday) 10:00:00 UTC
    t_mon = datetime.datetime(2026, 10, 5, 10, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert not is_schedule_due(schedule, tz, None, t_mon, created_at=t_mon)

    # 2026-10-06 (Tuesday) 10:00:00 UTC
    t_tue = datetime.datetime(2026, 10, 6, 10, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert not is_schedule_due(schedule, tz, None, t_tue, created_at=t_mon)

    # 2026-10-07 (Wednesday) 09:59:00 UTC
    t_wed_before = datetime.datetime(2026, 10, 7, 9, 59, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert not is_schedule_due(schedule, tz, None, t_wed_before, created_at=t_mon)

    # 2026-10-07 (Wednesday) 10:00:00 UTC - fires!
    t_wed_at = datetime.datetime(2026, 10, 7, 10, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert is_schedule_due(schedule, tz, None, t_wed_at, created_at=t_mon)

    # 2026-10-07 (Wednesday) 10:05:00 UTC - already ran
    t_wed_after = datetime.datetime(2026, 10, 7, 10, 5, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert not is_schedule_due(schedule, tz, t_wed_at, t_wed_after, created_at=t_mon)

    # 2026-10-08 (Thursday) 10:00:00 UTC - next day
    t_thu = datetime.datetime(2026, 10, 8, 10, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert not is_schedule_due(schedule, tz, t_wed_at, t_thu, created_at=t_mon)

    # 2026-10-14 (Next Wednesday) 10:00:00 UTC - fires!
    t_next_wed = datetime.datetime(2026, 10, 14, 10, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert is_schedule_due(schedule, tz, t_wed_at, t_next_wed, created_at=t_mon)


def test_is_schedule_due_with_timezone():
    # 08:00 AM America/New_York (EDT, UTC-4) is 12:00 UTC
    schedule = "daily@08:00"
    tz = "America/New_York"

    # 08:00 UTC is 04:00 AM in NY -> not due
    t_utc_8 = datetime.datetime(2026, 10, 1, 8, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert not is_schedule_due(schedule, tz, None, t_utc_8, created_at=t_utc_8)

    # 12:00 UTC is 08:00 AM in NY -> due!
    t_utc_12 = datetime.datetime(2026, 10, 1, 12, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert is_schedule_due(schedule, tz, None, t_utc_12, created_at=t_utc_8)


# ---------------------------------------------------------------------------
# Poller tests with frozen clock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_fires_once_per_day(test_db, monkeypatch):
    """Daily schedule fires exactly once per day at or after scheduled time."""
    async def mock_fetch(url):
        return SAMPLE_RSS_3

    monkeypatch.setattr("vozonda_api.watchlist_poller.fetch_feed_text", mock_fetch)

    tasks_dict: dict = {}
    listeners_dict: dict = {}
    test_store = JobStore()

    # Created at 07:00 UTC
    t_0700 = datetime.datetime(2026, 10, 1, 7, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    wl = create_watchlist("https://example.com/feed-daily.xml", schedule="daily@08:00", schedule_tz="UTC")

    # Poll at 07:30 UTC: before schedule -> returns []
    t_0730 = datetime.datetime(2026, 10, 1, 7, 30, 0, tzinfo=datetime.timezone.utc).timestamp()
    created = await poll_single(wl, test_store, tasks_dict, listeners_dict, now=t_0730)
    assert created == []

    # Poll at 08:00 UTC: schedule arrived -> exactly ONE digest render
    t_0800 = datetime.datetime(2026, 10, 1, 8, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    created = await poll_single(wl, test_store, tasks_dict, listeners_dict, now=t_0800)
    assert len(created) == 1
    job_id = created[0]
    assert job_id.startswith("digest-")

    # Verify job properties in store
    job = test_store.get(job_id)
    assert job["digest"] == 1
    assert len(job["digest_sources"]) == 3

    # Verify last_scheduled_run recorded in DB
    updated_wl = get_watchlist(wl["id"])
    assert updated_wl["last_scheduled_run"] == t_0800

    # Poll at 12:00 UTC: same day later -> does not fire again
    t_1200 = datetime.datetime(2026, 10, 1, 12, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    created_later = await poll_single(updated_wl, test_store, tasks_dict, listeners_dict, now=t_1200)
    assert created_later == []

    # Next day before slot (07:59 UTC) -> does not fire
    t_day2_before = datetime.datetime(2026, 10, 2, 7, 59, 0, tzinfo=datetime.timezone.utc).timestamp()
    created_day2_before = await poll_single(get_watchlist(wl["id"]), test_store, tasks_dict, listeners_dict, now=t_day2_before)
    assert created_day2_before == []

    # Next day at slot (08:00 UTC) with 2 fresh articles -> fires once!
    rss_day2 = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Tech Dispatch</title>
        <item><title>Article Delta</title><link>https://example.com/delta</link></item>
        <item><title>Article Epsilon</title><link>https://example.com/epsilon</link></item>
      </channel>
    </rss>
    """
    monkeypatch.setattr("vozonda_api.watchlist_poller.fetch_feed_text", lambda u: asyncio.sleep(0, result=rss_day2))
    t_day2_at = datetime.datetime(2026, 10, 2, 8, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    created_day2_at = await poll_single(get_watchlist(wl["id"]), test_store, tasks_dict, listeners_dict, now=t_day2_at)
    assert len(created_day2_at) == 1
    assert created_day2_at[0] != job_id
    assert get_watchlist(wl["id"])["last_scheduled_run"] == t_day2_at


@pytest.mark.asyncio
async def test_repeated_polls_inside_slot_do_not_fire_twice(test_db, monkeypatch):
    """Multiple poll ticks inside the same slot window fire only once."""
    monkeypatch.setattr("vozonda_api.watchlist_poller.fetch_feed_text", lambda u: asyncio.sleep(0, result=SAMPLE_RSS_3))

    tasks_dict: dict = {}
    listeners_dict: dict = {}
    test_store = JobStore()

    wl = create_watchlist("https://example.com/feed-rep.xml", schedule="daily@08:00", schedule_tz="UTC")

    t_slot_00 = datetime.datetime(2026, 10, 1, 8, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    t_slot_15 = datetime.datetime(2026, 10, 1, 8, 0, 15, tzinfo=datetime.timezone.utc).timestamp()
    t_slot_30 = datetime.datetime(2026, 10, 1, 8, 0, 30, tzinfo=datetime.timezone.utc).timestamp()
    t_slot_59 = datetime.datetime(2026, 10, 1, 8, 0, 59, tzinfo=datetime.timezone.utc).timestamp()

    # First tick inside slot: fires
    created = await poll_single(wl, test_store, tasks_dict, listeners_dict, now=t_slot_00)
    assert len(created) == 1

    # Ticks 15s, 30s, 59s later: do NOT fire
    for tick in (t_slot_15, t_slot_30, t_slot_59):
        curr_wl = get_watchlist(wl["id"])
        res = await poll_single(curr_wl, test_store, tasks_dict, listeners_dict, now=tick)
        assert res == [], f"Should not fire at tick {tick}"


@pytest.mark.asyncio
async def test_weekly_only_on_its_weekday(test_db, monkeypatch):
    """Weekly schedule only fires on its configured weekday at the scheduled time."""
    monkeypatch.setattr("vozonda_api.watchlist_poller.fetch_feed_text", lambda u: asyncio.sleep(0, result=SAMPLE_RSS_3))

    tasks_dict: dict = {}
    listeners_dict: dict = {}
    test_store = JobStore()

    # Scheduled for Friday at 18:00 UTC
    wl = create_watchlist("https://example.com/feed-weekly.xml", schedule="weekly@fri@18:00", schedule_tz="UTC")

    # 2026-10-05 (Monday) 18:00
    t_mon = datetime.datetime(2026, 10, 5, 18, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    # Set created_at to simulated time so the watchlist is "new" in the simulated timeline
    update_watchlist(wl["id"])
    with jobs_mod._conn() as c:
        c.execute("UPDATE watchlist SET created_at = ? WHERE id = ?", (t_mon, wl["id"]))
    wl = get_watchlist(wl["id"])  # refresh with updated created_at
    res = await poll_single(wl, test_store, tasks_dict, listeners_dict, now=t_mon)
    assert res == []

    # 2026-10-08 (Thursday) 18:00
    t_thu = datetime.datetime(2026, 10, 8, 18, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    res = await poll_single(get_watchlist(wl["id"]), test_store, tasks_dict, listeners_dict, now=t_thu)
    assert res == []

    # 2026-10-09 (Friday) 17:59
    t_fri_before = datetime.datetime(2026, 10, 9, 17, 59, 0, tzinfo=datetime.timezone.utc).timestamp()
    res = await poll_single(get_watchlist(wl["id"]), test_store, tasks_dict, listeners_dict, now=t_fri_before)
    assert res == []

    # 2026-10-09 (Friday) 18:00: FIRES!
    t_fri_at = datetime.datetime(2026, 10, 9, 18, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    res = await poll_single(get_watchlist(wl["id"]), test_store, tasks_dict, listeners_dict, now=t_fri_at)
    assert len(res) == 1
    assert res[0].startswith("digest-")

    # 2026-10-09 (Friday) 18:10: does not fire again
    t_fri_after = datetime.datetime(2026, 10, 9, 18, 10, 0, tzinfo=datetime.timezone.utc).timestamp()
    res = await poll_single(get_watchlist(wl["id"]), test_store, tasks_dict, listeners_dict, now=t_fri_after)
    assert res == []

    # 2026-10-10 (Saturday) 18:00: does not fire
    t_sat = datetime.datetime(2026, 10, 10, 18, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    res = await poll_single(get_watchlist(wl["id"]), test_store, tasks_dict, listeners_dict, now=t_sat)
    assert res == []


@pytest.mark.asyncio
async def test_missed_run_catch_up_fires_once(test_db, monkeypatch):
    """A run missed while service was down fires once on next poll, not repeatedly."""
    monkeypatch.setattr("vozonda_api.watchlist_poller.fetch_feed_text", lambda u: asyncio.sleep(0, result=SAMPLE_RSS_3))

    tasks_dict: dict = {}
    listeners_dict: dict = {}
    test_store = JobStore()

    # Watchlist created yesterday, scheduled for daily@08:00
    t_yesterday = datetime.datetime(2026, 9, 30, 12, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    wl = create_watchlist("https://example.com/feed-missed.xml", schedule="daily@08:00", schedule_tz="UTC")
    # Manually simulate created_at in the past
    update_watchlist(wl["id"])
    with jobs_mod._conn() as c:
        c.execute("UPDATE watchlist SET created_at = ? WHERE id = ?", (t_yesterday, wl["id"]))

    # Service was down during 08:00 on Oct 1.
    # Service restarts at 11:30 UTC: first poll catches up!
    t_1130 = datetime.datetime(2026, 10, 1, 11, 30, 0, tzinfo=datetime.timezone.utc).timestamp()
    curr_wl = get_watchlist(wl["id"])
    created = await poll_single(curr_wl, test_store, tasks_dict, listeners_dict, now=t_1130)
    assert len(created) == 1
    assert created[0].startswith("digest-")

    # last_scheduled_run recorded
    updated_wl = get_watchlist(wl["id"])
    assert updated_wl["last_scheduled_run"] == t_1130

    # Next poll at 11:40 UTC: does NOT fire again
    t_1140 = datetime.datetime(2026, 10, 1, 11, 40, 0, tzinfo=datetime.timezone.utc).timestamp()
    created_next = await poll_single(updated_wl, test_store, tasks_dict, listeners_dict, now=t_1140)
    assert created_next == []

    # Poll at 12:00 UTC: does NOT fire again
    t_1200 = datetime.datetime(2026, 10, 1, 12, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    created_noon = await poll_single(get_watchlist(wl["id"]), test_store, tasks_dict, listeners_dict, now=t_1200)
    assert created_noon == []


@pytest.mark.asyncio
async def test_no_new_entries_no_episode_one_log_line(test_db, monkeypatch, capsys):
    """At scheduled time with no fresh entries: no episode, one log line, last_scheduled_run recorded."""
    monkeypatch.setattr("vozonda_api.watchlist_poller.fetch_feed_text", lambda u: asyncio.sleep(0, result=SAMPLE_RSS_EMPTY))

    tasks_dict: dict = {}
    listeners_dict: dict = {}
    test_store = JobStore()

    wl = create_watchlist("https://example.com/feed-empty.xml", schedule="daily@08:00", schedule_tz="UTC")
    t_at = datetime.datetime(2026, 10, 1, 8, 0, 0, tzinfo=datetime.timezone.utc).timestamp()

    created = await poll_single(wl, test_store, tasks_dict, listeners_dict, now=t_at)
    assert created == []

    # Log line emitted
    captured = capsys.readouterr()
    assert "[watchlist-schedule]" in captured.out
    assert "no entries" in captured.out or "no new entries" in captured.out

    # last_scheduled_run is recorded so it won't repeatedly poll inside the slot
    updated_wl = get_watchlist(wl["id"])
    assert updated_wl["last_scheduled_run"] == t_at

    # Repeated poll inside slot does not fire
    t_after = datetime.datetime(2026, 10, 1, 8, 5, 0, tzinfo=datetime.timezone.utc).timestamp()
    res = await poll_single(updated_wl, test_store, tasks_dict, listeners_dict, now=t_after)
    assert res == []


@pytest.mark.asyncio
async def test_no_schedule_path_still_renders_per_entry(test_db, monkeypatch):
    """Without a schedule, the poller renders entries individually as they arrive."""
    # 2 articles in feed
    rss_feed = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Regular Feed</title>
        <item><title>Item 1</title><link>https://example.com/item1</link></item>
        <item><title>Item 2</title><link>https://example.com/item2</link></item>
      </channel>
    </rss>
    """
    monkeypatch.setattr("vozonda_api.watchlist_poller.fetch_feed_text", lambda u: asyncio.sleep(0, result=rss_feed))
    # Catchup mode to allow rendering all new entries
    monkeypatch.setattr("vozonda_api.settings_store.get_setting", lambda k: "catchup" if k == "watchlist.render_mode" else None)

    tasks_dict: dict = {}
    listeners_dict: dict = {}
    test_store = JobStore()

    # Create watchlist WITHOUT schedule
    wl = create_watchlist("https://example.com/feed-nosched.xml")
    assert wl["schedule"] is None

    created = await poll_single(wl, test_store, tasks_dict, listeners_dict)
    # Should render both entries individually, not as a digest
    assert len(created) == 2
    for job_id in created:
        assert not job_id.startswith("digest-")
        job = test_store.get(job_id)
        assert job["digest"] == 0 or not job.get("digest")


@pytest.mark.asyncio
async def test_digest_count_respected(test_db, monkeypatch):
    """Scheduled digest caps sources to watchlist digest_count."""
    # Feed with 5 entries
    rss_feed = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Lots of Articles</title>
        <item><title>1</title><link>https://example.com/1</link></item>
        <item><title>2</title><link>https://example.com/2</link></item>
        <item><title>3</title><link>https://example.com/3</link></item>
        <item><title>4</title><link>https://example.com/4</link></item>
        <item><title>5</title><link>https://example.com/5</link></item>
      </channel>
    </rss>
    """
    monkeypatch.setattr("vozonda_api.watchlist_poller.fetch_feed_text", lambda u: asyncio.sleep(0, result=rss_feed))

    tasks_dict: dict = {}
    listeners_dict: dict = {}
    test_store = JobStore()

    wl = create_watchlist("https://example.com/feed-count.xml", schedule="daily@08:00", schedule_tz="UTC")
    update_watchlist(wl["id"], digest_count=2)
    wl = get_watchlist(wl["id"])

    t_at = datetime.datetime(2026, 10, 1, 8, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    created = await poll_single(wl, test_store, tasks_dict, listeners_dict, now=t_at)
    assert len(created) == 1
    job = test_store.get(created[0])
    assert len(job["digest_sources"]) == 2

# ---------------------------------------------------------------------------
# Regression tests for the coordinator + muse review of 58b18da (VOZONDA-SCHEDULE-FIX).
# Each one fails on 58b18da.
# ---------------------------------------------------------------------------


def _utc(day: int, hour: int, minute: int = 0) -> float:
    return datetime.datetime(2026, 10, day, hour, minute, 0, tzinfo=datetime.timezone.utc).timestamp()


@pytest.mark.asyncio
async def test_unchanged_feed_is_not_bundled_again_the_next_day(test_db, monkeypatch):
    """Bug 1: digested entries live in digest_sources, not in jobs.url; they must count as rendered."""
    async def mock_fetch(url):
        return SAMPLE_RSS_3

    monkeypatch.setattr("vozonda_api.watchlist_poller.fetch_feed_text", mock_fetch)
    store, tasks, listeners = JobStore(), {}, {}
    wl = create_watchlist("https://example.com/feed-twice.xml", schedule="daily@08:00", schedule_tz="UTC")

    first = await poll_single(wl, store, tasks, listeners, now=_utc(1, 8))
    assert len(first) == 1
    wl = get_watchlist(wl["id"])
    second = await poll_single(wl, store, tasks, listeners, now=_utc(2, 8))
    assert second == []


@pytest.mark.asyncio
async def test_schedule_set_later_waits_for_the_next_slot(test_db, monkeypatch):
    """Bug 3 / F-5: a schedule set at 15:00 for daily@08:00 fires at 08:00 the next day, not on the next poll."""
    async def mock_fetch(url):
        return SAMPLE_RSS_3

    monkeypatch.setattr("vozonda_api.watchlist_poller.fetch_feed_text", mock_fetch)
    store, tasks, listeners = JobStore(), {}, {}
    wl = create_watchlist("https://example.com/feed-later.xml")
    import vozonda_api.watchlist as watchlist_mod

    monkeypatch.setattr(watchlist_mod.time, "time", lambda: _utc(1, 15))
    update_watchlist(wl["id"], schedule="daily@08:00", schedule_tz="UTC")
    wl = get_watchlist(wl["id"])

    assert await poll_single(wl, store, tasks, listeners, now=_utc(1, 15, 5)) == []
    assert len(await poll_single(wl, store, tasks, listeners, now=_utc(2, 8))) == 1


def test_weekly_missed_slot_caught_up_on_the_weekday_before_the_slot_time():
    """Bug 4: Thursday 07:00, last run two weeks ago: last Thursday's slot was missed and fires now."""
    assert datetime.date(2026, 10, 1).weekday() == 3  # Thursday
    last_run = _utc(1, 8) - 14 * 86400
    assert is_schedule_due("weekly@thu@08:00", "UTC", last_run, _utc(1, 7)) is True


@pytest.mark.asyncio
async def test_failed_fetch_at_the_slot_is_retried_on_the_next_poll(test_db, monkeypatch):
    """F-2: a fetch failure must not consume the slot."""
    from vozonda_api.fetcher import FetchError

    calls = {"n": 0}

    async def flaky_fetch(url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FetchError("temporary outage")
        return SAMPLE_RSS_3

    monkeypatch.setattr("vozonda_api.watchlist_poller.fetch_feed_text", flaky_fetch)
    store, tasks, listeners = JobStore(), {}, {}
    wl = create_watchlist("https://example.com/feed-flaky.xml", schedule="daily@08:00", schedule_tz="UTC")

    assert await poll_single(wl, store, tasks, listeners, now=_utc(1, 8)) == []
    wl = get_watchlist(wl["id"])
    assert len(await poll_single(wl, store, tasks, listeners, now=_utc(1, 8, 10))) == 1


@pytest.mark.asyncio
async def test_manual_check_on_a_scheduled_watchlist_starts_a_digest(test_db, monkeypatch):
    """F-3: 'check now' off-slot forces one digest instead of an unexplained empty list."""
    async def mock_fetch(url):
        return SAMPLE_RSS_3

    monkeypatch.setattr("vozonda_api.watchlist_poller.fetch_feed_text", mock_fetch)
    store, tasks, listeners = JobStore(), {}, {}
    wl = create_watchlist("https://example.com/feed-manual.xml", schedule="daily@08:00", schedule_tz="UTC")
    assert len(await poll_single(wl, store, tasks, listeners, now=_utc(1, 7), is_manual=True)) == 1
