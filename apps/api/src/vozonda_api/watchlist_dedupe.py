"""Watchlist deduplication: canonical URLs and near-duplicate titles.

Prevents rendering the same story twice when it appears in multiple feeds
or when tracking parameters turn a single article into many URLs.

No network, no new dependencies. Pure stdlib.
"""

import re
import urllib.parse
from difflib import SequenceMatcher

# Tracking params to strip (exact match)
_TRACKING_PARAMS = frozenset([
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src",
])

# AMP URL patterns
_AMP_SUFFIX = re.compile(r"\.amp$", re.IGNORECASE)
_AMP_QUERY = re.compile(r"(?:^|&)amp(?:=1|&|$)", re.IGNORECASE)
_AMP_PATH = re.compile(r"/amp(?:/|$)", re.IGNORECASE)

# Title normalization: lowercase, strip non-word non-space chars, collapse whitespace
_TITLE_NORM_COLLAPSE = re.compile(r"\s+")
_TITLE_NORM_STRIP = re.compile(r"[^\w\s]")


def _numbers(normalized_title: str) -> list[str]:
    """Digit runs of a normalized title, in order ("rust 1 82" -> ["1", "82"])."""
    return re.findall(r"\d+", normalized_title)


def _normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    if not title:
        return ""
    s = title.lower()
    s = _TITLE_NORM_STRIP.sub(" ", s)
    s = _TITLE_NORM_COLLAPSE.sub(" ", s)
    s = s.strip()
    return s

# 72 hours in seconds
_72H = 72 * 3600


def canonical_url(url: str) -> str:
    """Normalize a URL for deduplication.

    Rules:
    - lowercase scheme and host
    - drop leading "www."
    - drop fragment
    - drop tracking params (utm_*, fbclid, gclid, mc_cid, mc_eid, ref, ref_src)
    - drop trailing slash (on path only)
    - map AMP variants to plain URL
    - keep all other query params in sorted order
    """
    if not url:
        return ""

    parsed = urllib.parse.urlparse(url)

    # Lowercase scheme and netloc; strip www. prefix
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    netloc = re.sub(r"^www\.", "", netloc)

    # Map AMP variants to plain URL
    path = parsed.path
    if _AMP_SUFFIX.search(path):
        path = _AMP_SUFFIX.sub("", path)
    if _AMP_PATH.search(path):
        path = _AMP_PATH.sub("/", path)

    qs = parsed.query
    if _AMP_QUERY.search(qs):
        qs = re.sub(r"(?:^|&)amp(?:=1|&|$)", "", qs)
        qs = re.sub(r"^&|&$", "", qs)

    # Drop fragment entirely
    fragment = ""

    # Parse query params, drop tracking params
    params = urllib.parse.parse_qsl(qs, keep_blank_values=True)
    filtered = []
    for k, v in params:
        k_low = k.lower()
        if k_low.startswith("utm_"):
            continue
        if k in _TRACKING_PARAMS:
            continue
        filtered.append((k, v))

    # Sort query params
    filtered.sort()
    qs_clean = urllib.parse.urlencode(filtered, doseq=False)

    # Drop trailing slash from path (root / becomes "" so urlunparse omits it)
    p = path
    if p.endswith("/") and len(p) > 1:
        p = p.rstrip("/")
    elif p == "/":
        p = ""

    return urllib.parse.urlunparse((scheme, netloc, p, parsed.params, qs_clean, fragment))


def is_duplicate(entry: dict, recent_entries: list[dict]) -> bool:
    """Check if *entry* is a duplicate of any *recent_entries*.

    An entry is a dict with keys "link", "title", and optionally "created_at"
    (float, epoch seconds).

    Duplicate if:
    - same canonical URL, or
    - normalized title diff ratio >= 0.93 and the earlier entry is within 72 h
    """
    entry_canon = canonical_url(entry.get("link") or entry.get("canonical_url") or "")
    entry_time = float(entry.get("created_at") or entry.get("first_seen") or 0)
    entry_norm = _normalize_title(entry.get("title") or entry.get("normalized_title") or "")

    for ref in recent_entries:
        ref_canon = canonical_url(ref.get("link") or ref.get("canonical_url") or "")
        ref_time = float(ref.get("created_at") or ref.get("first_seen") or 0)
        if (
            entry_canon
            and ref_canon
            and entry_canon == ref_canon
            and (not (entry_time and ref_time) or ref_time >= entry_time - _72H)
        ):
            return True
        ref_norm = _normalize_title(ref.get("title") or ref.get("normalized_title") or "")
        if _numbers(entry_norm) != _numbers(ref_norm):
            # "iOS 18" vs "iOS 19", "0.25%" vs "0.50%": a different number is a different story
            continue
        if entry_norm and ref_norm and len(entry_norm) > 2 and len(ref_norm) > 2:
            ratio = SequenceMatcher(None, entry_norm, ref_norm).ratio()
            if ratio >= 0.93 and (not (entry_time and ref_time) or ref_time >= entry_time - _72H):
                return True
    return False


def record_seen_entry(
    url: str,
    title: str,
    first_seen: float | None = None,
    job_id: str | None = None,
    watchlist_id: str | None = None,
) -> None:
    """Record a seen feed entry for cross-watchlist deduplication."""
    from .watchlist import record_seen_entry as _record

    return _record(url, title, first_seen=first_seen, job_id=job_id, watchlist_id=watchlist_id)


def prune_seen_entries(now: float | None = None, max_age_seconds: float = 72 * 3600) -> int:
    """Prune seen entries older than max_age_seconds (default 72 hours)."""
    from .watchlist import prune_seen_entries as _prune

    return _prune(now=now, max_age_seconds=max_age_seconds)


def get_seen_entries(since: float | None = None) -> list[dict]:
    """Retrieve recently seen entries across all watchlists."""
    from .watchlist import get_seen_entries as _get

    return _get(since=since)


def clear_seen_entries() -> None:
    """Clear all seen entries (for test isolation)."""
    from .watchlist import clear_seen_entries as _clear

    return _clear()