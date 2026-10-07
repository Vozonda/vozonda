import httpx
import pytest

import vozonda_api.mcp_server as mcp_server


def _make_factory(handler, base="http://127.0.0.1:8787"):
    transport = httpx.MockTransport(handler)

    def factory():
        return httpx.AsyncClient(transport=transport, base_url=base)

    return factory


@pytest.mark.asyncio
async def test_list_watchlists(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "watchlist": [
                    {"id": "wl-1", "feed_url": "https://example.com/feed.xml"}
                ]
            },
        )

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    res = await mcp_server.list_watchlists()
    assert captured["method"] == "GET"
    assert captured["path"] == "/watchlist"
    assert res == [{"id": "wl-1", "feed_url": "https://example.com/feed.xml"}]


@pytest.mark.asyncio
async def test_list_watchlists_sends_auth(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.setenv("VOZONDA_TOKEN", "s3cret")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"watchlist": []})

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    await mcp_server.list_watchlists()
    assert captured["auth"] == "Bearer s3cret"


@pytest.mark.asyncio
async def test_create_watchlist(monkeypatch):
    """POST /watchlist ignores digest fields (WatchlistIn has none; review F-1), so the
    tool must create first and then set digest_mode/digest_count with PUT /watchlist/{id}."""
    import json

    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode()) if request.content else None
        calls.append((request.method, request.url.path, body))
        if request.method == "POST":
            return httpx.Response(200, json={"id": "wl-1", "schedule": "daily@08:00", "digest_mode": 0})
        return httpx.Response(200, json={"id": "wl-1", "schedule": "daily@08:00", "digest_mode": 1, "digest_count": 3})

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    res = await mcp_server.create_watchlist(
        feed_url="https://example.com/feed.xml",
        style="balanced",
        language="auto",
        digest_mode=1,
        digest_count=3,
        schedule="daily@08:00",
        schedule_tz="Europe/Berlin",
    )
    assert [c[:2] for c in calls] == [("POST", "/watchlist"), ("PUT", "/watchlist/wl-1")]
    post, put = calls[0][2], calls[1][2]
    assert post["feed_url"] == "https://example.com/feed.xml"
    assert post["style"] == "balanced" and post["language"] == "auto"
    assert post["schedule"] == "daily@08:00" and post["schedule_tz"] == "Europe/Berlin"
    assert "digest_mode" not in post and "digest_count" not in post
    assert put == {"digest_mode": 1, "digest_count": 3}
    assert res["id"] == "wl-1" and res["digest_mode"] == 1 and res["digest_count"] == 3


@pytest.mark.asyncio
async def test_create_watchlist_without_digest_makes_one_call(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"id": "wl-2"})

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    await mcp_server.create_watchlist(feed_url="https://example.com/feed.xml")
    assert calls == ["POST"]


@pytest.mark.asyncio
async def test_create_watchlist_422_readable(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "Invalid schedule format"})

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="Invalid schedule format"):
        await mcp_server.create_watchlist(
            feed_url="https://example.com/feed.xml", schedule="nonsense"
        )


@pytest.mark.asyncio
async def test_set_watchlist_schedule(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": "wl-1", "schedule": "weekly@mon@08:00"})

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    res = await mcp_server.set_watchlist_schedule(
        "wl-1", schedule="weekly@mon@08:00", schedule_tz="UTC"
    )
    assert captured["method"] == "PUT"
    assert captured["path"] == "/watchlist/wl-1"
    assert captured["body"]["schedule"] == "weekly@mon@08:00"
    assert captured["body"]["schedule_tz"] == "UTC"
    assert res["schedule"] == "weekly@mon@08:00"


@pytest.mark.asyncio
async def test_set_watchlist_schedule_none_clears(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content.decode())
        captured["path"] = request.url.path
        return httpx.Response(200, json={"id": "wl-1", "schedule": None})

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    await mcp_server.set_watchlist_schedule("wl-1", schedule=None)
    assert captured["path"] == "/watchlist/wl-1"
    assert captured["body"]["schedule"] is None


@pytest.mark.asyncio
async def test_set_watchlist_schedule_404(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "no such watchlist"})

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="no such watchlist"):
        await mcp_server.set_watchlist_schedule("wl-missing", schedule="daily@08:00")


@pytest.mark.asyncio
async def test_check_watchlist(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        return httpx.Response(200, json={"checked": "wl-1", "created": ["job-1"]})

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    res = await mcp_server.check_watchlist("wl-1")
    assert captured["method"] == "POST"
    assert captured["path"] == "/watchlist/wl-1/check"
    assert res == {"checked": "wl-1", "created": ["job-1"]}


@pytest.mark.asyncio
async def test_check_watchlist_404(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "no such watchlist"})

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="no such watchlist"):
        await mcp_server.check_watchlist("wl-missing")


@pytest.mark.asyncio
async def test_render_digest(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        return httpx.Response(200, json={"digest_job": "job-9", "sources": ["u1", "u2"]})

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    res = await mcp_server.render_digest("wl-1")
    assert captured["method"] == "POST"
    assert captured["path"] == "/watchlist/wl-1/digest"
    assert res["digest_job"] == "job-9"


@pytest.mark.asyncio
async def test_render_digest_422_readable(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "not enough fresh entries"})

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="not enough fresh entries"):
        await mcp_server.render_digest("wl-1")


@pytest.mark.asyncio
async def test_delete_watchlist(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        return httpx.Response(200, json={"deleted": "wl-1"})

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    res = await mcp_server.delete_watchlist("wl-1")
    assert captured["method"] == "DELETE"
    assert captured["path"] == "/watchlist/wl-1"
    assert res == {"deleted": "wl-1"}


@pytest.mark.asyncio
async def test_delete_watchlist_404(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "no such watchlist"})

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="no such watchlist"):
        await mcp_server.delete_watchlist("wl-missing")


@pytest.mark.asyncio
async def test_watchlist_401_readable(monkeypatch):
    monkeypatch.setenv("VOZONDA_API", "http://127.0.0.1:8787")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid token"})

    monkeypatch.setattr(mcp_server, "client_factory", _make_factory(handler))
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="invalid token"):
        await mcp_server.list_watchlists()


@pytest.mark.asyncio
async def test_watchlist_tools_registered():
    tools = await mcp_server.mcp.list_tools()
    names = {t.name for t in tools}
    for expected in (
        "list_watchlists",
        "create_watchlist",
        "set_watchlist_schedule",
        "check_watchlist",
        "render_digest",
        "delete_watchlist",
    ):
        assert expected in names


def test_watchlist_docstrings_describe_schedule():
    for fn_name in ("create_watchlist", "set_watchlist_schedule"):
        doc = getattr(mcp_server, fn_name).__doc__ or ""
        assert "daily@HH:MM" in doc
        assert "weekly@" in doc
        assert "IANA" in doc or "timezone" in doc.lower()
