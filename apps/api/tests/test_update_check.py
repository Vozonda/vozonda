"""Update notice: /update-check compares the running version with the latest GitHub release."""
import asyncio

import pytest


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    import vozonda_api.updates as up

    up._cache.update(at=0.0, release=None)
    monkeypatch.setattr(up, "BASE_VERSION", "0.7.1")
    monkeypatch.setattr(up, "enabled", lambda: True)


def _release(monkeypatch, tag, body=""):
    import vozonda_api.updates as up

    async def fake():
        return {"tag": tag, "url": f"https://github.com/Vozonda/vozonda/releases/tag/{tag}", "body": body}

    monkeypatch.setattr(up, "_latest", fake)


def test_newer_security_release_is_offered(monkeypatch):
    import vozonda_api.updates as up

    _release(monkeypatch, "v0.7.2", "## 0.7.2\n\n### Security\n\n- remote access needs the token")
    out = asyncio.run(up.check())
    assert out["available"] and out["latest"] == "0.7.2" and out["security"] is True
    assert out["command"] == "git pull && docker compose up -d --build"


def test_same_or_older_release_is_not_offered(monkeypatch):
    import vozonda_api.updates as up

    for tag in ("v0.7.1", "v0.6.9", "v0.7.0"):
        _release(monkeypatch, tag)
        assert asyncio.run(up.check())["available"] is False


def test_minor_and_major_compare_numerically(monkeypatch):
    import vozonda_api.updates as up

    _release(monkeypatch, "v0.10.0")
    assert asyncio.run(up.check())["available"] is True


def test_check_can_be_turned_off(monkeypatch):
    import vozonda_api.updates as up

    monkeypatch.setattr(up, "enabled", lambda: False)
    called = []

    async def fake():
        called.append(1)

    monkeypatch.setattr(up, "_latest", fake)
    assert asyncio.run(up.check()) == {"current": "0.7.1", "enabled": False, "available": False}
    assert called == []  # no request to GitHub at all


def test_failed_check_is_silent(monkeypatch):
    import vozonda_api.updates as up

    async def fake():
        pass

    monkeypatch.setattr(up, "_latest", fake)
    assert asyncio.run(up.check())["available"] is False


def test_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    import vozonda_api.main as main_mod

    _release(monkeypatch, "v0.8.0")
    res = TestClient(main_mod.app).get("/update-check")
    assert res.status_code == 200 and res.json()["latest"] == "0.8.0"
