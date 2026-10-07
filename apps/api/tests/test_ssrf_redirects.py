"""SSRF guard applies to every redirect hop, not only the first URL (audit 2026-09-22)."""

import asyncio

import httpx
import pytest

from vozonda_api import fetcher


@pytest.fixture
def fake_dns(monkeypatch):
    # public.example resolves public, everything with "internal" or 127.x is private
    monkeypatch.setattr(fetcher, "_host_is_private", lambda host: "internal" in host or host.startswith("127."))


def _transport():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/to-private":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:30001/v1/models"})
        if request.url.path == "/to-public":
            return httpx.Response(302, headers={"location": "https://other.example/page"})
        return httpx.Response(200, text="ok")
    return httpx.MockTransport(handler)


async def _get(url: str) -> httpx.Response:
    async with fetcher.guarded_client(transport=_transport(), follow_redirects=True) as c:
        return await c.get(url)


def test_redirect_to_private_address_is_refused(fake_dns):
    with pytest.raises(fetcher.FetchError):
        asyncio.run(_get("https://public.example/to-private"))


def test_redirect_between_public_hosts_is_followed(fake_dns):
    r = asyncio.run(_get("https://public.example/to-public"))
    assert r.status_code == 200 and str(r.url) == "https://other.example/page"


def test_direct_private_url_is_refused(fake_dns):
    with pytest.raises(fetcher.FetchError):
        asyncio.run(_get("http://internal.lan/x"))


def test_extra_request_hooks_are_kept(fake_dns):
    seen = []

    async def hook(request):
        seen.append(str(request.url))

    async def run():
        async with fetcher.guarded_client(transport=_transport(), follow_redirects=True,
                                          event_hooks={"request": [hook]}) as c:
            await c.get("https://public.example/to-public")

    asyncio.run(run())
    assert seen == ["https://public.example/to-public", "https://other.example/page"]
