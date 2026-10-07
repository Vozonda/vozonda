import pytest  # noqa: F401
from fastapi.testclient import TestClient


def test_source_serves_pasted_text_and_redirects_urls(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    store = jobs_mod.JobStore()
    store.create("ep-url", "https://example.com/article")
    store.finish("ep-url")
    pasted = "Prolog: Der Takt des Profits\n\nDie Nachtschicht in der Fabrik."
    store.create("ep-txt", pasted)
    store.finish("ep-txt")

    client = TestClient(main_mod.app)

    res = client.get("/source/ep-url", follow_redirects=False)
    assert res.status_code in (301, 302, 307, 308)
    assert res.headers["location"] == "https://example.com/article"

    res = client.get("/source/ep-txt", follow_redirects=False)
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    assert res.text == pasted

    assert client.get("/source/nope").status_code == 404
