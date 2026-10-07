"""Blossom media client (BUD-01, BUD-02, BUD-04, BUD-06).

Standalone client following the Blossom BUDs (github.com/hzrd149/blossom):

- sha256 of a file (BUD-02 addressing)
- BUD-06 preflight: HEAD /upload with X-SHA-256, X-Content-Length,
  X-Content-Type when the server supports it
- BUD-02 upload: PUT /upload with a kind 24242 authorization event
  (content "upload <sha>", tags t=upload, x=<sha>, expiration=<unix ts>)
- BUD-04 mirror: PUT /mirror to further servers
- BUD-01 verify: HEAD /<sha256> checks a blob exists

Signing is injected: callers pass sign_event(event_dict) which returns the
signed event dict. This module never handles private keys.

Server URLs come from the caller. The SSRF guard (fetcher.guard_url) applies
to every server URL except origins listed in an explicit allow list for a
local self-hosted server.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .fetcher import FetchError, guard_url

TIMEOUT = httpx.Timeout(30.0, connect=10.0)

SignFunc = Callable[[dict], dict]


class BlossomError(Exception):
    """User-presentable Blossom failure. Never contains auth headers."""


@dataclass
class BlobDescriptor:
    url: str
    sha256: str
    size: int
    type: str

    def to_dict(self) -> dict:
        return {"url": self.url, "sha256": self.sha256, "size": self.size, "type": self.type}


@dataclass
class MirrorOutcome:
    server: str
    descriptor: BlobDescriptor | None
    error: str | None


def sha256_bytes(data: bytes) -> str:
    """Hex sha256 of blob bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    """Hex sha256 of a file on disk, streamed."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_upload_event(
    sha256: str,
    size: int,
    content_type: str,
    *,
    created_at: int | None = None,
    expiration_secs: int = 300,
) -> dict:
    """Unsigned kind 24242 upload authorization event (signing is injected)."""
    now = created_at if created_at is not None else int(time.time())
    _ = (size, content_type)
    return {
        "kind": 24242,
        "created_at": now,
        "content": f"upload {sha256}",
        "tags": [
            ["t", "upload"],
            ["x", sha256],
            ["expiration", str(now + expiration_secs)],
        ],
    }


def build_mirror_event(
    sha256: str,
    blob_url: str,
    *,
    created_at: int | None = None,
    expiration_secs: int = 300,
) -> dict:
    """Unsigned kind 24242 mirror authorization event (signing is injected)."""
    now = created_at if created_at is not None else int(time.time())
    _ = blob_url
    return {
        "kind": 24242,
        "created_at": now,
        "content": f"mirror {sha256}",
        "tags": [
            # BUD-04/BUD-11: PUT /mirror is authorized with an 'upload' token; 'mirror'
            # is not a BUD-11 verb and standard servers reject it with 401
            ["t", "upload"],
            ["x", sha256],
            ["expiration", str(now + expiration_secs)],
        ],
    }


def encode_auth_header(signed_event: dict) -> str:
    """Encode a signed event as a Nostr Authorization header value."""
    raw = json.dumps(signed_event, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "Nostr " + base64.b64encode(raw).decode("ascii")


def _origin(url: str) -> str:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    default = {"http": 80, "https": 443}.get(scheme)
    if port is None or port == default:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _is_allowlisted(server_url: str, allow_list: Sequence[str] | None) -> bool:
    if not allow_list:
        return False
    try:
        want = _origin(server_url)
    except ValueError:
        return False
    for entry in allow_list:
        try:
            if _origin(entry) == want:
                return True
        except ValueError:
            continue
    return False


def _guard_server_url(server_url: str, allow_list: Sequence[str] | None) -> None:
    """Apply the SSRF guard unless the server origin is explicitly allow-listed."""
    if _is_allowlisted(server_url, allow_list):
        parsed = urlparse(server_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise BlossomError("invalid server URL (expected http(s) URL)")
        return
    try:
        guard_url(server_url)
    except FetchError as e:
        raise BlossomError(f"refusing blossom server URL: {e}") from None


def _client(transport: httpx.BaseTransport | None) -> httpx.Client:
    kwargs: dict = {"timeout": TIMEOUT}
    if transport is not None:
        kwargs["transport"] = transport
    return httpx.Client(**kwargs)


def _map_status(action: str, host: str, status: int) -> BlossomError:
    if status == 413:
        return BlossomError(f"blossom {action} rejected: blob too large (HTTP 413 on {host})")
    if status == 401:
        return BlossomError(f"blossom {action} rejected: server rejected authorization (HTTP 401 on {host})")
    if status == 402:
        return BlossomError(f"blossom {action} rejected: payment required (HTTP 402 on {host})")
    return BlossomError(f"blossom {action} failed: HTTP {status} on {host}")


def _descriptor_from_json(data: dict, *, fallback_url: str, sha256: str, size: int, content_type: str) -> BlobDescriptor:
    url = str(data.get("url") or fallback_url)
    return BlobDescriptor(
        url=url,
        sha256=str(data.get("sha256") or sha256),
        size=int(data.get("size", size)),
        type=str(data.get("type") or content_type),
    )


def preflight_upload(
    server_url: str,
    sha256: str,
    size: int,
    content_type: str,
    *,
    transport: httpx.BaseTransport | None = None,
    allow_list: Sequence[str] | None = None,
    auth_header: str | None = None,
) -> bool:
    """BUD-06 preflight: True when the server accepts the upload, False when it has no
    HEAD /upload (404/405, skip). A refusal (401/402/403/413) raises BlossomError so the
    body is never sent; BUD-11 requires the same 'upload' token as the PUT itself.
    """
    _guard_server_url(server_url, allow_list)
    base = server_url.rstrip("/")
    host = urlparse(server_url).hostname or server_url
    try:
        with _client(transport) as client:
            resp = client.head(
                f"{base}/upload",
                headers={
                    "X-SHA-256": sha256,
                    "X-Content-Length": str(size),
                    "X-Content-Type": content_type,
                    **({"Authorization": auth_header} if auth_header else {}),
                },
            )
    except (httpx.TransportError, httpx.TimeoutException) as e:
        raise BlossomError(f"blossom preflight failed: network error contacting {host}") from e
    if resp.status_code in (404, 405):
        return False
    if resp.status_code in (401, 402, 403, 413):
        raise _map_status("upload", host, resp.status_code)
    return True


def verify_blob(
    server_url: str,
    sha256: str,
    *,
    transport: httpx.BaseTransport | None = None,
    allow_list: Sequence[str] | None = None,
) -> bool:
    """BUD-01: True when HEAD /<sha256> answers 200, False on 404."""
    _guard_server_url(server_url, allow_list)
    base = server_url.rstrip("/")
    host = urlparse(server_url).hostname or server_url
    try:
        with _client(transport) as client:
            resp = client.head(f"{base}/{sha256}")
    except (httpx.TransportError, httpx.TimeoutException) as e:
        raise BlossomError(f"blossom verify failed: network error contacting {host}") from e
    if resp.status_code == 200:
        return True
    if resp.status_code == 404:
        return False
    raise _map_status("verify", host, resp.status_code)


def upload_blob(
    data: bytes,
    content_type: str,
    server_url: str,
    sign_event: SignFunc,
    *,
    transport: httpx.BaseTransport | None = None,
    allow_list: Sequence[str] | None = None,
    expiration_secs: int = 300,
) -> BlobDescriptor:
    """BUD-02 upload with BUD-06 preflight when supported. Returns a descriptor."""
    _guard_server_url(server_url, allow_list)
    base = server_url.rstrip("/")
    host = urlparse(server_url).hostname or server_url
    sha = sha256_bytes(data)
    size = len(data)

    unsigned = build_upload_event(sha, size, content_type, expiration_secs=expiration_secs)
    signed = sign_event(unsigned)
    if not isinstance(signed, dict):
        raise BlossomError("blossom upload failed: signer returned no event")
    # raises on a refusal, so a too large or unpaid blob is never sent
    preflight_upload(
        server_url, sha, size, content_type, transport=transport, allow_list=allow_list,
        auth_header=encode_auth_header(signed),
    )
    try:
        with _client(transport) as client:
            resp = client.put(
                f"{base}/upload",
                content=data,
                headers={
                    "Authorization": encode_auth_header(signed),
                    "Content-Type": content_type,
                },
            )
    except (httpx.TransportError, httpx.TimeoutException) as e:
        raise BlossomError(f"blossom upload failed: network error contacting {host}") from e
    if resp.status_code not in (200, 201):
        raise _map_status("upload", host, resp.status_code)
    try:
        payload = resp.json()
    except ValueError as e:
        raise BlossomError(f"blossom upload failed: invalid server response on {host}") from e
    if not isinstance(payload, dict):
        raise BlossomError(f"blossom upload failed: invalid server response on {host}")
    return _descriptor_from_json(payload, fallback_url=f"{base}/{sha}", sha256=sha, size=size, content_type=content_type)


def mirror_blob(
    sha256: str,
    blob_url: str,
    target_server: str,
    sign_event: SignFunc,
    *,
    transport: httpx.BaseTransport | None = None,
    allow_list: Sequence[str] | None = None,
    expiration_secs: int = 300,
) -> BlobDescriptor:
    """BUD-04: ask target_server to mirror blob_url. Raises BlossomError on failure."""
    _guard_server_url(target_server, allow_list)
    _guard_server_url(blob_url, allow_list)
    base = target_server.rstrip("/")
    host = urlparse(target_server).hostname or target_server
    unsigned = build_mirror_event(sha256, blob_url, expiration_secs=expiration_secs)
    signed = sign_event(unsigned)
    if not isinstance(signed, dict):
        raise BlossomError("blossom mirror failed: signer returned no event")
    try:
        with _client(transport) as client:
            resp = client.put(
                f"{base}/mirror",
                json={"url": blob_url},
                headers={"Authorization": encode_auth_header(signed)},
            )
    except (httpx.TransportError, httpx.TimeoutException) as e:
        raise BlossomError(f"blossom mirror failed: network error contacting {host}") from e
    if resp.status_code not in (200, 201):
        raise _map_status("mirror", host, resp.status_code)
    try:
        payload = resp.json()
    except ValueError as e:
        raise BlossomError(f"blossom mirror failed: invalid server response on {host}") from e
    if not isinstance(payload, dict):
        raise BlossomError(f"blossom mirror failed: invalid server response on {host}")
    return _descriptor_from_json(payload, fallback_url=blob_url, sha256=sha256, size=0, content_type="")


def mirror_to_servers(
    sha256: str,
    blob_url: str,
    servers: Sequence[str],
    sign_event: SignFunc,
    *,
    transport: httpx.BaseTransport | None = None,
    allow_list: Sequence[str] | None = None,
    expiration_secs: int = 300,
) -> list[MirrorOutcome]:
    """Mirror to each server; one server failing never fails the others."""
    outcomes: list[MirrorOutcome] = []
    for server in servers:
        try:
            desc = mirror_blob(
                sha256,
                blob_url,
                server,
                sign_event,
                transport=transport,
                allow_list=allow_list,
                expiration_secs=expiration_secs,
            )
            outcomes.append(MirrorOutcome(server=server, descriptor=desc, error=None))
        except BlossomError as e:
            outcomes.append(MirrorOutcome(server=server, descriptor=None, error=str(e)))
    return outcomes


def upload_and_mirror(
    data: bytes,
    content_type: str,
    primary_server: str,
    mirror_servers: Sequence[str],
    sign_event: SignFunc,
    *,
    transport: httpx.BaseTransport | None = None,
    allow_list: Sequence[str] | None = None,
    expiration_secs: int = 300,
) -> tuple[BlobDescriptor, list[MirrorOutcome]]:
    """Upload to primary, then mirror elsewhere. Mirror failures do not fail the upload."""
    primary = upload_blob(
        data,
        content_type,
        primary_server,
        sign_event,
        transport=transport,
        allow_list=allow_list,
        expiration_secs=expiration_secs,
    )
    outcomes = mirror_to_servers(
        primary.sha256,
        primary.url,
        mirror_servers,
        sign_event,
        transport=transport,
        allow_list=allow_list,
        expiration_secs=expiration_secs,
    )
    return primary, outcomes
