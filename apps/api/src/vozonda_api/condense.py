"""Condense an oversized source to its budget share (VOZONDA-TRAY-CONDENSE).

A source longer than its share is rewritten section by section, not cut: the
text is split at paragraph boundaries into chunks of about CHUNK_CHARS, the
script model rewrites each chunk to its proportional share of target_chars
(claims, numbers, names, dates and short direct quotes kept, in the source
language, no commentary), and the parts are joined. A model rewrite that still
overshoots is cut at a paragraph boundary. When no script model answers, the
text gets the old cut to target_chars instead and the caller is told so via the
fallback flag, so the job can record it on the extract stage.

The model is reached through providers.llm_chain(), so a LOCAL_ONLY episode
(an uploaded file without cloud permission) condenses on the local model only.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# a chunk fits one script-model call with room to spare for the prompt
CHUNK_CHARS = 12000


def split_chunks(text: str, chunk_chars: int = CHUNK_CHARS) -> list[str]:
    """Split text at paragraph boundaries into chunks of about chunk_chars.

    Whole paragraphs only: a chunk never ends mid-paragraph (a single
    paragraph longer than chunk_chars stands alone and overshoots).
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if not paras:
        return [text] if text.strip() else []
    chunks: list[str] = []
    current: list[str] = []
    cur_len = 0
    for para in paras:
        add = len(para) + (2 if current else 0)
        if current and cur_len + add > chunk_chars:
            chunks.append("\n\n".join(current))
            current = []
            cur_len = 0
        current.append(para)
        cur_len += len(para) + (2 if len(current) > 1 else 0)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def cut_at_paragraph(text: str, target_chars: int) -> str:
    """Cut text to target_chars, preferring a paragraph boundary at or before it."""
    if len(text) <= target_chars:
        return text
    if target_chars <= 0:
        return ""
    window = text[:target_chars]
    for sep in ("\n\n", "\n"):
        idx = window.rfind(sep)
        if idx > 0:
            return window[:idx]
    return window


def _condense_prompt(chunk: str, share: int, language: str | None) -> str:
    if language and language != "auto":
        lang_bit = f'in {language}'
    else:
        lang_bit = "in the same language as the source text"
    return (
        f"Condense the following source section to about {share} characters "
        f"(it is currently about {len(chunk)} characters). Keep every claim, "
        f"number, name and date, and keep short direct quotes verbatim. Write "
        f"{lang_bit}. Output ONLY the condensed text: no commentary, no "
        f"headings, no bullet lists.\n\nSource section:\n{chunk}"
    )


async def condense_with_flag(
    text: str, target_chars: int, language: str | None = None
) -> tuple[str, bool]:
    """Rewrite text down to target_chars. Returns (text, fallback_cut).

    fallback_cut is True when no script model answered and the text got the
    old cut to target_chars instead.
    """
    if len(text) <= target_chars:
        return text, False
    if target_chars <= 0:
        return "", True
    chunks = split_chunks(text)
    total = len(text)
    shares: list[int] = []
    acc = 0
    for i, chunk in enumerate(chunks):
        if i == len(chunks) - 1:
            shares.append(max(0, target_chars - acc))
        else:
            share = max(1, round(len(chunk) / total * target_chars))
            share = min(share, max(0, target_chars - acc))
            shares.append(share)
            acc += share
    try:
        from .providers import llm_chain
    except Exception:
        logger.warning("condense: no provider chain, cutting instead")
        return text[:target_chars], True
    try:
        chain = llm_chain()
    except Exception:
        logger.warning("condense: provider chain failed, cutting instead")
        return text[:target_chars], True
    if not chain:
        logger.warning("condense: no script model available, cutting instead")
        return text[:target_chars], True
    parts: list[str] = []
    fallback = False
    for chunk, share in zip(chunks, shares):
        if len(chunk) <= share:
            parts.append(chunk)
            continue
        prompt = _condense_prompt(chunk, share, language)
        max_tokens = max(1024, min(8192, share // 3 + 512))
        rewritten: str | None = None
        for prov in chain:
            try:
                from . import pipeline as pipeline_mod

                rewritten = await pipeline_mod._chat_completion(prov, prompt, max_tokens=max_tokens)
                break
            except Exception as exc:
                logger.warning("condense: provider %s failed (%s)", prov.get("name"), type(exc).__name__)
        if not rewritten or not rewritten.strip():
            parts.append(chunk[:share])
            fallback = True
        else:
            cleaned = rewritten.strip()
            if len(cleaned) > share:
                cleaned = cut_at_paragraph(cleaned, share)
            parts.append(cleaned)
    joined = "\n\n".join(parts)
    if len(joined) > target_chars:
        joined = cut_at_paragraph(joined, target_chars)
    return joined, fallback


async def condense(text: str, target_chars: int, language: str | None = None) -> str:
    """Rewrite text down to target_chars via the script model (see condense_with_flag)."""
    out, _ = await condense_with_flag(text, target_chars, language)
    return out
