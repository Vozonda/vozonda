"""Security audit 2026-10 fixes — one test per finding.

Each test is written so that it FAILS against the unfixed code
and PASSES after applying the listed fix.
"""

from fastapi.testclient import TestClient

from vozonda_api.main import app

# ── F-5: /audio/{filename:path}.mp3 path traversal ──────────────────

def test_f5_audio_traversal_rejected(monkeypatch):
    """Traversal like ../../etc/passwd.mp3 must NOT leak a file."""
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    client = TestClient(app)
    r = client.get("/audio/../../../../etc/passwd.mp3")
    assert r.status_code in (403, 404)


# ── F-6: /audio/{job_id}.peaks.json path traversal ──────────────────

def test_f6_peaks_traversal_rejected(monkeypatch):
    """Traversal like ../data/jobs.peaks.json must NOT leak a file."""
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    client = TestClient(app)
    r = client.get("/audio/../../data/jobs.peaks.json")
    assert r.status_code in (403, 404)


# ── F-2 / F-3: /llm/probe unauthenticated ──────────────────────────

def test_f2_f3_probe_requires_write_auth(monkeypatch):
    """Unauthenticated GET /llm/probe must return 401 (F-3)."""
    monkeypatch.setenv("VOZONDA_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get("/llm/probe", params={"engine": "custom", "custom_base": "http://127.0.0.1:11434/"})
    assert r.status_code == 401


# ── F-1: callback_url blocked at registration ──────────────────────

def test_f1_callback_url_private_rejected(monkeypatch):
    """A private/metadata callback_url must be rejected at POST /jobs."""
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    client = TestClient(app)
    r = client.post("/jobs", json={
        "url": "https://example.com/article",
        "callback_url": "http://169.254.169.254/latest/meta-data/",
    })
    assert r.status_code == 422


def test_f1_callback_url_localhost_rejected(monkeypatch):
    """A localhost callback_url must also be rejected at POST /jobs."""
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    client = TestClient(app)
    r = client.post("/jobs", json={
        "url": "https://example.com/article",
        "callback_url": "http://127.0.0.1:8787/webhook",
    })
    assert r.status_code == 422


# ── F-4: exception text not leaked ─────────────────────────────────

def test_f4_no_exception_leak(monkeypatch):
    """An invalid access token must not echo the billing exception."""
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
    monkeypatch.setenv("VOZONDA_TOKEN", "s3cret")
    client = TestClient(app)

    def fake_validate(token):
        raise ValueError("internal-db-conn://billing:5432/details")

    # Patch the billing module so validate_token always fails with detail
    import vozonda_api.billing as _billing
    monkeypatch.setattr(_billing, "validate_token", fake_validate)

    r = client.post("/jobs", json={
        "url": "https://example.com/article",
        "access_token": "bad-token-xyz",
    })
    assert r.status_code == 401
    body = r.text
    assert "internal-db-conn" not in body
    assert "billing:5432" not in body
    assert "details" not in body


# ── F-11: _discover_links guards internal links ────────────────────

def test_f11_discover_links_blocks_internal_urls():
    """Private/internal URLs in article links must be filtered out."""
    from vozonda_api.pipeline import _discover_links

    html = """
    <html><body>
    <article>
      <a href="https://example.com/valid">a valid internal link with enough text</a>
      <a href="http://127.0.0.1:8787/secret">a localhost link with enough text</a>
      <a href="http://169.254.169.254/latest/meta-data">the metadata service link</a>
      <a href="http://10.0.0.5/admin">private ip link with enough words</a>
    </article>
    </body></html>
    """
    links = _discover_links(html, "https://example.com/article")
    # Public link should be included
    assert "https://example.com/valid" in links
    # Private/internal links must be filtered by guard_url
    for bad in ("http://127.0.0.1:8787/secret", "http://169.254.169.254/latest/meta-data",
                "http://10.0.0.5/admin"):
        assert bad not in links


# ── Bonus: authenticated probe of localhost still works ────────────

def test_probe_localhost_works_when_authenticated(monkeypatch):
    """An authenticated probe of a localhost base still works (F-2 constraint)."""
    monkeypatch.setenv("VOZONDA_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get("/llm/probe", params={"engine": "custom", "custom_base": "http://127.0.0.1:11434/"},
                    headers={"Authorization": "Bearer s3cret"})
    # The probe either succeeds (200) or fails because nothing is running on port 11434
    # but crucially it must NOT be blocked by auth (401) or SSRF guard (422)
    assert r.status_code not in (401, 422)