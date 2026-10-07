"""Blossom client: BUD-01/02/04/06, auth events, mirrors, error mapping, SSRF guard."""

from __future__ import annotations

import base64
import hashlib
import json

import httpx
import pytest

from vozonda_api import blossom
from vozonda_api import fetcher


def _signer(event: dict) -> dict:
    return {**event, "pubkey": "00" * 32, "id": "ab" * 32, "sig": "cd" * 64}


def _decode_auth(request: httpx.Request) -> dict:
    header = request.headers.get("authorization", "")
    assert header.startswith("Nostr ")
    return json.loads(base64.b64decode(header[len("Nostr "):]).decode("utf-8"))


def _decode_auth_value(header: str) -> dict:
    assert header.startswith("Nostr ")
    return json.loads(base64.b64decode(header[len("Nostr "):]).decode("utf-8"))


@pytest.fixture
def fake_dns(monkeypatch):
    monkeypatch.setattr(
        fetcher,
        "_host_is_private",
        lambda host: host in ("127.0.0.1", "localhost") or "private" in host or "internal" in host,
    )


def test_sha256_correctness():
    assert blossom.sha256_bytes(b"abc") == hashlib.sha256(b"abc").hexdigest()
    assert blossom.sha256_bytes(b"") == hashlib.sha256(b"").hexdigest()


def test_upload_auth_event_content_and_tags(fake_dns):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD" and request.url.path == "/upload":
            seen["preflight"] = dict(request.headers)
            return httpx.Response(200)
        if request.method == "PUT" and request.url.path == "/upload":
            seen["auth"] = _decode_auth(request)
            seen["content_type"] = request.headers.get("content-type")
            sha = hashlib.sha256(request.content).hexdigest()
            return httpx.Response(
                200,
                json={"url": f"https://blossom.example/{sha}", "sha256": sha, "size": len(request.content), "type": "audio/mpeg"},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    data = b"hello blossom"
    desc = blossom.upload_blob(data, "audio/mpeg", "https://blossom.example", _signer, transport=transport)

    assert desc.sha256 == hashlib.sha256(data).hexdigest()
    assert desc.size == len(data)
    assert desc.type == "audio/mpeg"
    assert desc.url == f"https://blossom.example/{desc.sha256}"

    # preflight headers (BUD-06)
    assert seen["preflight"]["x-sha-256"] == desc.sha256
    assert seen["preflight"]["x-content-length"] == str(len(data))
    assert seen["preflight"]["x-content-type"] == "audio/mpeg"

    # auth event (BUD-02 kind 24242)
    auth = seen["auth"]
    assert auth["kind"] == 24242
    assert auth["content"] == f"upload {desc.sha256}"
    tags = {t[0]: t[1] for t in auth["tags"]}
    assert tags["t"] == "upload"
    assert tags["x"] == desc.sha256
    assert "expiration" in tags and int(tags["expiration"]) > 0


@pytest.mark.parametrize("status", [404, 405])
def test_preflight_skipped_when_unsupported(fake_dns, status):
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD" and request.url.path == "/upload":
            calls.append("preflight")
            return httpx.Response(status)
        if request.method == "PUT" and request.url.path == "/upload":
            calls.append("upload")
            sha = hashlib.sha256(request.content).hexdigest()
            return httpx.Response(200, json={"url": f"https://blossom.example/{sha}", "sha256": sha, "size": 3, "type": "text/plain"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    assert blossom.preflight_upload("https://blossom.example", "abc", 3, "text/plain", transport=transport) is False
    desc = blossom.upload_blob(b"abc", "text/plain", "https://blossom.example", _signer, transport=transport)
    assert calls == ["preflight", "preflight", "upload"]
    assert desc.sha256 == hashlib.sha256(b"abc").hexdigest()


def test_mirror_two_servers_one_failing(fake_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        if request.method == "HEAD":
            return httpx.Response(200)
        if request.method == "PUT" and request.url.path == "/upload":
            sha = hashlib.sha256(request.content).hexdigest()
            return httpx.Response(
                200, json={"url": f"https://primary.example/{sha}", "sha256": sha, "size": 4, "type": "audio/mpeg"}
            )
        if request.method == "PUT" and request.url.path == "/mirror":
            if "mirror-a" in host:
                body = json.loads(request.content.decode())
                assert "url" in body
                auth = _decode_auth(request)
                assert auth["kind"] == 24242
                return httpx.Response(200, json={"url": body["url"], "sha256": "x" * 64, "size": 4, "type": "audio/mpeg"})
            return httpx.Response(500)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    primary, outcomes = blossom.upload_and_mirror(
        b"data",
        "audio/mpeg",
        "https://primary.example",
        ["https://mirror-a.example", "https://mirror-b.example"],
        _signer,
        transport=transport,
    )
    assert primary.url.startswith("https://primary.example/")
    assert len(outcomes) == 2
    ok = [o for o in outcomes if o.descriptor is not None]
    failed = [o for o in outcomes if o.error is not None]
    assert len(ok) == 1 and len(failed) == 1
    assert ok[0].server == "https://mirror-a.example"


@pytest.mark.parametrize(
    ("status", "fragment"),
    [(413, "too large"), (401, "authorization"), (402, "payment")],
)
def test_status_mapping_and_no_auth_leak(fake_dns, status, fragment):
    auth_value: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200)
        auth_value["header"] = request.headers.get("authorization", "")
        return httpx.Response(status)

    transport = httpx.MockTransport(handler)
    with pytest.raises(blossom.BlossomError) as exc:
        blossom.upload_blob(b"abc", "text/plain", "https://blossom.example", _signer, transport=transport)
    assert fragment in str(exc.value).lower()
    # error text must never contain auth headers
    assert "Nostr " not in str(exc.value)
    assert auth_value["header"] not in str(exc.value)


def test_network_error_mapping(fake_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    transport = httpx.MockTransport(handler)
    with pytest.raises(blossom.BlossomError, match="network error"):
        blossom.upload_blob(b"abc", "text/plain", "https://blossom.example", _signer, transport=transport)


def test_guard_rejects_private_server_url(fake_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    with pytest.raises(blossom.BlossomError, match="refusing"):
        blossom.upload_blob(b"abc", "text/plain", "http://127.0.0.1:9999", _signer, transport=transport)
    with pytest.raises(blossom.BlossomError, match="refusing"):
        assert blossom.verify_blob("http://internal.lan", "abc", transport=transport) is False


def test_allow_list_permits_local_server(fake_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200)
        sha = hashlib.sha256(request.content).hexdigest()
        return httpx.Response(
            200, json={"url": f"http://127.0.0.1:9999/{sha}", "sha256": sha, "size": 3, "type": "text/plain"}
        )

    transport = httpx.MockTransport(handler)
    desc = blossom.upload_blob(
        b"abc",
        "text/plain",
        "http://127.0.0.1:9999",
        _signer,
        transport=transport,
        allow_list=["http://127.0.0.1:9999"],
    )
    assert desc.sha256 == hashlib.sha256(b"abc").hexdigest()


def test_verify_blob_true_and_false(fake_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        if "present" in request.url.path:
            return httpx.Response(200)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    assert blossom.verify_blob("https://blossom.example", "present", transport=transport) is True
    assert blossom.verify_blob("https://blossom.example", "missing", transport=transport) is False


# ---------------------------------------------------------------------------
# Coordinator review of 72f3c79 against the BUD texts (hzrd149/blossom):
# BUD-11 allows only get/upload/list/delete/media and requires t=upload for
# PUT /mirror and HEAD /upload; BUD-06 exists to refuse a blob BEFORE the body
# is sent, so a preflight 413/402/401 must stop the upload.
# ---------------------------------------------------------------------------


def test_mirror_authorization_uses_the_upload_verb():
    ev = blossom.build_mirror_event("ab" * 32, "https://primary.example/" + "ab" * 32)
    tags = {t[0]: t[1] for t in ev["tags"]}
    assert tags["t"] == "upload"
    assert tags["x"] == "ab" * 32


def test_preflight_carries_the_upload_authorization(fake_dns):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD" and request.url.path == "/upload":
            seen["auth"] = request.headers.get("authorization")
            return httpx.Response(200)
        sha = hashlib.sha256(request.content).hexdigest()
        return httpx.Response(200, json={"url": f"https://blossom.example/{sha}", "sha256": sha, "size": 3})

    blossom.upload_blob(b"abc", "text/plain", "https://blossom.example", _signer, transport=httpx.MockTransport(handler))
    assert seen["auth"] and seen["auth"].startswith("Nostr ")
    assert _decode_auth_value(seen["auth"])["tags"][0] == ["t", "upload"]


@pytest.mark.parametrize("status", [413, 402, 401])
def test_preflight_refusal_stops_before_the_body_is_sent(fake_dns, status):
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "HEAD":
            return httpx.Response(status)
        return httpx.Response(200, json={})

    with pytest.raises(blossom.BlossomError):
        blossom.upload_blob(b"abc", "text/plain", "https://blossom.example", _signer,
                            transport=httpx.MockTransport(handler))
    assert ("PUT", "/upload") not in calls
