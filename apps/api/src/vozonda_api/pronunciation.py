"""Pronunciation dictionary for TTS.

Stores term -> ``say`` mappings so that names, drug names, case citations,
product names, etc. are spoken correctly while the transcript and script
keep the original spelling.

Rules
-----
* ``term`` and ``say`` are 1..100 characters.
* ``match_case`` (default ``False``) controls whether the match is case
  sensitive.
* Replacement is whole-word only (``\b`` boundaries).
* Longer terms are tried first so "cooper" does not eat the "cooper"
  inside "cooperatives".
* Entries are applied in list order after the longest-first sort.

API
---
``tts.pronunciations`` – global list stored as JSON in settings_store.
``show.<N>.pronunciations`` – per-show list applied after the global one.
"""

from __future__ import annotations

import json
import re
from typing import Any


def _validate_entry(entry: Any) -> dict[str, str | bool] | None:
    """Return a cleaned entry dict or ``None`` if invalid."""
    if not isinstance(entry, dict):
        return None
    term = entry.get("term")
    say = entry.get("say")
    if not isinstance(term, str) or not isinstance(say, str):
        return None
    term = term.strip()
    say = say.strip()
    if not term or len(term) > 100:
        return None
    if not say or len(say) > 100:
        return None
    match_case = bool(entry.get("match_case", False))
    return {"term": term, "say": say, "match_case": match_case}


def validate_entries(raw: list[Any] | None) -> list[dict[str, str | bool]] | None:
    """Validate a list of pronunciation entries.

    Returns a deduplicated (by term, lowercased) list or ``None`` if the
    input is invalid (duplicates in the raw list are deduplicated by
    keeping the first occurrence).
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    if len(raw) > 500:
        return None
    seen: set[str] = set()
    result: list[dict[str, str | bool]] = []
    for entry in raw:
        cleaned = _validate_entry(entry)
        if cleaned is None:
            return None
        key = cleaned["term"].lower()
        if key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def apply_pronunciations(
    text: str, pronunciations: list[dict[str, str | bool]] | None
) -> str:
    """Replace whole-word occurrences in ``text`` according to ``pronunciations``.

    One pass over the text with every term in a single pattern, longest first, so a
    replacement is never replaced again and "Dr." or "C++" match like plain words
    (word boundaries are "no word character next to it", not ``\\b``). The ``say``
    text is inserted literally. A ``match_case`` entry matches only its own spelling.
    The original ``text`` is not mutated.
    """
    if not pronunciations or not text:
        return text
    exact = {str(e["term"]): str(e["say"]) for e in pronunciations if e.get("match_case")}
    loose = {str(e["term"]).lower(): str(e["say"]) for e in pronunciations if not e.get("match_case")}
    terms = sorted({str(e["term"]) for e in pronunciations}, key=len, reverse=True)
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(t) for t in terms) + r")(?!\w)", re.IGNORECASE)

    def _say(m: re.Match[str]) -> str:
        word = m.group(0)
        if word in exact:
            return exact[word]
        return loose.get(word.lower(), word)

    return pattern.sub(_say, text)


def apply_pronunciations_segments(
    segments: list[dict[str, Any]],
    pronunciations: list[dict[str, str | bool]] | None,
) -> list[dict[str, Any]]:
    """Apply pronunciations to a copy of ``segments``.

    Returns a new list of segment dicts with ``text`` transformed.
    The original ``segments`` list is not mutated.
    """
    if not pronunciations:
        return segments
    return [
        {**seg, "text": apply_pronunciations(seg.get("text", ""), pronunciations)}
        for seg in segments
    ]


def entries_from_global_and_show(
    get_setting: Any,
    global_key: str = "tts.pronunciations",
    show_num: str | None = None,
    show_prefix_key: str = "show",
) -> list[dict[str, str | bool]] | None:
    """Merge global and per-show pronunciation lists.

    Per-show entries (``show.<N>.pronunciations``) are applied *after*
    the global list, overwriting global terms with the same key (case
    insensitive).

    Returns the merged, validated list or ``None``.
    """
    # Load global
    global_raw = get_setting(global_key) if global_key else None
    global_entries: list[dict[str, str | bool]] = []
    if isinstance(global_raw, str):
        try:
            parsed = json.loads(global_raw)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        validated = validate_entries(parsed)
        if validated:
            global_entries = validated

    # Load per-show if show_num is provided
    if show_num is not None and show_prefix_key:
        show_key = f"{show_prefix_key}.{show_num}.pronunciations"
        show_raw = get_setting(show_key)
        if isinstance(show_raw, str):
            try:
                parsed = json.loads(show_raw)
            except (json.JSONDecodeError, TypeError):
                parsed = None
            validated = validate_entries(parsed)
            if validated:
                # Per-show entries override global by term (case-insensitive)
                global_by_term: dict[str, dict[str, str | bool]] = {
                    e["term"].lower(): e for e in global_entries
                }
                for entry in validated:
                    global_by_term[entry["term"].lower()] = entry
                global_entries = list(global_by_term.values())

    return global_entries or None
