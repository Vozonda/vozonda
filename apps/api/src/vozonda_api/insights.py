"""Source-Grounded Blinkist-Grade Insights extraction (DUE-077 / #262).

Produces executive_summary + key_takeaways with verbatim source_quote
attribution. The LLM is prompted to return a JSON object; a deterministic
fallback synthesizes takeaways from the source text if the LLM is down.

All quotes are verified downstream by script_lint.lint_takeaways.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .providers import llm_chain


def _repair_json(s: str) -> str | None:
    """Attempt to repair truncated JSON output from LLM token cutoff.

    Handles unclosed brackets, braces, strings, and trailing commas.
    Works for both JSON arrays and JSON objects.
    """
    s = s.strip()
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # Fix stray trailing '","' before closing brace (truncated object with dangling comma-quote)
    s = re.sub(r',\s*"\s*,\s*"\s*([}\]])', r"\1", s)
    s = re.sub(r',\s*"\s*"\s*([}\]])', r"\1", s)
    # Fix trailing comma + unclosed quote before close brace/array (e.g. '{"a":1,"}')
    s = re.sub(r',\s*""?\s*([}\]])', r"\1", s)

    stack: list[str] = []
    in_string = False
    escape = False
    i = 0
    while i < len(s):
        ch = s[i]
        if escape:
            escape = False
            i += 1
            continue
        if ch == "\\" and in_string:
            escape = True
            i += 1
            continue
        if ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch in ("{", "["):
                stack.append(ch)
            elif ch == "}":
                if stack and stack[-1] == "{":
                    stack.pop()
                else:
                    return None
            elif ch == "]":
                if stack and stack[-1] == "[":
                    stack.pop()
                else:
                    return None
        i += 1

    if in_string:
        for ci in range(len(s) - 1, -1, -1):
            if s[ci] == '"':
                closings = "".join("]" if ch == "[" else "}" for ch in reversed(stack))
                s = s + '"' + closings
                return s
        return None

    while stack:
        open_ch = stack.pop()
        if open_ch == "{":
            s += "}"
        elif open_ch == "[":
            s += "]"

    return s


def _heuristic_takeaways(source_text: str, max_items: int = 4) -> tuple[str, str, list[dict[str, Any]]]:
    """Fallback when LLM is unavailable: extract sentences as takeaways."""
    # split into sentences; naive but deterministic
    sents = re.split(r"(?<=[.!?])\s+", source_text.strip())
    sents = [s.strip() for s in sents if len(s.strip().split()) >= 8]
    # score by length + keyword density (longer = more content)
    scored = sorted(sents, key=lambda s: len(s.split()), reverse=True)
    chosen = scored[:max_items] if scored else [source_text[:200]]
    # executive: first sentence capped
    exec_text = (sents[0] if sents else source_text[:180]).strip()
    if len(exec_text.split()) > 40:
        exec_text = " ".join(exec_text.split()[:30])
    exec_quote = chosen[0][:220] if chosen else exec_text[:220]
    takeaways: list[dict[str, Any]] = []
    for i, sent in enumerate(chosen[:max_items]):
        title = " ".join(sent.split()[:5]).rstrip(".,;:")[:40]
        if not title:
            title = f"Insight {i+1}"
        # ensure title is not filler
        text = sent.strip()
        if len(text.split()) > 30:
            text = " ".join(text.split()[:30])
        # source_quote is the sentence itself (verbatim)
        quote = sent.strip()[:300]
        takeaways.append({
            "id": f"t{i+1}",
            "title": title[:60],
            "text": text[:400],
            "source_quote": quote[:400],
            "section_idx": i,
        })
    return exec_text, exec_quote, takeaways


def _parse_insights_json(raw: str) -> tuple[str, str, list[dict[str, Any]]]:
    """Parse LLM JSON for insights. Supports object or array wrapper.

    On token cutoff (truncated JSON), attempts repair via _repair_json().
    """
    # strip thinking tags
    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw).strip()
    # find first JSON object
    start = raw.find("{")
    if start == -1:
        # Try JSON array wrapper as fallback (some models return [ {...}, ... ])
        start = raw.find("[")
        if start == -1:
            raise ValueError("no JSON object in output")
    try:
        obj, _end = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError:
        repaired = _repair_json(raw[start:])
        if repaired is None:
            raise ValueError("invalid JSON") from None
        try:
            obj, _end = json.JSONDecoder().raw_decode(repaired)
        except json.JSONDecodeError:
            raise ValueError("invalid JSON") from None
    if isinstance(obj, list):
        # array of takeaways: pick the first one as the "summary" item
        if not obj:
            raise ValueError("empty insights array")
        item = obj[0]
        if isinstance(item, dict) and "executive_summary" in item:
            obj = item  # first item is itself the insights object
        else:
            # wrap the array items into a single object structure
            obj = {
                "executive_summary": str(item.get("summary", item.get("title", ""))),
                "executive_quote": str(item.get("source_quote", item.get("quote", ""))),
                "key_takeaways": obj,
            }
    elif not isinstance(obj, dict):
        raise ValueError("insights JSON must be an object")  # noqa: TRY004
    exec_text = str(obj.get("executive_summary") or obj.get("summary") or "").strip()
    exec_quote = str(obj.get("executive_quote") or obj.get("executive_source_quote") or "").strip()
    raw_tk = obj.get("key_takeaways") or obj.get("takeaways") or []
    if not isinstance(raw_tk, list):
        raise ValueError("key_takeaways must be a list")  # noqa: TRY004
    takeaways: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_tk[:5]):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        text = str(item.get("text", "")).strip()
        quote = str(item.get("source_quote", "") or item.get("quote", "")).strip()
        if not title and text:
            title = " ".join(text.split()[:5])[:40]
        if not text:
            continue
        # enforce chain-of-density: truncate long filler
        if len(text.split()) > 45:
            text = " ".join(text.split()[:40])
        takeaways.append({
            "id": str(item.get("id", f"t{idx+1}")).strip()[:10] or f"t{idx+1}",
            "title": title[:80] or f"Insight {idx+1}",
            "text": text[:500],
            "source_quote": quote[:400],
            "section_idx": int(item.get("section_idx", idx)) if str(item.get("section_idx", "")).lstrip("-").isdigit() else idx,
        })
    if not exec_text:
        raise ValueError("missing executive_summary")
    return exec_text[:500], exec_quote[:400], takeaways


INSIGHTS_PROMPT_TEMPLATE = """You extract Blinkist-grade insights from the source text.

Rules (mandatory):
- executive_summary: 1 to 2 sentences, dense, no filler. Max 40 words. No meta-language like "This article discusses" or "The author states".
- For EACH key_takeaway you MUST provide:
  - title: punchy headline, 3 to 7 words, no filler, no quotes.
  - text: 1 to 2 sentences, dense insight answering "what exactly did I learn?", max 35 words. No meta-language. No "This article says".
  - source_quote: VERBATIM excerpt from the source text (15 to 40 words) that proves this takeaway. Copy exactly, character-for-character, including punctuation. Do NOT invent or paraphrase.
  - section_idx: 0-based index estimating where in the source the point appears.
- Produce 3 to 5 takeaways.
- Output ONLY JSON, no markdown, no explanation. Wrap in { and }.
- JSON schema:
{
  "executive_summary": "...",
  "executive_quote": "verbatim excerpt - 15 to 40 words",
  "key_takeaways": [
    {"id":"t1","title":"...","text":"...","source_quote":"verbatim ...","section_idx":0},
    {"id":"t2","title":"...","text":"...","source_quote":"verbatim ...","section_idx":1}
  ]
}

Source text (verbatim, use it for quotes):
---
{body}
---

Now output the JSON object.
"""


async def _call_llm(prompt: str) -> str:
    """Try each provider in llm_chain until one returns content."""
    errors: list[str] = []
    for prov in llm_chain():
        try:
            # reuse providers.script.script_call_nonstreaming-style via _chat_completion
            from .pipeline import _chat_completion  # local import to avoid cycle

            content = await _chat_completion(prov, prompt, max_tokens=4096)
            content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
            if content:
                return content
        except Exception as exc:
            errors.append(f"{prov.get('name','?')}: {exc}")
    raise RuntimeError("all insight extractors failed | " + " ; ".join(errors))


async def extract_insights(
    body: str,
    style: str = "balanced",
    language: str = "auto",
) -> tuple[str, str, list[dict[str, Any]]]:
    """Extract executive_summary, executive_quote, key_takeaways with source attribution.

    Returns (executive_summary, executive_quote, takeaways).
    Falls back to heuristic extraction if LLM fails.
    """
    # truncate body for prompt fit
    truncated = body[:6000] if len(body) > 6000 else body
    prompt = INSIGHTS_PROMPT_TEMPLATE.replace("{body}", truncated)
    # language hint
    if language and language != "auto":
        lang_map = {
            "en": "English", "de": "German", "es": "Spanish", "fr": "French",
            "it": "Italian", "pt": "Portuguese", "ru": "Russian",
            "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
        }
        lang_name = lang_map.get(language, language)
        prompt = f"Write the entire output in {lang_name}.\n" + prompt
    try:
        raw = await _call_llm(prompt)
        exec_text, exec_quote, tks = _parse_insights_json(raw)
        # ensure quotes are not empty - if empty, try to fill from source
        for tk in tks:
            if not tk.get("source_quote"):
                # fill with first matching sentence heuristic
                _h_exec, h_quote, _ = _heuristic_takeaways(truncated, max_items=1)
                tk["source_quote"] = h_quote
        if not exec_quote:
            _, h_q, _ = _heuristic_takeaways(truncated, max_items=1)
            exec_quote = h_q
        return exec_text, exec_quote, tks
    except Exception:
        # deterministic fallback: heuristic extraction is always grounded
        return _heuristic_takeaways(body)
