"""Nostr publishing orchestrator for vozonda.

Orchestrates the full publish flow for a completed job:
- Ensure the show keypair exists (generate once, never overwrite)
- Publish kind:10154 show metadata when missing or metadata changed
- Upload audio (Opus when present, else MP3), VTT transcript, and JSON chapters
  to the first accepting Blossom server, then mirror to the others
- Publish kind:54 episode event with every audio URL
- Store per-job publish state in the ``nostr_publish`` DB table

Calls happen from the pipeline as a background task after a job reaches "done";
a Nostr failure is recorded and never changes the job state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from .blossom import (
    BlobDescriptor,
    BlossomError,
    build_upload_event,
    encode_auth_header,
    preflight_upload,
    sha256_bytes,
    upload_and_mirror,
)
from .config import VOZONDA_SECRETS_DIR
from .jobs import _conn as _jobs_conn
from .nostr_publish import build_episode_event, build_show_event
from .nostr_relay import publish_async
from .podcast_key import generate_keypair, has_keypair, load_keypair, sign_event

logger = logging.getLogger(__name__)


def _read_file_bytes(path: str) -> bytes:
    """Read file bytes (for use in run_in_executor)."""
    with open(path, "rb") as f:
        return f.read()

# ---------------------------------------------------------------------------
# DB helpers for nostr_publish table
# ---------------------------------------------------------------------------

_NOSTR_PUBLISH_SCHEMA = """
CREATE TABLE IF NOT EXISTS nostr_publish (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    kind INTEGER NOT NULL,
    event_id TEXT,
    blob_url TEXT,
    relay_url TEXT,
    server_url TEXT,
    relay_ok INTEGER,
    server_ok INTEGER,
    error TEXT,
    published_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS nostr_show_meta (
    show_slug TEXT PRIMARY KEY,
    sha TEXT NOT NULL,
    event_id TEXT,
    published_at REAL NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Show metadata: re-publish kind 10154 only when what it says changed
# (review F-2, 2026-10-02: the old in-process cache forgot everything on a restart,
# hashed only name/author/category and was set even when no relay accepted)
# ---------------------------------------------------------------------------

def _show_event_sha(event: dict[str, Any]) -> str:
    """Hash of everything the show event says (kind, tags, content), not its timestamp."""
    raw = json.dumps({"kind": event.get("kind"), "tags": event.get("tags"), "content": event.get("content")},
                     sort_keys=True, ensure_ascii=False).encode("utf-8")
    return sha256_bytes(raw)


def _last_show_sha(show_slug: str) -> str | None:
    _ensure_nostr_publish_table()
    with _jobs_conn() as c:
        row = c.execute("SELECT sha FROM nostr_show_meta WHERE show_slug = ?", (show_slug,)).fetchone()
    return row[0] if row else None


def _remember_show_sha(show_slug: str, sha: str, event_id: str) -> None:
    _ensure_nostr_publish_table()
    with _jobs_conn() as c:
        c.execute(
            "INSERT INTO nostr_show_meta (show_slug, sha, event_id, published_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(show_slug) DO UPDATE SET sha = excluded.sha, event_id = excluded.event_id, "
            "published_at = excluded.published_at",
            (show_slug, sha, event_id, time.time()),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_show_config(show_slug: str) -> dict[str, Any] | None:
    """Resolve show configuration from settings for a given slug.

    Returns a dict with keys: num, nostr, name, author, category.
    """
    from .settings_store import get_setting

    try:
        idx = int(str(show_slug).lstrip("s"))
    except (ValueError, TypeError):
        return None  # not a numbered show: nothing to publish

    try:
        name = get_setting(f"show.{idx}.name") or ""
    except Exception:
        name = ""
    try:
        author = get_setting(f"show.{idx}.author") or ""
    except Exception:
        author = ""
    try:
        category = get_setting(f"show.{idx}.category") or ""
    except Exception:
        category = ""
    from .settings_store import resolve_show_nostr

    # only the show's own switch publishes; the global preset never does
    nostr = resolve_show_nostr(str(idx))

    return {"num": idx, "nostr": nostr, "name": name, "author": author, "category": category}


def _ensure_nostr_publish_table() -> None:
    """Create the nostr_publish table if it does not exist."""
    with _jobs_conn() as c:
        try:
            c.executescript(_NOSTR_PUBLISH_SCHEMA)
        except Exception:
            logger.debug("nostr_publish table init failed", exc_info=True)


def _record_publish(
    job_id: str,
    kind: int,
    event_id_val: str | None,
    blob_url: str | None = None,
    relay_url: str | None = None,
    server_url: str | None = None,
    relay_ok: bool | None = None,
    server_ok: bool | None = None,
    error: str | None = None,
    published_at: float | None = None,
) -> None:
    """Persist a Nostr publish outcome row."""
    _ensure_nostr_publish_table()
    with _jobs_conn() as c:
        c.execute(
            "INSERT INTO nostr_publish "
            "(job_id, kind, event_id, blob_url, relay_url, server_url, relay_ok, server_ok, error, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                kind,
                event_id_val,
                blob_url,
                relay_url,
                server_url,
                int(relay_ok) if relay_ok is not None else None,
                int(server_ok) if server_ok is not None else None,
                error,
                published_at or time.time(),
            ),
        )


def _load_relay_urls() -> list[str]:
    """Return a list of relay URLs from settings."""
    from .settings_store import get_setting

    raw = get_setting("nostr.relays") or ""
    if not raw:
        return []
    return [u.strip() for u in raw.split(",") if u.strip()]


def _load_blossom_servers() -> list[str]:
    """Return a list of Blossom server URLs from settings."""
    from .settings_store import get_setting

    raw = get_setting("nostr.blossom_servers") or ""
    if not raw:
        return []
    return [u.strip() for u in raw.split(",") if u.strip()]


def _audio_blob_for(job: dict[str, Any], public_base: str) -> tuple[str, str] | None:
    """Find the audio file for a job. Prefer .opus, fall back to .mp3.

    Returns (relative_path, mime_type) or None when no file is found.
    """
    media_dir = Path(VOZONDA_SECRETS_DIR).parent / "media"
    for suffix, mime in [(".opus", "audio/opus"), (".mp3", "audio/mpeg")]:
        candidate = media_dir / f"{job['id']}{suffix}"
        if candidate.exists():
            return (str(candidate), mime)
    # Fallback: check MEDIA_DIR from providers
    try:
        from .providers import MEDIA_DIR

        for suffix, mime in [(".opus", "audio/opus"), (".mp3", "audio/mpeg")]:
            candidate = MEDIA_DIR / f"{job['id']}{suffix}"
            if candidate.exists():
                return (str(candidate), mime)
    except Exception:  # silent: providers module may not be importable in test env
        pass
    return None


def _transcript_path_for(job: dict[str, Any]) -> str | None:
    """Return the path to the VTT transcript file, or None."""
    media_dirs = []
    try:
        from .providers import MEDIA_DIR

        media_dirs.append(MEDIA_DIR)
    except Exception:  # silent: providers module may not be importable in test env
        pass
    media_dirs.append(Path(VOZONDA_SECRETS_DIR).parent / "media")
    for d in media_dirs:
        candidate = d / f"{job['id']}.vtt"
        if candidate.exists():
            return str(candidate)
    return None


def _chapters_path_for(job: dict[str, Any]) -> str | None:
    """Return the path to the JSON chapters file, or None."""
    media_dirs = []
    try:
        from .providers import MEDIA_DIR

        media_dirs.append(MEDIA_DIR)
    except Exception:  # silent: providers module may not be importable in test env
        pass
    media_dirs.append(Path(VOZONDA_SECRETS_DIR).parent / "media")
    for d in media_dirs:
        candidate = d / f"{job['id']}.chapters.json"
        if candidate.exists():
            return str(candidate)
    return None


async def _ensure_show_key(show_slug: str) -> str:
    """Ensure a keypair exists for the show; generate only if missing.

    Returns the hex pubkey.
    """
    if not has_keypair(show_slug):
        try:
            generate_keypair(show_slug)
            logger.info("generated new Nostr keypair for show %s", show_slug)
        except FileExistsError:
            # Race condition: another goroutine created it between check and
            # generate. That is fine -- we just load it.
            logger.info("show %s keypair was created by another task, loading", show_slug)
    _, pubkey = load_keypair(show_slug)
    return pubkey


async def _publish_show_event(show_slug: str, show: dict[str, Any], pubkey: str) -> str | None:
    """Publish or re-publish kind:10154 show metadata.

    Checks the cache to decide if the show metadata has changed.
    Returns the event_id or None if skipped.
    """
    event = build_show_event(show, pubkey)
    new_sha = _show_event_sha(event)
    if _last_show_sha(show_slug) == new_sha:
        logger.debug("show %s metadata unchanged, skipping 10154", show_slug)
        return None

    signed = sign_event(show_slug, event)
    if not signed or not signed.get("id"):
        logger.warning("sign_event returned no id for show %s", show_slug)
        _record_publish(
            job_id="__show__",
            kind=10154,
            event_id_val=None,
            error="sign_event returned no id",
        )
        return None

    relays = _load_relay_urls()
    results = await publish_async(signed, relays)
    ok_count = sum(1 for r in results if r.ok)
    if ok_count:  # no relay took it: try again next time
        _remember_show_sha(show_slug, new_sha, signed["id"])
    _record_publish(
        job_id="__show__",
        kind=10154,
        event_id_val=signed["id"],
        relay_url=",".join(r.relay for r in results),
        relay_ok=bool(ok_count > 0),
        published_at=signed.get("created_at", 0) or time.time(),
    )
    logger.info("published show event %s (kind 10154), ok relays: %d/%d", show_slug, ok_count, len(results))
    return signed["id"]


async def _upload_blob(
    file_path: str,
    content_type: str,
    servers: list[str],
    show_slug: str,
) -> tuple[BlobDescriptor, list[Any]] | None:
    """Upload a file to the first accepting Blossom server and mirror elsewhere.

    Returns (primary_descriptor, mirror_outcomes) or None on failure.
    """
    if not servers:
        return None

    # Read file in a thread to avoid blocking the event loop
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _read_file_bytes, file_path)

    def _sign_for_upload(event: dict) -> dict:
        """Sign a Blossom upload event with the show key."""
        return sign_event(show_slug, event)

    # Find first accepting server. The preflight carries the same signed 'upload'
    # authorization as the PUT (BUD-06/BUD-11): every public server answers an unsigned
    # HEAD /upload with 401, so nothing was ever uploaded (live check 2026-10-02).
    # Blossom calls are sync httpx: run them in a thread, never on the API's event loop.
    sha = sha256_bytes(data)
    size = len(data)
    auth = encode_auth_header(_sign_for_upload(build_upload_event(sha, size, content_type)))
    primary_server = None
    for srv in servers:
        try:
            accepted = await asyncio.to_thread(preflight_upload, srv, sha, size, content_type, auth_header=auth)
            if accepted:
                primary_server = srv
                break
        except BlossomError:
            logger.debug("preflight rejected on %s, skipping", srv)
            continue
        except Exception:
            continue

    if primary_server is None:
        logger.warning("no Blossom server accepted upload for %s", file_path)
        return None

    try:
        result = await asyncio.to_thread(
            upload_and_mirror,
            data=data,
            content_type=content_type,
            primary_server=primary_server,
            mirror_servers=[s for s in servers if s != primary_server],
            sign_event=_sign_for_upload,
        )
        return result
    except BlossomError as e:
        logger.warning("upload failed: %s", e)
        _record_publish(
            job_id="__blob__",
            kind=0,
            event_id_val=None,
            server_url=primary_server,
            server_ok=False,
            error=str(e),
        )
        return None


async def _publish_episode(
    show_slug: str,
    show: dict[str, Any],
    job: dict[str, Any],
    audio_urls: list[tuple[str, str]],
    transcript_url: str | None,
    chapters_url: str | None,
    pubkey: str,
) -> str | None:
    """Build and publish a kind:54 episode event.

    Returns the event_id or None on failure.
    """
    event = build_episode_event(
        show=show,
        job=job,
        audio=audio_urls,
        podcast_pubkey=pubkey,
        transcript_url=transcript_url,
        chapters_url=chapters_url,
    )
    signed = sign_event(show_slug, event)
    if not signed or not signed.get("id"):
        logger.warning("sign_event returned no id for episode %s", job.get("id"))
        _record_publish(
            job_id=job.get("id", ""),
            kind=54,
            event_id_val=None,
            error="sign_event returned no id",
        )
        return None

    relays = _load_relay_urls()
    results = await publish_async(signed, relays)
    ok_count = sum(1 for r in results if r.ok)

    for r in results:
        _record_publish(
            job_id=job.get("id", ""),
            kind=54,
            event_id_val=signed["id"],
            relay_url=r.relay,
            relay_ok=r.ok,
            error=r.reason,
            published_at=signed.get("created_at", 0) or time.time(),
        )

    for url, _ in audio_urls:
        _record_publish(
            job_id=job.get("id", ""),
            kind=54,
            event_id_val=signed["id"],
            blob_url=url,
            published_at=signed.get("created_at", 0) or time.time(),
        )

    _record_publish(
        job_id=job.get("id", ""),
        kind=54,
        event_id_val=signed["id"],
        published_at=signed.get("created_at", 0) or time.time(),
    )

    logger.info(
        "published episode event %s (kind 54), ok relays: %d/%d",
        job.get("id"),
        ok_count,
        len(results),
    )
    return signed["id"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def publish_job(job_id: str) -> None:
    """Publish a finished episode to Nostr + Blossom.

    Only triggers when the job is "done" and its show (jobs.show_slug) has
    show.<n>.nostr == "1". A Nostr failure is recorded and never changes
    the job state.
    """
    from .jobs import JobStore

    store = JobStore()

    try:
        job = store.get(job_id)
    except KeyError:
        logger.warning("publish_job: job %s not found", job_id)
        return

    if job.get("state") != "done":
        logger.debug("publish_job: job %s is %s, skipping", job_id, job.get("state"))
        return

    show_slug = job.get("show_slug") or ""
    if not show_slug:
        logger.debug("publish_job: job %s has no show_slug, skipping", job_id)
        return

    # Check if show has nostr enabled
    cfg = _get_show_config(show_slug)
    if not cfg or cfg.get("nostr") != "1":
        logger.debug("publish_job: show %s nostr=%s, skipping", show_slug, cfg.get("nostr") if cfg else "none")
        return

    _ensure_nostr_publish_table()

    show = {
        "name": cfg.get("name", ""),
        "author": cfg.get("author", ""),
        "category": cfg.get("category", ""),
        "image": job.get("og_image") or "",
    }

    # Step 1: Ensure keypair
    try:
        pubkey = await _ensure_show_key(show_slug)
    except Exception as e:
        logger.warning("publish_job: keypair failed for show %s: %s", show_slug, e)
        _record_publish(
            job_id=job_id,
            kind=0,
            event_id_val=None,
            error=f"keypair: {e}",
        )
        return

    # Step 2: Publish show metadata (kind:10154) if changed or missing
    try:
        await _publish_show_event(show_slug, show, pubkey)
    except Exception as e:
        logger.warning("publish_job: show event publish failed for %s: %s", show_slug, e)

    # Step 3: Find audio file and upload to Blossom
    audio_blob = _audio_blob_for(job, "")
    if not audio_blob:
        logger.warning("publish_job: no audio file found for job %s", job_id)
        _record_publish(
            job_id=job_id,
            kind=0,
            event_id_val=None,
            error="no audio file found",
        )
        return

    file_path, content_type = audio_blob
    servers = _load_blossom_servers()

    audio_urls: list[tuple[str, str]] = []
    if servers:
        upload_result = await _upload_blob(file_path, content_type, servers, show_slug)
        if upload_result:
            primary, outcomes = upload_result
            audio_urls.append((primary.url, content_type))
            # the primary blob is recorded too, or a deletion would leave it behind
            from urllib.parse import urlparse as _urlparse

            _p = _urlparse(primary.url)
            _record_publish(job_id=job_id, kind=0, event_id_val=None, server_url=f"{_p.scheme}://{_p.netloc}",
                            server_ok=True, blob_url=primary.url)
            for outcome in outcomes:
                _record_publish(
                    job_id=job_id,
                    kind=0,
                    event_id_val=None,
                    server_url=outcome.server,
                    server_ok=outcome.descriptor is not None,
                    blob_url=outcome.descriptor.url if outcome.descriptor else None,
                    error=outcome.error,
                )
    else:
        logger.warning("publish_job: no blossom servers configured for job %s", job_id)

    if not audio_urls:
        # a signed episode event on public relays cannot be taken back: never send one
        # that has no audio (every Blossom upload failed, or no server configured)
        logger.warning("publish_job: no audio uploaded for job %s, episode not published", job_id)
        _record_publish(job_id=job_id, kind=54, event_id_val=None,
                        error="no audio uploaded to any Blossom server; episode not published")
        return

    # Step 4: Upload transcript and chapters
    transcript_url = None
    transcript_path = _transcript_path_for(job)
    if transcript_path and servers:
        try:
            t_result = await _upload_blob(transcript_path, "text/vtt", servers, show_slug)
            if t_result:
                transcript_url = t_result[0].url
        except Exception:
            logger.debug("publish_job: transcript upload failed", exc_info=True)

    chapters_url = None
    chapters_path = _chapters_path_for(job)
    if chapters_path and servers:
        try:
            c_result = await _upload_blob(chapters_path, "application/json", servers, show_slug)
            if c_result:
                chapters_url = c_result[0].url
        except Exception:
            logger.debug("publish_job: chapters upload failed", exc_info=True)

    # Step 5: Publish episode event (kind:54)
    try:
        await _publish_episode(show_slug, show, job, audio_urls, transcript_url, chapters_url, pubkey)
    except Exception as e:
        logger.warning("publish_job: episode publish failed for %s: %s", job_id, e)
        _record_publish(
            job_id=job_id,
            kind=54,
            event_id_val=None,
            error=f"publish: {e}",
        )


async def publish_job_async(job_id: str) -> None:
    """Async entry point for publish_job (avoids sync wrapper issues)."""
    await publish_job(job_id)


# ---------------------------------------------------------------------------
# Deletion helpers (NIP-09 kind:5, BUD-02 kind:24242 t=delete)
# ---------------------------------------------------------------------------

def _build_delete_event(show_id: str, target_event_id: str, kind: int) -> dict:
    """Build a NIP-09 kind:5 deletion event targeting a specific event id.

    Args:
        show_id: Show id (used for signing)
        target_event_id: The id of the event to delete
        kind: The kind of the event being deleted (for the deletion reason tag)

    Returns:
        Unsigned deletion event dict.
    """
    return {
        "kind": 5,
        "tags": [
            ["e", target_event_id],
            ["k", str(kind)],
        ],
        "content": "vozonda: episode or show metadata removed by the podcaster",
    }


async def _publish_delete_event(
    show_slug: str,
    job_id: str,
    target_event_id: str,
    kind: int,
) -> str | None:
    """Publish a kind:5 deletion event for a previously published Nostr event.

    Args:
        show_slug: Show slug for signing.
        job_id: The job that originally published the event (used for bookkeeping).
        target_event_id: The id of the event to delete.
        kind: The kind of the event being deleted.

    Returns the deletion event id or None on failure.
    """
    try:
        await _ensure_show_key(show_slug)
    except Exception as e:
        logger.warning("delete: keypair failed for show %s: %s", show_slug, e)
        return None

    delete_event = _build_delete_event(show_slug, target_event_id, kind)
    try:
        signed = sign_event(show_slug, delete_event)
    except Exception as e:
        logger.warning("delete: signing failed for show %s: %s", show_slug, e)
        return None

    if not signed or not signed.get("id"):
        logger.warning("delete: sign_event returned no id")
        return None

    relays = _load_relay_urls()
    if not relays:
        logger.warning("delete: no relays configured")
        return None

    results = await publish_async(signed, relays)
    ok_count = sum(1 for r in results if r.ok)
    _record_publish(
        job_id=job_id,
        kind=5,
        event_id_val=signed["id"],
        relay_url=",".join(r.relay for r in results),
        relay_ok=bool(ok_count > 0),
        published_at=signed.get("created_at", 0) or time.time(),
    )
    logger.info("published deletion event for %s (kind %d), ok relays: %d/%d",
                target_event_id, kind, ok_count, len(results))
    return signed["id"]


async def _delete_blob_on_server(
    server_url: str,
    sha256: str,
    show_slug: str,
) -> bool:
    """Send a BUD-02 DELETE to one Blossom server.

    Returns True when the server accepted the deletion.
    """
    from urllib.parse import urlparse

    from .blossom import (
        _client,
        _guard_server_url,
        encode_auth_header,
    )

    try:
        _guard_server_url(server_url, None)
    except BlossomError:
        logger.warning("delete: refusing blossom server %s (SSRF guard)", server_url)
        return False  # one refused server never stops the other deletions
    base = server_url.rstrip("/")
    host = urlparse(server_url).hostname or ""

    # BUD-11: the token MUST carry an expiration; a delete token without a server tag
    # can be replayed against every other server holding the blob, so bind it to this one
    now = int(time.time())
    auth_event = {
        "kind": 24242,
        "created_at": now,
        "content": f"delete {sha256}",
        "tags": [
            ["t", "delete"],
            ["x", sha256],
            ["expiration", str(now + 300)],
            ["server", host],
        ],
    }
    try:
        signed = sign_event(show_slug, auth_event)
    except Exception:
        logger.warning("delete: signing auth for blob on %s failed", server_url)
        return False

    def _send():
        with _client() as client:
            return client.delete(f"{base}/{sha256}", headers={"Authorization": encode_auth_header(signed)})

    try:
        resp = await asyncio.to_thread(_send)
    except Exception:
        logger.warning("delete: HTTP request to %s failed", server_url)
        return False

    if resp.status_code == 200:
        logger.info("blob %s deleted from %s", sha256[:12], server_url)
        return True
    if resp.status_code == 404:
        logger.debug("blob %s not found on %s (already deleted)", sha256[:12], server_url)
        return True  # best effort: server says it's gone
    logger.warning("delete: server %s returned %d for blob %s", server_url, resp.status_code, sha256[:12])
    return False


def _load_blob_descriptors_for_job(job_id: str) -> list[dict]:
    """Blobs recorded for a job (server_url + blob_url rows of nostr_publish).

    Blob URLs end in '<sha256>.<ext>' (BUD-01), so the hash is the 64-hex run in the
    URL, not 'everything after the last slash' (which found no blob at all)."""
    import re as _re

    try:
        _ensure_nostr_publish_table()
    except Exception:
        return []
    with _jobs_conn() as c:
        c.row_factory = __import__("sqlite3").Row
        rows = c.execute(
            "SELECT DISTINCT blob_url, server_url FROM nostr_publish WHERE job_id = ? "
            "AND blob_url IS NOT NULL AND server_url IS NOT NULL",
            (job_id,),
        ).fetchall()
    blobs: list[dict] = []
    for row in rows:
        m = _re.search(r"[0-9a-f]{64}", row["blob_url"] or "")
        if m:
            blobs.append({"blob_url": row["blob_url"], "server_url": row["server_url"], "sha256": m.group(0)})
    return blobs


def _event_ids_for_job(job_id: str) -> list[dict]:
    """Load event_ids from nostr_publish table for a job.

    Returns list of dicts with keys: kind, event_id.
    """
    try:
        _ensure_nostr_publish_table()
    except Exception:
        return []
    with _jobs_conn() as c:
        rows = c.execute(
            "SELECT kind, event_id FROM nostr_publish WHERE job_id = ? AND kind = 54 AND event_id IS NOT NULL",
            (job_id,),
        ).fetchall()
    return [{"kind": r["kind"], "event_id": r["event_id"]} for r in rows]


async def delete_published_job(job_id: str, show_slug: str | None = None) -> dict:
    """Best-effort deletion of a published Nostr job.

    Sends:
    - NIP-09 kind:5 deletion for each kind:54 event_id
    - BUD-02 DELETE (kind:24242 t=delete) for each blob on each server

    Returns a dict with deletion results.
    """
    from .jobs import JobStore

    if show_slug is None:  # the job delete passes it: the row is gone by then
        try:
            show_slug = JobStore().get(job_id).get("show_slug") or ""
        except KeyError:
            return {"error": "job not found", "job_id": job_id}
    if not show_slug:
        return {"error": "job has no show_slug", "job_id": job_id}

    results: dict = {
        "job_id": job_id,
        "deletions": [],
        "blob_deletes": [],
    }

    # Step 1: Delete kind:54 events on relays (deduplicate by event_id)
    seen_eids: set[str] = set()
    for evt in _event_ids_for_job(job_id):
        kind = evt["kind"]
        eid = evt["event_id"]
        if eid in seen_eids:
            continue
        seen_eids.add(eid)
        del_id = await _publish_delete_event(show_slug, job_id, eid, kind)
        results["deletions"].append({
            "kind": kind,
            "event_id": eid,
            "deletion_event_id": del_id,
            "status": "deleted" if del_id else "failed",
        })

    # Step 2: Delete blobs on Blossom servers (best effort)
    for blob_info in _load_blob_descriptors_for_job(job_id):
        sha = blob_info["sha256"]
        server = blob_info["server_url"]
        ok = await _delete_blob_on_server(server, sha, show_slug)
        results["blob_deletes"].append({
            "server": server,
            "sha256": sha,
            "ok": ok,
        })
        _record_publish(
            job_id=job_id,
            kind=5,
            event_id_val=None,
            server_url=server,
            server_ok=ok,
        )

    results["summary"] = {
        "events_deleted": sum(1 for d in results["deletions"] if d["status"] == "deleted"),
        "blobs_deleted": sum(1 for b in results["blob_deletes"] if b["ok"]),
    }

    logger.info("delete_published_job %s: %s", job_id, results["summary"])
    return results