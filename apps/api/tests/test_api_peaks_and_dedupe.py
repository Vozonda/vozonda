
from fastapi.testclient import TestClient


def test_list_jobs_dedupes_done_by_url(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    store = jobs_mod.JobStore()
    # three done jobs, two share url
    store.create("dup-a", "https://example.com/a")
    store.finish("dup-a")
    # ensure different created_at ordering: sleep a bit
    import time

    time.sleep(0.01)
    store.create("dup-b", "https://example.com/a")
    store.finish("dup-b")
    time.sleep(0.01)
    store.create("uniq", "https://example.com/b")
    store.finish("uniq")

    client = TestClient(main_mod.app)
    res = client.get("/jobs?limit=10")
    assert res.status_code == 200
    data = res.json()
    ids = [j["id"] for j in data["jobs"] if j["state"] == "done"]
    # deduped: most recent per url kept, so dup-a hidden
    assert len(ids) == 2
    assert "dup-b" in ids
    assert "uniq" in ids
    assert "dup-a" not in ids


def test_list_jobs_keeps_failed_duplicates(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    store = jobs_mod.JobStore()
    store.create("fail-a", "https://example.com/c")
    store.fail("fail-a", "fetch", "boom")
    store.create("fail-b", "https://example.com/c")
    store.fail("fail-b", "fetch", "boom2")

    client = TestClient(main_mod.app)
    res = client.get("/jobs?limit=10")
    assert res.status_code == 200
    failed_ids = [j["id"] for j in res.json()["jobs"] if j["state"] == "failed"]
    # failed not deduped
    assert len(failed_ids) == 2
    assert "fail-a" in failed_ids
    assert "fail-b" in failed_ids


def test_peaks_put_and_get(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod  # noqa: F401 - ensure env isolation
    import vozonda_api.main as main_mod
    import vozonda_api.providers as prov

    monkeypatch.setattr(prov, "MEDIA_DIR", tmp_path / "media")
    monkeypatch.setattr(main_mod, "MEDIA_DIR", tmp_path / "media")
    (tmp_path / "media").mkdir(parents=True, exist_ok=True)

    client = TestClient(main_mod.app)
    peaks = [0.1 * i for i in range(160)]
    # missing before put -> 404
    assert client.get("/audio/test123.peaks.json").status_code == 404
    # put
    res = client.put("/audio/test123.peaks.json", json={"peaks": peaks, "duration": 42.5, "bars": 160})
    assert res.status_code == 200
    assert res.json()["peaks"] == 160
    # get
    res2 = client.get("/audio/test123.peaks.json")
    assert res2.status_code == 200
    data = res2.json()
    assert data["peaks"] == peaks
    assert data["duration"] == 42.5
    # invalid put -> 422
    assert client.put("/audio/test123.peaks.json", json={"peaks": []}).status_code == 422
    assert client.put("/audio/test123.peaks.json", json={"peaks": "bad"}).status_code == 422
