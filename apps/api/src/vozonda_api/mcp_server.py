"""Thin MCP adapter over the Vozonda HTTP API.

Exposes the HTTP API as MCP tools so AI assistants can make podcasts.
Configuration by env only: VOZONDA_API and VOZONDA_TOKEN.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .env import env

mcp = MCPServer(name="vozonda")

# Injectable client factory for tests (uses httpx.MockTransport)
client_factory: Callable[[], httpx.AsyncClient] | None = None


def _api_base() -> str:
    return env("API", "http://127.0.0.1:8787").rstrip("/")


def _auth_headers() -> dict[str, str]:
    token = env("TOKEN", "")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _get_client() -> httpx.AsyncClient:
    if client_factory is not None:
        return client_factory()
    return httpx.AsyncClient(timeout=30)


def _extract_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            detail = data.get("detail")
            if detail:
                return str(detail)
        return resp.text.strip() or f"HTTP {resp.status_code}"
    except Exception:
        txt = resp.text.strip()
        return txt or f"HTTP {resp.status_code}"


@mcp.tool()
async def create_episode(
    sources: list[str] | None = None,
    text: str | None = None,
    minutes: float | None = None,
    style: str = "balanced",
    language: str = "auto",
    focus: str | None = None,
) -> dict:
    """Create a new podcast episode from sources or pasted text.

    Provide either `sources` (one or more URLs) or `text` (pasted article).
    One URL creates a single-source episode; 2+ URLs create a combined
    multi-source episode. Use `minutes` to request a target length,
    `style` to pick the dialogue style, `language` for output language,
    and `focus` to steer emphasis (adds no facts).
    """
    payload: dict = {}
    if text is not None and text.strip():
        payload["text"] = text
    elif sources:
        if len(sources) == 1:
            payload["url"] = sources[0]
        else:
            payload["combine"] = True
            payload["digest_sources"] = sources
    else:
        raise ToolError("provide sources or text")

    payload["style"] = style
    payload["language"] = language
    if focus is not None:
        payload["focus"] = focus
    if minutes is not None:
        payload["target_minutes"] = minutes

    url = f"{_api_base()}/jobs"
    headers = _auth_headers()
    try:
        async with _get_client() as client:
            resp = await client.post(url, json=payload, headers=headers)
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(str(exc)) from exc

    if resp.status_code == 402:
        raise ToolError(f"payment required: {_extract_detail(resp)}")
    if resp.status_code >= 400:
        raise ToolError(_extract_detail(resp))
    try:
        data = resp.json()
    except Exception as exc:
        raise ToolError(f"invalid response: {exc}") from exc
    return {
        "id": data.get("id"),
        "state": data.get("state"),
        "status_hint": "call get_episode(id) until state is done",
    }


@mcp.tool()
async def get_episode(job_id: str) -> dict:
    """Get episode status, metadata and audio URL when done.

    Poll this after create_episode until state is done.
    """
    url = f"{_api_base()}/jobs/{job_id}"
    try:
        async with _get_client() as client:
            resp = await client.get(url)
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(str(exc)) from exc
    if resp.status_code >= 400:
        raise ToolError(_extract_detail(resp))
    try:
        data = resp.json()
    except Exception as exc:
        raise ToolError(f"invalid response: {exc}") from exc
    result: dict = {
        "id": data.get("id"),
        "state": data.get("state"),
        "title": data.get("title"),
        "duration_ms": data.get("duration_ms"),
        "error": data.get("error", ""),
    }
    if data.get("state") == "done":
        result["audio_url"] = f"{_api_base()}/audio/{job_id}.mp3"
    return result


@mcp.tool()
async def list_episodes(limit: int = 10) -> list[dict]:
    """List recent episodes with id, title, state and created_at."""
    url = f"{_api_base()}/jobs"
    try:
        async with _get_client() as client:
            resp = await client.get(url, params={"limit": limit})
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(str(exc)) from exc
    if resp.status_code >= 400:
        raise ToolError(_extract_detail(resp))
    try:
        data = resp.json()
    except Exception as exc:
        raise ToolError(f"invalid response: {exc}") from exc
    jobs = data.get("jobs", [])
    return [
        {
            "id": j.get("id"),
            "title": j.get("title"),
            "state": j.get("state"),
            "created_at": j.get("created_at"),
        }
        for j in jobs
    ]


@mcp.tool()
async def list_styles() -> list[dict]:
    """List available dialogue styles with a one-line description each."""
    url = f"{_api_base()}/meta"
    try:
        async with _get_client() as client:
            resp = await client.get(url)
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(str(exc)) from exc
    if resp.status_code >= 400:
        raise ToolError(_extract_detail(resp))
    try:
        data = resp.json()
    except Exception as exc:
        raise ToolError(f"invalid response: {exc}") from exc
    styles: list[str] = data.get("styles", [])
    docs: dict = data.get("style_docs", {})
    return [{"id": sid, "description": docs.get(sid, "")} for sid in styles]


@mcp.tool()
async def get_feed_url() -> str:
    """Get the RSS feed URL for all done episodes."""
    return f"{_api_base()}/feed.xml"


@mcp.tool()
async def list_watchlists() -> list[dict]:
    """List all watched feeds with their schedule and status.

    Each entry has id, feed_url, style, language, schedule, schedule_tz,
    enabled and last_checked. Use this to find a watchlist id for the
    other watchlist tools.
    """
    url = f"{_api_base()}/watchlist"
    try:
        async with _get_client() as client:
            resp = await client.get(url, headers=_auth_headers())
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(str(exc)) from exc
    if resp.status_code >= 400:
        raise ToolError(_extract_detail(resp))
    try:
        data = resp.json()
    except Exception as exc:
        raise ToolError(f"invalid response: {exc}") from exc
    watchlist = data.get("watchlist", [])
    return watchlist if isinstance(watchlist, list) else []


@mcp.tool()
async def create_watchlist(
    feed_url: str,
    style: str = "balanced",
    language: str = "auto",
    digest_mode: int | None = None,
    digest_count: int | None = None,
    schedule: str | None = None,
    schedule_tz: str = "UTC",
) -> dict:
    """Watch an RSS/Atom feed so new articles become episodes by themselves.

    Posts the feed to the watchlist; without a schedule new entries are
    rendered as they arrive, with a schedule they are bundled into a digest.
    Schedule format is 'daily@HH:MM' (24h, e.g. 'daily@08:00') or
    'weekly@mon..sun@HH:MM' (e.g. 'weekly@mon@08:00'); schedule_tz is an
    IANA timezone (e.g. 'Europe/Berlin', default 'UTC').
    Example: create_watchlist(feed_url="https://example.com/feed.xml",
    schedule="daily@08:00", schedule_tz="Europe/Berlin").
    Bad schedule, style or language comes back as a 422 message.
    """
    payload: dict = {
        "feed_url": feed_url,
        "style": style,
        "language": language,
        "schedule_tz": schedule_tz,
    }
    if schedule is not None:
        payload["schedule"] = schedule
    # POST /watchlist has no digest fields (WatchlistIn); they are set with PUT afterwards,
    # otherwise an agent asking for a digest silently got a per-article watchlist.
    digest = {k: v for k, v in (("digest_mode", digest_mode), ("digest_count", digest_count)) if v is not None}
    url = f"{_api_base()}/watchlist"
    try:
        async with _get_client() as client:
            resp = await client.post(url, json=payload, headers=_auth_headers())
            if resp.status_code < 400 and digest:
                created = resp.json()
                wid = created.get("id") if isinstance(created, dict) else None
                if not wid:
                    raise ToolError("watchlist created but no id returned; digest settings not applied")
                resp = await client.put(f"{url}/{wid}", json=digest, headers=_auth_headers())
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(str(exc)) from exc
    if resp.status_code >= 400:
        raise ToolError(_extract_detail(resp))
    try:
        data = resp.json()
    except Exception as exc:
        raise ToolError(f"invalid response: {exc}") from exc
    return data if isinstance(data, dict) else {"result": data}


@mcp.tool()
async def set_watchlist_schedule(
    watchlist_id: str,
    schedule: str | None = None,
    schedule_tz: str = "UTC",
) -> dict:
    """Set or clear when a watched feed renders its digest episode.

    Pass schedule=None to clear the schedule (entries render as they
    arrive again). Schedule format is 'daily@HH:MM' (24h, e.g. 'daily@08:00')
    or 'weekly@mon..sun@HH:MM' (e.g. 'weekly@mon@08:00'); schedule_tz is an
    IANA timezone (e.g. 'Europe/Berlin', default 'UTC').
    Example: set_watchlist_schedule(watchlist_id="wl-1",
    schedule="weekly@mon@08:00", schedule_tz="UTC").
    Unknown id comes back as a 404 message, bad schedule as 422.
    """
    payload: dict = {"schedule": schedule, "schedule_tz": schedule_tz}
    url = f"{_api_base()}/watchlist/{watchlist_id}"
    try:
        async with _get_client() as client:
            resp = await client.put(url, json=payload, headers=_auth_headers())
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(str(exc)) from exc
    if resp.status_code >= 400:
        raise ToolError(_extract_detail(resp))
    try:
        data = resp.json()
    except Exception as exc:
        raise ToolError(f"invalid response: {exc}") from exc
    return data if isinstance(data, dict) else {"result": data}


@mcp.tool()
async def check_watchlist(watchlist_id: str) -> dict:
    """Poll a watched feed right now and render new entries.

    Example: check_watchlist(watchlist_id="wl-1"). Returns which job ids
    were created. Unknown id comes back as a 404 message.
    """
    url = f"{_api_base()}/watchlist/{watchlist_id}/check"
    try:
        async with _get_client() as client:
            resp = await client.post(url, headers=_auth_headers())
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(str(exc)) from exc
    if resp.status_code >= 400:
        raise ToolError(_extract_detail(resp))
    try:
        data = resp.json()
    except Exception as exc:
        raise ToolError(f"invalid response: {exc}") from exc
    return data if isinstance(data, dict) else {"result": data}


@mcp.tool()
async def render_digest(watchlist_id: str) -> dict:
    """Bundle the newest fresh entries of a watched feed into one episode.

    Example: render_digest(watchlist_id="wl-1"). Needs at least 2 fresh
    entries, otherwise a 422 message tells you to check first or wait.
    Unknown id comes back as a 404 message.
    """
    url = f"{_api_base()}/watchlist/{watchlist_id}/digest"
    try:
        async with _get_client() as client:
            resp = await client.post(url, headers=_auth_headers())
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(str(exc)) from exc
    if resp.status_code >= 400:
        raise ToolError(_extract_detail(resp))
    try:
        data = resp.json()
    except Exception as exc:
        raise ToolError(f"invalid response: {exc}") from exc
    return data if isinstance(data, dict) else {"result": data}


@mcp.tool()
async def delete_watchlist(watchlist_id: str) -> dict:
    """Stop watching a feed. Keeps episodes already rendered.

    Example: delete_watchlist(watchlist_id="wl-1").
    Unknown id comes back as a 404 message.
    """
    url = f"{_api_base()}/watchlist/{watchlist_id}"
    try:
        async with _get_client() as client:
            resp = await client.delete(url, headers=_auth_headers())
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(str(exc)) from exc
    if resp.status_code >= 400:
        raise ToolError(_extract_detail(resp))
    try:
        data = resp.json()
    except Exception as exc:
        raise ToolError(f"invalid response: {exc}") from exc
    return data if isinstance(data, dict) else {"result": data}


def main() -> None:
    parser = argparse.ArgumentParser(description="Vozonda MCP server")
    parser.add_argument("--http", action="store_true", help="use streamable HTTP instead of stdio")
    parser.add_argument("--port", type=int, default=8790, help="HTTP port (default 8790)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="HTTP host (default 127.0.0.1)")
    args = parser.parse_args()
    if args.http:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
