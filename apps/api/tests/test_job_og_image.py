"""JobStore.update stores the episode cover (2026-10-02).

Five callers passed og_image (downloaded og:image, generated cover, upload); update()
had no such parameter, so each call raised a TypeError that was only logged, and no
episode ever stored its cover although the files were on disk."""
from vozonda_api.jobs import JobStore


def test_update_stores_and_returns_the_cover():
    store = JobStore()
    store.create("og-test-1", "https://example.com/a")
    store.update("og-test-1", og_image="og-test-1-cover.png")
    assert store.get("og-test-1")["og_image"] == "og-test-1-cover.png"


def test_update_stores_the_audio_length_apart_from_the_render_time():
    """The library showed duration_ms (render time) as the episode length."""
    store = JobStore()
    store.create("len-test-1", "https://example.com/b")
    store.update("len-test-1", duration_ms=409000, audio_seconds=231.9)
    job = store.get("len-test-1")
    assert job["audio_seconds"] == 231.9 and job["duration_ms"] == 409000


def test_the_job_list_carries_cover_and_audio_length(tmp_path, monkeypatch):
    """The library reads both from GET /jobs, which builds its rows by hand."""
    from fastapi.testclient import TestClient

    import vozonda_api.jobs as jobs_mod
    from vozonda_api.main import app

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    jobs_mod.init_db()
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    store = JobStore()
    store.create("list-1", "https://example.com/c")
    store.update("list-1", state="done", og_image="list-1-og.png", audio_seconds=180.5, duration_ms=400000)
    row = next(j for j in TestClient(app).get("/jobs?limit=5").json()["jobs"] if j["id"] == "list-1")
    assert row["og_image"] == "list-1-og.png" and row["audio_seconds"] == 180.5
