"""PUT /shows/current was dead and wrong: it wrote the slug into show.name."""

from fastapi.testclient import TestClient

from vozonda_api.main import app


def test_shows_current_route_is_gone():
    client = TestClient(app)
    r = client.put("/shows/current", json={"name": "probe"})
    assert r.status_code in (404, 405), r.status_code


def test_no_shows_current_route_registered():
    paths = [route.path for route in app.routes if hasattr(route, "path")]
    assert "/shows/current" not in paths
