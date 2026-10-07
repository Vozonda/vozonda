"""NIP-F4 event builders for Vozonda shows and episodes.

Pure data layer: no signing, no network. Builds unsigned Nostr events
(kind:10154 show metadata, kind:54 episodes) from Vozonda show/job dicts.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from . import __version__

_HEX_PUBKEY = re.compile(r"[0-9a-f]{64}")


def _format_source_line(i: int, s: dict[str, Any]) -> str:
    """One public source line (VOZONDA-TRAY-CITATIONS): '[n] title' plus the
    link url for link sources. Uploads and notes show by title only, never
    with text or a file name."""
    title = str(s.get("title") or "").strip()
    url = str(s.get("origin_url") or "").strip()
    if url:
        label = title if title else url
        if label == url:
            return f"[{i + 1}] {url}"
        return f"[{i + 1}] {label} — {url}"
    return f"[{i + 1}] {title or 'untitled'}"


def _sources_block(job: dict[str, Any]) -> str:
    """The public 'Sources:' list for an episode event, or '' for 0-1 sources.

    From sources.job_sources (public form, no source text). A job without an
    id (never stored) falls back to its digest_sources/url fields."""
    try:
        from . import sources as _sources_mod

        ref = dict(job)
        ref.setdefault("id", "")
        raw = ref.get("digest_sources")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                ref["digest_sources"] = parsed if isinstance(parsed, list) else None
            except Exception:
                ref["digest_sources"] = None
        items = _sources_mod.job_sources(ref)
    except Exception:
        return ""
    if len(items) <= 1:
        return ""
    return "Sources:\n" + "\n".join(_format_source_line(i, s) for i, s in enumerate(items))


def build_show_event(
    show: dict[str, Any],
    podcast_pubkey: str,
    cover_image_url: str | None = None,
    website_url: str | None = None,
    language: str = "en",
    created_at: int | None = None,
) -> dict[str, Any]:
    """Build an unsigned kind:10154 show metadata event (replaceable, no d-tag).

    Args:
        show: Show dict with keys: name, author, category, description (optional)
        podcast_pubkey: Hex pubkey of the podcast's Nostr keypair
        cover_image_url: Optional Blossom URL for cover art
        website_url: Optional website/RSS feed URL
        language: BCP-47 language code (default "en")
        created_at: Unix timestamp (default now)

    Returns:
        Unsigned event dict with pubkey, created_at, kind, tags, content.
        No 'id' or 'sig' fields.
    """
    if created_at is None:
        created_at = int(time.time())

    name = show.get("name") or show.get("title") or ""
    author = show.get("author") or ""
    description = show.get("description") or ""

    tags: list[list[str]] = [
        ["title", name],
        ["description", description],
    ]

    if cover_image_url:
        tags.append(["image", cover_image_url])
    if website_url:
        tags.append(["website", website_url])
    if language:
        tags.append(["language", language])
    # a p tag names a user by pubkey (NIP-01: 32-bytes lowercase hex). The show author is
    # a display name ('Alice'), which made an invalid p tag (coordinator review 2026-10-02)
    if _HEX_PUBKEY.fullmatch(author):
        tags.append(["p", author])

    # AI disclosure tag
    tags.append(["ai", "vozonda", "generated", f"vozonda/{__version__}"])

    return {
        "pubkey": podcast_pubkey.lower(),
        "created_at": created_at,
        "kind": 10154,
        "tags": tags,
        "content": "",
    }


def build_episode_event(
    show: dict[str, Any],
    job: dict[str, Any],
    audio: list[tuple[str, str]],
    podcast_pubkey: str,
    transcript_url: str | None = None,
    chapters_url: str | None = None,
    episode_image_url: str | None = None,
    published_at: int | None = None,
    created_at: int | None = None,
) -> dict[str, Any]:
    """Build an unsigned kind:54 episode event.

    Args:
        show: Show dict with keys: name, author, category, etc.
        job: Job dict with keys: title, description, url, digest_sources,
             language, duration_ms, etc.
        audio: List of (url, mime_type) tuples, e.g. [("https://.../ep.mp3", "audio/mpeg"),
             ("https://.../ep.opus", "audio/opus")]
        podcast_pubkey: Hex pubkey of the podcast's Nostr keypair
        transcript_url: Optional Blossom URL for VTT transcript
        chapters_url: Optional Blossom URL for JSON chapters
        episode_image_url: Optional Blossom URL for episode-specific image
        published_at: Unix timestamp of original source publication (default job created_at)
        created_at: Unix timestamp for Nostr event creation (default now)

    Returns:
        Unsigned event dict with pubkey, created_at, kind, tags, content.
        No 'id' or 'sig' fields.
    """
    if created_at is None:
        created_at = int(time.time())

    # published_at defaults to job created_at or now
    if published_at is None:
        published_at = int(job.get("created_at") or time.time())

    title = job.get("title") or show.get("name") or "Untitled Episode"
    description = job.get("description") or ""
    content = description
    sources_block = _sources_block(job)
    if sources_block:
        content = f"{content}\n\n{sources_block}" if content.strip() else sources_block
    language = job.get("language") or "en"
    if language == "auto":
        language = "en"

    # duration in seconds as string
    duration_ms = job.get("duration_ms")
    duration_s = str(int(duration_ms / 1000)) if duration_ms else "0"

    tags: list[list[str]] = [
        ["title", title],
        ["duration", duration_s],
        ["published_at", str(published_at)],
        ["language", language],
    ]

    # audio tags (repeatable for multiple formats)
    for url, mime in audio:
        tags.append(["audio", url, mime])

    if episode_image_url:
        tags.append(["image", episode_image_url])
    elif show.get("image"):
        tags.append(["image", show["image"]])

    # a-tag to the show: coordinate is '10154:<podcast_pubkey>:' (empty d)
    tags.append(["a", f"10154:{podcast_pubkey.lower()}:"])

    # r-tag(s) for original source URL(s)
    if job.get("digest") and job.get("digest_sources"):
        # digest: one r-tag per source
        for src_url in job["digest_sources"]:
            if src_url:
                tags.append(["r", src_url])
    elif job.get("url"):
        tags.append(["r", job["url"]])

    # transcript tag (Podcasting 2.0 type)
    if transcript_url:
        tags.append(["transcript", transcript_url, "text/vtt"])

    # chapters tag (Podcasting 2.0 type)
    if chapters_url:
        tags.append(["chapters", chapters_url, "application/json+chapters"])

    # AI disclosure tag with model ids if available
    ai_tag = ["ai", "vozonda", "generated", f"vozonda/{__version__}"]
    # Add model ids from job meta if present
    model_ids = job.get("model_ids")
    if model_ids and isinstance(model_ids, list):
        ai_tag.extend(model_ids)
    elif job.get("model_id"):
        ai_tag.append(job["model_id"])
    tags.append(ai_tag)

    return {
        "pubkey": podcast_pubkey.lower(),
        "created_at": created_at,
        "kind": 54,
        "tags": tags,
        "content": content,
    }


def event_id(event: dict[str, Any]) -> str:
    """Compute the NIP-01 event ID (sha256 of serialized event).

    Serializes [0, pubkey, created_at, kind, tags, content] as JSON
    with no whitespace, UTF-8 encoded, then sha256 hex digest.

    Args:
        event: Unsigned or signed event dict with keys: pubkey, created_at,
               kind, tags, content

    Returns:
        64-char lowercase hex event id.
    """
    pubkey = str(event.get("pubkey", "")).lower()
    created_at = int(event.get("created_at", 0))
    kind = int(event.get("kind", 0))
    tags = event.get("tags", [])
    content = str(event.get("content", ""))

    arr = [0, pubkey, created_at, kind, tags, content]
    serialized = json.dumps(arr, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()