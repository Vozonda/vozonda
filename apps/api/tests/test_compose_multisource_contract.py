"""Contract test for VOZONDA-UX-1: compose multi-source digest.

The compose UI sends digest=true with digest_sources when 2-10 sources
are collected, and a plain url body for a single source. This pins the
API side of that contract: POST /jobs accepts the 3-source digest body
and still accepts the 1-source url body. The pipeline is monkeypatched
so nothing renders.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from vozonda_api import main
from vozonda_api.main import app


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient with the render pipeline stubbed out."""

    async def fake_run_job(store: Any, job_id: str):
        job = store.get(job_id)
        yield job

    monkeypatch.setattr(main, "run_job", fake_run_job)
    return TestClient(app)


def test_three_sources_send_as_digest(client: TestClient) -> None:
    """A body shaped like the UI's 3-source payload is accepted as a digest."""
    body = {
        "digest": True,
        "digest_sources": [
            "https://example.com/article-one",
            "https://example.com/article-two",
            "https://example.com/article-three",
        ],
        "style": "balanced",
        "format": "dialog",
        "language": "auto",
        "hosts": 2,
    }
    resp = client.post("/jobs", json=body)
    assert resp.status_code == 200, resp.text
    job = resp.json()
    assert job["digest"] is True
    assert job["digest_sources"] == body["digest_sources"]
    assert job["url"].startswith("digest:")


def test_single_source_still_uses_url(client: TestClient) -> None:
    """A 1-source body keeps the classic url path (no digest)."""
    body = {
        "url": "https://example.com/just-one-article",
        "style": "balanced",
        "format": "dialog",
        "language": "auto",
        "hosts": 2,
    }
    resp = client.post("/jobs", json=body)
    assert resp.status_code == 200, resp.text
    job = resp.json()
    assert job["url"] == "https://example.com/just-one-article"
    assert not job.get("digest")
