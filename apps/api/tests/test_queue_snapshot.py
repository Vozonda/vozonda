"""Tests for _queue_snapshot ahead_title and ahead_count (VOZONDA-QUEUE-1)."""

import pytest

from vozonda_api.jobs import JobStore, _conn, init_db


@pytest.fixture(autouse=True)
def clean_db():
    """Clear the jobs table before each test."""
    with _conn() as c:
        init_db()
        c.execute("DELETE FROM jobs")
    yield
    with _conn() as c:
        c.execute("DELETE FROM jobs")


@pytest.fixture()
def store() -> JobStore:
    return JobStore()


def test_queue_snapshot_ahead_title_for_one_running_job(store: JobStore) -> None:
    # Create a running job
    running = store.create("t-qs-run-1", "http://example.com/running")
    store.set_stage_running("t-qs-run-1", "fetch")
    store.update("t-qs-run-1", title="Running Episode Title")

    # Create a queued job behind it
    queued = store.create("t-qs-queued-1", "http://example.com/queued")
    qs = store.queue_info("t-qs-queued-1")

    assert qs["queue_position"] == 1
    assert qs["queue_length"] == 1
    assert qs["ahead_count"] == 0  # position 1 means no jobs ahead in queue
    assert qs["ahead_title"] == "Running Episode Title"


def test_queue_snapshot_ahead_count_with_two_ahead(store: JobStore) -> None:
    # Create a running job
    running = store.create("t-qs-run-2", "http://example.com/running")
    store.set_stage_running("t-qs-run-2", "fetch")
    store.update("t-qs-run-2", title="Running Episode")

    # Create first queued job
    queued1 = store.create("t-qs-queued-2a", "http://example.com/queued1")
    # Create second queued job (our test job)
    queued2 = store.create("t-qs-queued-2b", "http://example.com/queued2")

    qs = store.queue_info("t-qs-queued-2b")

    assert qs["queue_position"] == 2
    assert qs["queue_length"] == 2
    assert qs["ahead_count"] == 1  # one job ahead in queue
    assert qs["ahead_title"] == "Running Episode"


def test_queue_snapshot_billing_mode_hides_title(store: JobStore, monkeypatch) -> None:
    # Enable billing mode
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")

    # Create a running job with a different user
    running = store.create("t-qs-run-3", "http://example.com/running", user_id="user-1")
    store.set_stage_running("t-qs-run-3", "fetch")
    store.update("t-qs-run-3", title="Private Episode Title")

    # Create a queued job for a different user
    queued = store.create("t-qs-queued-3", "http://example.com/queued", user_id="user-2")
    qs = store.queue_info("t-qs-queued-3")

    assert qs["queue_position"] == 1
    assert qs["ahead_count"] == 0
    assert qs["ahead_title"] is None  # hidden in billing mode


def test_queue_snapshot_no_running_job_returns_none_ahead(store: JobStore) -> None:
    # Only queued jobs, nothing running
    queued1 = store.create("t-qs-queued-4a", "http://example.com/queued1")
    queued2 = store.create("t-qs-queued-4b", "http://example.com/queued2")

    qs = store.queue_info("t-qs-queued-4b")

    assert qs["queue_position"] == 2
    assert qs["ahead_count"] == 1
    assert qs["ahead_title"] is None


def test_queue_snapshot_running_job_returns_zero_position(store: JobStore) -> None:
    running = store.create("t-qs-run-5", "http://example.com/running")
    store.set_stage_running("t-qs-run-5", "fetch")
    qs = store.queue_info("t-qs-run-5")

    assert qs["queue_position"] == 0
    assert qs["ahead_count"] == 0
    assert qs["ahead_title"] is None


def test_queue_snapshot_done_job_returns_none_position(store: JobStore) -> None:
    done = store.create("t-qs-done-6", "http://example.com/done")
    store.finish("t-qs-done-6")
    qs = store.queue_info("t-qs-done-6")

    assert qs["queue_position"] is None
    assert qs["ahead_count"] == 0
    assert qs["ahead_title"] is None


def test_queue_snapshot_billing_mode_shows_title_for_same_user(store: JobStore, monkeypatch) -> None:
    # Enable billing mode
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")

    # Create a running job with same user
    running = store.create("t-qs-run-7", "http://example.com/running", user_id="user-1")
    store.set_stage_running("t-qs-run-7", "fetch")
    store.update("t-qs-run-7", title="My Episode Title")

    # Create a queued job for the SAME user
    queued = store.create("t-qs-queued-7", "http://example.com/queued", user_id="user-1")
    qs = store.queue_info("t-qs-queued-7")

    assert qs["queue_position"] == 1
    assert qs["ahead_count"] == 0
    assert qs["ahead_title"] == "My Episode Title"  # visible for same user