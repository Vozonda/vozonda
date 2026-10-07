"""NIP-84 Highlights (kind 9802) helpers for vozonda.

Pure helpers for Swarm Transcript Highlights:
  highlighted text -> kind 9802 event -> relay publish -> relay query

Spec: https://github.com/nostr-protocol/nips/blob/master/84.md
Kind 9802, content = highlighted text, tags include r (source url), context, p (author), alt.

All functions are stdlib-only and network-free (relay I/O done by caller).
"""

from __future__ import annotations

import re
import time
import urllib.parse
from typing import Any

HIGHLIGHT_KIND = 9802
MAX_HIGHLIGHT_LENGTH = 2000
MAX_CONTEXT_LENGTH = 5000
DEFAULT_ALT = "highlight"

_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_TRACKER_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "msclkid",
    "igshid",
}


def clean_highlight_url(url: str) -> str:
    """Strip tracker query params (utm_*, fbclid, etc.) and fragment. Best effort."""
    url = url.strip()
    if not url:
        raise ValueError("url must be non-empty")
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        raise ValueError(f"invalid url: {url!r}: {exc}") from exc
    if parsed.scheme not in ("http", "https"):
        raise ValueError("url must be http(s)")
    if not parsed.netloc:
        raise ValueError("url must have host")
    # remove tracker params
    qs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [(k, v) for k, v in qs if k not in _TRACKER_PARAMS and not k.startswith("utm_")]
    new_query = urllib.parse.urlencode(filtered, doseq=True)
    # drop fragment
    cleaned = urllib.parse.urlunparse(parsed._replace(query=new_query, fragment=""))
    return cleaned


def _normalize_hex(s: str) -> str:
    return s.strip().lower()


def build_highlight_event(
    content: str,
    source_url: str,
    *,
    context: str | None = None,
    author_pubkey: str | None = None,
    author_relay: str | None = None,
    author_role: str | None = None,
    alt: str | None = None,
    pubkey: str | None = None,
    created_at: int | None = None,
) -> dict[str, Any]:
    """Build a NIP-84 kind 9802 highlight event template (unsigned).

    Args:
        content: highlighted text (the selection). Must be non-empty, <= MAX_HIGHLIGHT_LENGTH.
        source_url: Episode/source URL -> r tag. Will be cleaned via clean_highlight_url.
        context: optional surrounding paragraph/context -> context tag.
        author_pubkey: optional original author pubkey -> p tag.
        author_relay: optional relay hint for p tag.
        author_role: optional role (author/editor). Appended as 4th element.
        alt: optional alt description. Defaults to "highlight".
        pubkey: optional pubkey of the highlighter (signer). Validated if given.
        created_at: optional unix seconds. Defaults to now.

    Returns dict with kind, content, tags, created_at, pubkey (if given).
    Caller must sign via NIP-07 / Amber (window.nostr.signEvent).

    Tags constructed:
        ["r", "<cleaned_url>"]
        ["alt", "<alt>"]
        ["context", "<context>"]  (if provided)
        ["p", "<author_hex>", "<relay>", "<role>"] (if provided)
    """
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be non-empty highlighted text")
    trimmed = content.strip()
    if len(trimmed) > MAX_HIGHLIGHT_LENGTH:
        raise ValueError(f"content too long (max {MAX_HIGHLIGHT_LENGTH})")
    if not isinstance(source_url, str) or not source_url.strip():
        raise ValueError("source_url must be non-empty")
    cleaned_url = clean_highlight_url(source_url)

    # context validation
    if context is not None:
        if not isinstance(context, str):
            raise ValueError("context must be string")
        if len(context) > MAX_CONTEXT_LENGTH:
            raise ValueError(f"context too long (max {MAX_CONTEXT_LENGTH})")
        context = context.strip()
        if not context:
            context = None

    if author_pubkey is not None:
        if not _HEX64_RE.match(author_pubkey.strip()):
            raise ValueError("author_pubkey must be 64 hex")
        author_pubkey = _normalize_hex(author_pubkey)
        if author_relay is not None and author_relay.strip():
            if not author_relay.startswith(("wss://", "https://", "ws://")):
                raise ValueError(f"invalid author relay: {author_relay!r}")
            author_relay = author_relay.strip()
        else:
            author_relay = ""

    if pubkey is not None:
        if not _HEX64_RE.match(pubkey.strip()):
            raise ValueError("pubkey must be 64 hex")
        pubkey = _normalize_hex(pubkey)

    alt = (alt or DEFAULT_ALT).strip() or DEFAULT_ALT
    if len(alt) > 200:
        raise ValueError("alt too long")

    tags: list[list[str]] = [
        ["r", cleaned_url],
        ["alt", alt],
    ]
    if context:
        tags.append(["context", context])
    if author_pubkey:
        p_tag: list[str] = ["p", author_pubkey]
        # nostr spec: p tag is ["p", pubkey, relay, role]
        if author_relay is not None:
            p_tag.append(author_relay)
            if author_role:
                p_tag.append(author_role)
        elif author_role:
            # need relay placeholder if role given
            p_tag.append("")
            p_tag.append(author_role)
        tags.append(p_tag)

    event: dict[str, Any] = {
        "kind": HIGHLIGHT_KIND,
        "content": trimmed,
        "tags": tags,
        "created_at": int(created_at) if created_at is not None else int(time.time()),
    }
    if pubkey:
        event["pubkey"] = pubkey
    return event


def is_valid_highlight(event: dict[str, Any]) -> tuple[bool, str]:
    """Validate structure of a kind 9802 highlight event (signed or unsigned ok)."""
    if not isinstance(event, dict):
        return False, "event must be object"
    if event.get("kind") != HIGHLIGHT_KIND:
        return False, f"kind must be {HIGHLIGHT_KIND}"
    content = event.get("content", "")
    if not isinstance(content, str):
        return False, "content must be string"
    if not content.strip():
        return False, "content must be non-empty"
    if len(content) > MAX_HIGHLIGHT_LENGTH:
        return False, f"content too long (max {MAX_HIGHLIGHT_LENGTH})"
    tags = event.get("tags", [])
    if not isinstance(tags, list):
        return False, "tags must be array"
    # must have r tag
    r_tags = [t for t in tags if isinstance(t, list) and len(t) >= 2 and t[0] == "r"]
    if not r_tags:
        return False, "missing r tag (source url)"
    for t in r_tags:
        try:
            clean_highlight_url(t[1])
        except ValueError as e:
            return False, f"invalid r tag url: {e}"
    # must have alt
    alt_tags = [t for t in tags if isinstance(t, list) and len(t) >= 1 and t[0] == "alt"]
    if not alt_tags:
        return False, "missing alt tag"
    # context if present must be string <= MAX
    for t in tags:
        if isinstance(t, list) and t[0] == "context":
            if len(t) < 2 or not isinstance(t[1], str):
                return False, "invalid context tag"
            if len(t[1]) > MAX_CONTEXT_LENGTH:
                return False, "context too long"
    # p tags if present must be hex
    for t in tags:
        if isinstance(t, list) and t[0] == "p" and (len(t) < 2 or not isinstance(t[1], str) or not _HEX64_RE.match(t[1])):
            return False, "invalid p tag pubkey"
    # pubkey if present must be hex
    pubkey = event.get("pubkey")
    if pubkey is not None and (not isinstance(pubkey, str) or not _HEX64_RE.match(pubkey)):
        return False, "invalid pubkey"
    return True, "ok"


def parse_highlight(event: dict[str, Any]) -> dict[str, Any] | None:
    """Extract structured fields from a validated kind 9802 event. Returns None if invalid."""
    ok, _ = is_valid_highlight(event)
    if not ok:
        return None
    tags = event.get("tags", [])
    r_vals = [t[1] for t in tags if isinstance(t, list) and t[0] == "r" and len(t) >= 2]
    alt_vals = [t[1] for t in tags if isinstance(t, list) and t[0] == "alt" and len(t) >= 2]
    contexts = [t[1] for t in tags if isinstance(t, list) and t[0] == "context" and len(t) >= 2]
    p_tags = [t for t in tags if isinstance(t, list) and t[0] == "p" and len(t) >= 2]
    return {
        "id": event.get("id"),
        "pubkey": event.get("pubkey"),
        "content": event.get("content"),
        "source_url": r_vals[0] if r_vals else None,
        "r_tags": r_vals,
        "alt": alt_vals[0] if alt_vals else None,
        "context": contexts[0] if contexts else None,
        "author_pubkeys": [t[1].lower() for t in p_tags],
        "p_tags": p_tags,
        "created_at": event.get("created_at"),
        "tags": tags,
    }


def build_highlight_filter(source_url: str, limit: int = 100) -> dict[str, Any]:
    """Build a relay REQ filter for kind 9802 highlights for a given episode_url."""
    if not source_url or not source_url.strip():
        raise ValueError("source_url required")
    cleaned = clean_highlight_url(source_url)
    if limit <= 0 or limit > 500:
        raise ValueError("limit must be 1..500")
    return {
        "kinds": [HIGHLIGHT_KIND],
        "#r": [cleaned],
        "limit": limit,
    }


def highlight_kind() -> int:
    return HIGHLIGHT_KIND


def get_highlight_sources(event: dict[str, Any]) -> list[str]:
    """Return all r tag values from a highlight."""
    tags = event.get("tags", []) if isinstance(event.get("tags"), list) else []
    return [t[1] for t in tags if isinstance(t, list) and t[0] == "r" and len(t) >= 2]


def get_highlight_alt(event: dict[str, Any]) -> str | None:
    for t in event.get("tags", []) if isinstance(event.get("tags"), list) else []:
        if isinstance(t, list) and t[0] == "alt" and len(t) >= 2:
            return str(t[1])
    return None
