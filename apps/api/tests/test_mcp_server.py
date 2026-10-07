import httpx
import pytest

import vozonda_api.mcp_server as mcp_server


def _make_factory(handler, base="http://127.0.0.1:8787"):
    transport = httpx.MockTransport(handler)

    def factory():
        return httpx.AsyncClient(transport=transport, base_url=base)

    return factory, transport


@pytest.mark.asyncio
async def test_create_episode_one_source(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["method"] = request.method
        import json

        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": "ep-1", "state": "queued"})

    factory, _ = _make_factory(handler)
    monkeypatch.setattr(mcp_server, "client_factory", factory)
    res = await mcp_server.create_episode(sources=["https://example.com/a"])
    assert captured["path"] == "/jobs"
    assert captured["method"] == "POST"
    assert captured["body"]["url"] == "https://example.com/a"
    assert "combine" not in captured["body"]
    assert res["id"] == "ep-1"
    assert res["state"] == "queued"
    assert "status_hint" in res
    assert "get_episode" in res["status_hint"]


@pytest.mark.asyncio
async def test_create_episode_two_sources(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content.decode())
        captured["path"] = request.url.path
        return httpx.Response(200, json={"id": "digest-1", "state": "queued"})

    factory, _ = _make_factory(handler)
    monkeypatch.setattr(mcp_server, "client_factory", factory)
    res = await mcp_server.create_episode(
        sources=["https://example.com/a", "https://example.com/b"]
    )
    assert captured["path"] == "/jobs"
    assert captured["body"]["combine"] is True
    assert captured["body"]["digest_sources"] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert res["id"] == "digest-1"


@pytest.mark.asyncio
async def test_create_episode_text_and_minutes(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": "txt-1", "state": "queued"})

    factory, _ = _make_factory(handler)
    monkeypatch.setattr(mcp_server, "client_factory", factory)
    await mcp_server.create_episode(text="hello world this is a long enough text", minutes=12.5)
    assert captured["body"]["text"] == "hello world this is a long enough text"
    assert captured["body"]["target_minutes"] == 12.5


@pytest.mark.asyncio
async def test_create_episode_bearer_header(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.setenv("VOZONDA_TOKEN", "s3cret")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": "ep-2", "state": "queued"})

    factory, _ = _make_factory(handler)
    monkeypatch.setattr(mcp_server, "client_factory", factory)
    await mcp_server.create_episode(sources=["https://example.com/a"])
    assert captured["auth"] == "Bearer s3cret"


@pytest.mark.asyncio
async def test_create_episode_402_mapping(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"detail": "needs 5 sats"})

    factory, _ = _make_factory(handler)
    monkeypatch.setattr(mcp_server, "client_factory", factory)
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="payment required: needs 5 sats"):
        await mcp_server.create_episode(sources=["https://example.com/a"])


@pytest.mark.asyncio
async def test_get_episode_audio_url_only_when_done(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")

    def handler_queued(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/jobs/ep-1"
        return httpx.Response(
            200,
            json={
                "id": "ep-1",
                "state": "queued",
                "title": "t",
                "duration_ms": None,
                "error": "",
            },
        )

    factory, _ = _make_factory(handler_queued)
    monkeypatch.setattr(mcp_server, "client_factory", factory)
    res = await mcp_server.get_episode("ep-1")
    assert res["id"] == "ep-1"
    assert res["state"] == "queued"
    assert "audio_url" not in res

    def handler_done(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "ep-1",
                "state": "done",
                "title": "t",
                "duration_ms": 1234,
                "error": "",
            },
        )

    factory2, _ = _make_factory(handler_done)
    monkeypatch.setattr(mcp_server, "client_factory", factory2)
    res2 = await mcp_server.get_episode("ep-1")
    assert res2["audio_url"] == "http://127.0.0.1:8787/audio/ep-1.mp3"
    assert res2["duration_ms"] == 1234


@pytest.mark.asyncio
async def test_list_episodes(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": "ep-1",
                        "title": "hello",
                        "state": "done",
                        "created_at": "2026-01-01T00:00:00",
                    }
                ]
            },
        )

    factory, _ = _make_factory(handler)
    monkeypatch.setattr(mcp_server, "client_factory", factory)
    res = await mcp_server.list_episodes(limit=5)
    assert captured["path"] == "/jobs"
    assert captured["params"]["limit"] == "5"
    assert res[0]["id"] == "ep-1"
    assert res[0]["title"] == "hello"
    assert res[0]["state"] == "done"
    assert "created_at" in res[0]


@pytest.mark.asyncio
async def test_list_styles(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "styles": ["balanced", "serious"],
                "style_docs": {
                    "balanced": "Balanced tour: curious host, expert guest.",
                    "serious": "Precise and evidence-first, no jokes.",
                },
            },
        )

    factory, _ = _make_factory(handler)
    monkeypatch.setattr(mcp_server, "client_factory", factory)
    res = await mcp_server.list_styles()
    assert captured["path"] == "/meta"
    ids = [r["id"] for r in res]
    assert "balanced" in ids
    bal = next(r for r in res if r["id"] == "balanced")
    assert "Balanced" in bal["description"]


@pytest.mark.asyncio
async def test_get_feed_url(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    url = await mcp_server.get_feed_url()
    assert url == "http://127.0.0.1:8787/feed.xml"
    monkeypatch.setenv("VOZONDA_API", "http://example.com:9999")
    url2 = await mcp_server.get_feed_url()
    assert url2 == "http://example.com:9999/feed.xml"


@pytest.mark.asyncio
async def test_http_errors_become_tool_error(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "internal error"})

    factory, _ = _make_factory(handler)
    monkeypatch.setattr(mcp_server, "client_factory", factory)
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="internal error"):
        await mcp_server.get_episode("ep-x")
    with pytest.raises(ToolError, match="internal error"):
        await mcp_server.list_episodes()
    with pytest.raises(ToolError, match="internal error"):
        await mcp_server.list_styles()
