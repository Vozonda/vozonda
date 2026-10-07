"""Unit tests for the hardened fetcher (no real network needed)."""

import pytest

from vozonda_api.fetcher import (
    FetchError,
    _host_is_private,
    _parse_vtt,
    extract_youtube_id,
    guard_url,
)


def test_loopback_is_private():
    assert _host_is_private("127.0.0.1") is True
    assert _host_is_private("localhost") is True


def test_rfc1918_and_linklocal_are_private():
    assert _host_is_private("10.1.2.3") is True
    assert _host_is_private("192.168.1.1") is True
    assert _host_is_private("169.254.169.254") is True  # cloud metadata
    assert _host_is_private("::1") is True


def test_public_host_is_not_private():
    # resolves via real DNS; sparki always has network in this environment
    assert _host_is_private("sovgrid.org") is False


def test_unresolvable_host_is_blocked_with_dns_message():
    # unresolvable hosts stay blocked, but the error must say dns,
    # not local address: a dead subdomain is not ssrf (issue from the
    # 2026-08-25 watchlist debugging)
    with pytest.raises(FetchError, match="cannot resolve host"):
        _host_is_private("this-host-does-not-exist-vozonda.invalid")


def test_guard_rejects_non_http_schemes():
    with pytest.raises(FetchError, match="scheme"):
        guard_url("file:///etc/passwd")
    with pytest.raises(FetchError, match="scheme"):
        guard_url("ftp://example.com/x")


def test_guard_rejects_local_targets():
    with pytest.raises(FetchError, match="local"):
        guard_url("http://127.0.0.1:8787/meta")
    with pytest.raises(FetchError, match="local"):
        guard_url("http://localhost:3002")


def test_guard_accepts_public_url():
    guard_url("https://de.wikipedia.org/wiki/NVIDIA")


def test_detect_source_lang():
    from vozonda_api.pipeline import detect_source_lang

    en = ("The quick brown fox jumps over the lazy dog. " * 10)
    de = ("Der schnelle braune Fuchs springt uber den faulen Hund. "
          "Die Sonne ist nicht sichtbar und die Luft ist kalt. " * 5)
    es = ("El rapido zorro marron salta sobre el perro perezoso. "
          "Los ninos estan en la casa y la madre por el camino. " * 5)
    assert detect_source_lang(en) == "en"
    assert detect_source_lang(de) == "de"
    assert detect_source_lang(es) == "es"
    assert detect_source_lang("short text") is None


def test_write_auth_enforced_when_token_set(monkeypatch):
    from fastapi import HTTPException

    from vozonda_api.main import require_write_auth

    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    import asyncio
    asyncio.run(require_write_auth(None))  # open when unset

    monkeypatch.setenv("VOZONDA_TOKEN", "s3cret")
    try:
        asyncio.run(require_write_auth(None))
        raised = False
    except HTTPException as e:
        raised = e.status_code == 401
    assert raised
    asyncio.run(require_write_auth("Bearer s3cret"))  # accepted


def test_delete_removes_row(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod
    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "t.db")
    store = jobs_mod.JobStore()
    jobs_mod.init_db()
    store.create("del-1", "https://x.example")
    store.delete("del-1")
    try:
        store.get("del-1")
        gone = False
    except KeyError:
        gone = True
    assert gone


def test_extract_youtube_id():
    assert extract_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://www.youtube.com/v/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=123") == "dQw4w9WgXcQ"
    assert extract_youtube_id("not a youtube url") is None
    assert extract_youtube_id("https://example.com/watch?v=dQw4w9WgXcQ") is None


def test_parse_vtt():
    vtt = """WEBVTT

00:00:01.000 --> 00:00:04.000
Hello world

00:00:04.000 --> 00:00:07.000
This is a test

00:00:07.000 --> 00:00:10.000
Hello world

00:00:10.000 --> 00:00:13.000
<c>Bold text</c> and normal
"""
    result = _parse_vtt(vtt)
    assert "Hello world" in result
    assert "This is a test" in result
    assert "Bold text and normal" in result
    # Check consecutive deduplication works
    vtt2 = """WEBVTT

00:00:01.000 --> 00:00:04.000
Hello world

00:00:04.000 --> 00:00:07.000
Hello world

00:00:07.000 --> 00:00:10.000
This is a test
"""
    result2 = _parse_vtt(vtt2)
    lines = result2.split("\n")
    assert lines.count("Hello world") == 1  # consecutive deduplicated


def test_parse_vtt_empty():
    assert _parse_vtt("") == ""
    assert _parse_vtt("WEBVTT\n\n") == ""


def test_extract_pdf_text():
    from vozonda_api.fetcher import _extract_pdf_text
    # Test with invalid / empty bytes raises FetchError
    with pytest.raises(FetchError):
        _extract_pdf_text(b"not a valid pdf content")


@pytest.mark.asyncio
async def test_extract_opengraph_image():
    from vozonda_api.pipeline import _extract

    html = """<html><head>
    <title>Test Article</title>
    <meta property="og:image" content="https://example.com/cover.jpg">
    </head><body><p>Article body text</p></body></html>"""

    title, body, og_image = await _extract("https://example.com/article", html=html)
    assert title == "Test Article"
    assert og_image == "https://example.com/cover.jpg"
    assert "Article body" in body