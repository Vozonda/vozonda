"""What a link is comes from what the server sends, not from the URL (2026-10-03: a
Wikipedia page ending in '#/media/File:Mona_Lisa.jpg' went to the vision model as an
image; large photos were cut at 2 MB and never shrunk, so the vision server refused them)."""

import asyncio
import io

import httpx
import pytest
from PIL import Image

from vozonda_api import fetcher, sources


def _jpeg(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def serve(monkeypatch):
    """Serve one fixed response for any URL; capture what reaches the vision model."""
    seen: dict = {}

    def install(body: bytes, ctype: str | None):
        headers = {"content-type": ctype} if ctype else {}
        transport = httpx.MockTransport(lambda req: httpx.Response(200, content=body, headers=headers))
        monkeypatch.setattr(fetcher, "guard_url", lambda u: None)
        monkeypatch.setattr(fetcher, "guarded_client", lambda **kw: httpx.AsyncClient(transport=transport, **kw))

        async def fake_vision(data, ctype):
            seen["bytes"], seen["ctype"] = data, ctype
            return "described"

        monkeypatch.setattr(fetcher, "_extract_image_text", fake_vision)
        return seen

    return install


def test_an_html_page_with_a_jpg_fragment_is_an_article(serve):
    seen = serve(b"<html><title>Mona Lisa</title><p>text</p></html>", "text/html; charset=utf-8")
    kind, content = asyncio.run(fetcher.fetch_document("https://en.wikipedia.org/wiki/Mona_Lisa#/media/File:Mona_Lisa.jpg"))
    assert kind == "article" and "<title>Mona Lisa" in content and "bytes" not in seen


def test_html_content_type_wins_over_a_jpg_path(serve):
    serve(b"<html><p>a gallery page</p></html>", "text/html")
    assert asyncio.run(fetcher.fetch_document("https://example.org/gallery/photo.jpg"))[0] == "article"


def test_an_untyped_response_is_recognised_by_its_bytes(serve):
    seen = serve(_jpeg(40, 30), None)
    assert asyncio.run(fetcher.fetch_document("https://example.org/download?id=7"))[0] == "image"
    assert seen["bytes"][:3] == b"\xff\xd8\xff"


def test_an_image_bigger_than_2mb_is_read_whole(serve, monkeypatch):
    monkeypatch.setattr(fetcher, "FETCH_MAX_BYTES", 1000)
    body = _jpeg(800, 600)
    assert len(body) > 1000
    seen = serve(body, "image/jpeg")
    asyncio.run(fetcher.fetch_document("https://example.org/a.jpg"))
    assert seen["bytes"] == body


def test_an_image_over_the_cap_fails_as_too_large(serve, monkeypatch):
    monkeypatch.setattr(fetcher, "PDF_MAX_BYTES", 500)
    serve(_jpeg(400, 300), "image/jpeg")
    with pytest.raises(fetcher.FetchError) as e:
        asyncio.run(fetcher.fetch_document("https://example.org/huge.jpg"))
    assert sources.classify(e.value) == "too_large"


def test_big_images_are_shrunk_before_the_vision_model():
    data, ctype = fetcher._shrink_image(_jpeg(5000, 1200))
    assert ctype == "image/jpeg"
    assert max(Image.open(io.BytesIO(data)).size) == fetcher.IMAGE_MAX_SIDE


def test_the_vision_prompt_also_describes_pictures_without_text():
    assert "describe" in fetcher.VISION_PROMPT and "transcribe" in fetcher.VISION_PROMPT
