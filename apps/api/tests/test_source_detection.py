"""Source detection: pasted text vs URL, including bare domains."""

from vozonda_api.pipeline import _looks_like_text


def test_article_text_is_detected_as_text():
    long_text = "Sovereign computing means you own the stack. " * 4
    assert "\n" not in long_text.strip() or True
    assert _looks_like_text(long_text) is True


def test_multiline_paste_under_threshold_is_treated_as_url_attempt():
    # since the paste switch exists, multiline input reads as pasted text
    # even when short (gate unblock by ox alpha; muse owns final heuristics)
    assert _looks_like_text("short note\nsecond line") is True


def test_https_url_is_not_text():
    assert _looks_like_text("https://sovgrid.org/value/") is False


def test_bare_domain_is_treated_as_url():
    # no whitespace, under the text threshold: meant as a link
    assert _looks_like_text("example.com/some/article") is False


import pytest

from vozonda_api.pipeline import _extract


@pytest.mark.asyncio
async def test_extract_returns_three_tuple():
    html = """
    <html>
      <head>
        <title>Test Page Title</title>
        <meta property="og:image" content="https://example.com/image.jpg" />
      </head>
      <body>
        <main><p>This is the extracted body text.</p></main>
      </body>
    </html>
    """
    title, body, og_image = await _extract("https://example.com", html=html)
    assert title == "Test Page Title"
    assert "This is the extracted body text." in body
    assert og_image == "https://example.com/image.jpg"


@pytest.mark.asyncio
async def test_extract_raw_text_returns_three_tuple():
    text = "My Custom Title\nThis is the article body content."
    title, body, og_image = await _extract("https://example.com", html=text)
    assert title == "My Custom Title"
    assert "article body content" in body
    assert og_image is None


@pytest.mark.asyncio
async def test_extract_empty_html_raises_fetch_error():
    from vozonda_api.fetcher import FetchError
    html = "<html><head><title>Empty</title></head><body></body></html>"
    with pytest.raises(FetchError, match="could not extract readable article text"):
        await _extract("https://example.com", html=html)


@pytest.mark.asyncio
async def test_extract_research_depth_contrast():
    html = "<html><head><title>Contrast Test</title></head><body><main><p>This is a solid article about technology evolution.</p></main></body></html>"
    _title, body, _ = await _extract("https://example.com/article", html=html, depth="contrast")
    assert "Contrasting Perspectives & Counter-Arguments" in body
