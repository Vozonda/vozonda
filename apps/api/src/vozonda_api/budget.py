"""Source tray budget (VOZONDA-TRAY-BUDGET, docs/plan-multisource-tray.md).

The source budget comes from the script model's context window, with a
settings override. One source of truth: no hardcoded 60_000.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# prompt reserve, output reserve (script_call's max_tokens) and the
# chars-per-token rule from the plan; the floor keeps tiny windows usable
PROMPT_RESERVE_TOKENS = 6000
OUTPUT_RESERVE_TOKENS = 16384
CHARS_PER_TOKEN = 3.5
MIN_BUDGET_CHARS = 20000
# 'auto' never goes above this, whatever the window: a 35B model writes clearly worse scripts
# from 200k+ tokens of input (middle parts get lost) and the prefill takes minutes. Longer
# material is condensed to this size instead (VOZONDA-TRAY-CONDENSE); a numeric setting can
# go higher on purpose. ~34k tokens, about twice the 60k chars that worked before (2026-10-03)
AUTO_MAX_CHARS = 120_000
# context window probe of an OpenAI-compatible provider: max_model_len from
# GET {base}/models for its model (the local vLLM reports 262144)
FALLBACK_CONTEXT_TOKENS = 32768
_MODELS_CACHE_TTL_S = 600.0

_cache: dict[tuple[str, str], tuple[float, int]] = {}


def clear_cache() -> None:
    """Forget probed context windows (tests)."""
    _cache.clear()


def _raw_setting(key: str) -> str | None:
    try:
        from .settings_store import get_setting

        val = get_setting(key)
    except Exception:
        return None
    return str(val) if val is not None else None


def _parse_models_payload(payload: object, model: str) -> int | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, list):
        return None
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("id", "")) != model:
            continue
        for key in ("max_model_len", "max_model_tokens", "context_length"):
            raw = entry.get(key)
            try:
                num = int(raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if num > 0:
                return num
        return None
    return None


def _probe_max_model_len(base: str, model: str) -> int | None:
    """max_model_len for model from GET {base}/models, else None."""
    import httpx

    url = base.rstrip("/") + "/models"
    try:
        resp = httpx.get(url, timeout=3.0)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        return _parse_models_payload(resp.json(), model)
    except Exception:
        logger.debug("models probe at %s not parseable", url, exc_info=True)
        return None


def script_model_context_tokens() -> int:
    """Context window of the first provider in providers.llm_chain().

    OpenAI-compatible providers report max_model_len via GET {base}/models,
    cached 10 minutes; unknown or unreachable means FALLBACK_CONTEXT_TOKENS.
    """
    try:
        from .providers import llm_chain

        chain = llm_chain()
    except Exception:
        return FALLBACK_CONTEXT_TOKENS
    if not chain:
        return FALLBACK_CONTEXT_TOKENS
    prov = chain[0]
    base = str(prov.get("base", "") or "")
    model = str(prov.get("model", "") or "")
    if not base.startswith(("http://", "https://")) or not model:
        return FALLBACK_CONTEXT_TOKENS
    key = (base, model)
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _MODELS_CACHE_TTL_S:
        return hit[1]
    tokens = _probe_max_model_len(base, model) or FALLBACK_CONTEXT_TOKENS
    _cache[key] = (now, tokens)
    return tokens


def computed_budget_chars(context_tokens: int | None = None) -> int:
    """Budget from a context window: window minus prompt and output reserve."""
    ctx = context_tokens if context_tokens is not None else script_model_context_tokens()
    return max(MIN_BUDGET_CHARS, int((ctx - PROMPT_RESERVE_TOKENS - OUTPUT_RESERVE_TOKENS) * CHARS_PER_TOKEN))


def source_budget_chars() -> int:
    """Effective source budget: the source.max_chars override when numeric."""
    raw = _raw_setting("source.max_chars")
    if raw is not None:
        text = raw.strip().lower()
        if text not in ("", "auto"):
            try:
                return int(float(text))
            except ValueError:
                pass
    return min(computed_budget_chars(), AUTO_MAX_CHARS)


def max_sources() -> int:
    """Effective source limit: setting source.max_sources, default 10."""
    raw = _raw_setting("source.max_sources")
    if raw is not None:
        try:
            return int(float(str(raw).strip()))
        except ValueError:
            pass
    return 10


# need-based split (VOZONDA-TRAY-ALLOCATION, docs/plan-multisource-tray.md):
# context sources are background and served last, main sources carry the episode
CONTEXT_FLOOR_CHARS = 3000


def _water_fill(lengths: list[int], budget_chars: int) -> list[int]:
    """Share budget_chars fairly: nobody gets more than its length.

    A source shorter than its fair share keeps all and its surplus is
    shared among the others. The sum never exceeds budget_chars.
    """
    n = len(lengths)
    if n == 0 or budget_chars <= 0:
        return [0] * n
    order = sorted(range(n), key=lambda i: lengths[i])
    out = [0] * n
    remaining = budget_chars
    left = n
    for pos, idx in enumerate(order):
        fair = remaining // left
        if lengths[idx] <= fair:
            out[idx] = lengths[idx]
            remaining -= lengths[idx]
            left -= 1
        else:
            rest = order[pos:]
            base = remaining // len(rest)
            extra = remaining % len(rest)
            for j, ridx in enumerate(rest):
                out[ridx] = min(lengths[ridx], base + (1 if j < extra else 0))
            break
    return out


def allocate(lengths: list[int], roles: list[str], budget: int) -> list[int]:
    """Chars kept per source, in order. First every context source gets
    min(its length, 3000); the rest goes to main sources by water-filling;
    what is left after mains goes to context sources the same way.

    A job without roles (legacy) passes all main. The sum never exceeds
    budget and a source never gets more than its length.
    """
    n = len(lengths)
    if n == 0 or budget <= 0:
        return [0] * n
    norm = [(roles[i] if i < len(roles) else "main") for i in range(n)]
    ctx = [i for i in range(n) if norm[i] == "context"]
    mains = [i for i in range(n) if norm[i] != "context"]
    alloc = [0] * n
    floor_total = sum(min(lengths[i], CONTEXT_FLOOR_CHARS) for i in ctx)
    if floor_total >= budget:
        shares = _water_fill([lengths[i] for i in ctx], budget)
        for k, i in enumerate(ctx):
            alloc[i] = shares[k]
        return alloc
    for i in ctx:
        alloc[i] = min(lengths[i], CONTEXT_FLOOR_CHARS)
    remaining = budget - floor_total
    if mains and remaining > 0:
        shares = _water_fill([lengths[i] for i in mains], remaining)
        for k, i in enumerate(mains):
            alloc[i] = shares[k]
        remaining = budget - sum(alloc)
    if ctx and remaining > 0:
        caps = [lengths[i] - alloc[i] for i in ctx]
        extra = _water_fill(caps, remaining)
        for k, i in enumerate(ctx):
            alloc[i] += extra[k]
    return alloc
