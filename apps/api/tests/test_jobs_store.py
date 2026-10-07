import time as _time

import pytest

from vozonda_api.jobs import STAGES, JobStore


@pytest.fixture()
def store() -> JobStore:
    return JobStore()


def test_create_returns_queued_with_pending_stages(store: JobStore) -> None:
    job = store.create("t-create", "http://example.com/a")
    assert job["state"] == "queued"
    assert job["current_stage"] is None
    assert [s["name"] for s in job["stages"]] == STAGES
    assert all(s["status"] == "pending" for s in job["stages"])
    assert job["style"] == "default"
    assert job["format"] == "dialog"
    assert job["tone"] == "neutral"
    assert job["language"] == "auto"


def test_get_unknown_raises_keyerror(store: JobStore) -> None:
    with pytest.raises(KeyError):
        store.get("missing-job")


def test_stage_lifecycle_records_timing(store: JobStore) -> None:
    store.create("t-life", "http://example.com/b")
    running = store.set_stage_running("t-life", "fetch")
    assert running["state"] == "running"
    assert running["current_stage"] == "fetch"
    fetch = next(s for s in running["stages"] if s["name"] == "fetch")
    assert fetch["status"] == "running"
    assert "_t0" in fetch

    _time.sleep(0.01)
    done = store.set_stage_done("t-life", "fetch")
    fetch = next(s for s in done["stages"] if s["name"] == "fetch")
    assert fetch["status"] == "done"
    assert fetch["ms"] >= 0
    assert "_t0" not in fetch
    store.finish("t-life")


def test_fail_marks_stage_and_strips_html(store: JobStore) -> None:
    store.create("t-fail", "http://example.com/c")
    store.set_stage_running("t-fail", "script")
    failed = store.fail("t-fail", "script", "<b>boom</b> " + "x" * 300)
    assert failed["state"] == "failed"
    assert failed["error"].startswith("boom")
    assert len(failed["error"]) <= 200
    assert "<b>" not in failed["error"]
    script = next(s for s in failed["stages"] if s["name"] == "script")
    assert script["status"] == "failed"
    assert script["detail"] == failed["error"]


def test_finish_sets_done(store: JobStore) -> None:
    store.create("t-done", "http://example.com/d")
    assert store.finish("t-done")["state"] == "done"


def test_update_persists_title_and_script(store: JobStore) -> None:
    store.create("t-upd", "http://example.com/e")
    updated = store.update(
        "t-upd", title="Hello", script=[{"speaker": "A", "text": "hi"}]
    )
    again = store.get("t-upd")
    assert again["title"] == "Hello"
    assert again["script"] == [{"speaker": "A", "text": "hi"}]
    assert updated["title"] == "Hello"


def test_fail_interrupted_marks_running_job_at_current_stage(store: JobStore) -> None:
    store.fail_interrupted()
    store.create("t-int-run", "http://example.com/f")
    store.set_stage_running("t-int-run", "voice")
    out = [j for j in store.fail_interrupted() if j["id"] == "t-int-run"]
    assert len(out) == 1
    job = store.get("t-int-run")
    assert job["state"] == "failed"
    assert job["current_stage"] == "voice"
    assert job["error"] == "interrupted"
    voice = next(s for s in job["stages"] if s["name"] == "voice")
    assert voice["status"] == "failed"


def test_fail_interrupted_fails_queued_job_without_touching_stages(
    store: JobStore,
) -> None:
    store.fail_interrupted()
    store.create("t-int-queued", "http://example.com/g")
    out = [j for j in store.fail_interrupted() if j["id"] == "t-int-queued"]
    assert len(out) == 1
    job = store.get("t-int-queued")
    assert job["state"] == "failed"
    assert job["error"] == "interrupted"
    assert all(s["status"] == "pending" for s in job["stages"])


def test_fail_interrupted_leaves_terminal_jobs_alone(store: JobStore) -> None:
    store.fail_interrupted()
    store.create("t-int-done", "http://example.com/h")
    store.finish("t-int-done")
    before = store.get("t-int-done")
    out = [j for j in store.fail_interrupted() if j["id"] == "t-int-done"]
    assert out == []
    assert store.get("t-int-done") == before
