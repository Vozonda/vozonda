"""Share pages must link to the install's own address, never a hardcoded domain.

Self-hosters share /e/<id> links; with APP_URL hardcoded to vozonda.sovgrid.org
(a name still TBC) every OG tag and canonical link pointed at our domain."""
import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

_JOB = {
    "id": "pub-job-1", "title": "Test Episode", "state": "done",
    "url": "https://example.com/article", "script": [{"speaker": "A", "text": "Hello"}],
    "stages": [], "created_at": 1700000000, "duration_ms": 120000,
    "show_name": "Test Show", "language": "en", "og_image": None, "digest_sources": None,
}


def _page(monkeypatch, env_url):
    import vozonda_api.main as main_module

    if env_url is None:
        monkeypatch.delenv("VOZONDA_PUBLIC_URL", raising=False)
    else:
        monkeypatch.setenv("VOZONDA_PUBLIC_URL", env_url)
    store = MagicMock()
    store.get.return_value = json.loads(json.dumps(_JOB))
    client = TestClient(main_module.app, base_url="http://podcasts.example.org")
    with patch.object(main_module, "store", store), \
            patch("vozonda_api.settings_store.get_setting", return_value=None):
        r = client.get("/e/pub-job-1")
    assert r.status_code == 200
    return r.text


def test_share_page_uses_request_host_without_config(monkeypatch):
    text = _page(monkeypatch, None)
    assert "vozonda.sovgrid.org" not in text
    assert "http://podcasts.example.org/" in text


def test_share_page_prefers_vozonda_public_url(monkeypatch):
    text = _page(monkeypatch, "https://pods.mydomain.net/")
    assert "vozonda.sovgrid.org" not in text
    assert "https://pods.mydomain.net/" in text
    assert "https://pods.mydomain.net//" not in text


def test_no_hardcoded_app_domain_left_in_api_source():
    from pathlib import Path

    import vozonda_api

    src = Path(vozonda_api.__file__).parent
    hits = [str(p) for p in src.rglob("*.py") if "vozonda.sovgrid.org" in p.read_text()]
    assert hits == []
