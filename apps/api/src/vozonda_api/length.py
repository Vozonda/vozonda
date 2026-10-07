"""Precise episode length control (VOZONDA-LEN-1).

Pure functions only: minutes to word budget per TTS engine, source grounding
caps, turn-range derivation, deviation checks, outline budget splits and the
rolling words-per-minute calibration. No I/O, no settings imports; callers
pass settings as plain dicts so this stays trivially testable.
"""

from __future__ import annotations

import math

DEFAULT_WPM = 160.0
DEFAULT_MINUTES = 8.0
MIN_MINUTES = 1.0
MAX_MINUTES = 60.0

# Above this many planned words a single-pass script drifts; generate from an
# outline of per-section budgets instead.
OUTLINE_THRESHOLD_WORDS = 2400
SECTION_WORDS_MAX = 1200

# A source carries roughly this many spoken words per minute of episode; a
# thinner source must be capped, never padded with invented material.
WORDS_PER_SOURCE_MINUTE = 110
MIN_SOURCE_MINUTES = 3.0

# UI presets: NotebookLM parity, but as minutes into a continuous control.
LENGTH_PRESETS: dict[str, float] = {"short": 3.0, "default": 8.0, "long": 15.0}


def resolve_target_minutes(
    target_minutes: float | None = None,
    length: str | None = None,
    default_minutes: float = DEFAULT_MINUTES,
) -> float:
    """Resolve explicit minutes or a preset name to a validated minute target."""
    if target_minutes is not None:
        minutes = float(target_minutes)
    elif length is not None:
        preset = str(length).strip().lower()
        if preset not in LENGTH_PRESETS:
            raise ValueError(f"length must be one of {sorted(LENGTH_PRESETS)}, got {length!r}")
        minutes = LENGTH_PRESETS[preset]
    else:
        minutes = float(default_minutes)
    if not (MIN_MINUTES <= minutes <= MAX_MINUTES):
        raise ValueError(f"target_minutes must be between {MIN_MINUTES:g} and {MAX_MINUTES:g}, got {minutes:g}")
    return minutes


def measured_wpm(engine: str, settings: dict | None = None, language: str | None = None) -> float:
    """Words per minute for an engine: the calibrated setting when present.

    Falls back in order: tts.wpm.<engine>.<lang> > tts.wpm.<engine> > DEFAULT_WPM.
    """
    if settings:
        if language:
            lang_key = f"tts.wpm.{engine}.{language.lower()}"
            raw = settings.get(lang_key)
            if raw:
                try:
                    return float(raw)
                except (TypeError, ValueError):
                    pass
        raw = settings.get(f"tts.wpm.{engine}")
        if raw:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    return DEFAULT_WPM


def word_budget(target_minutes: float, engine: str, settings: dict | None = None, language: str | None = None) -> int:
    """Planned spoken words for a target length on a given TTS engine."""
    return max(1, round(float(target_minutes) * measured_wpm(engine, settings, language)))


def max_minutes_for_source(source_words: float) -> float:
    """Grounding cap: a source only carries so many minutes of episode."""
    return max(MIN_SOURCE_MINUTES, float(source_words) / WORDS_PER_SOURCE_MINUTE)


def cap_target_minutes(target_minutes: float, source_words: float) -> tuple[float, bool]:
    """Clamp the target to what the source supports; (minutes, was_capped)."""
    cap = max_minutes_for_source(source_words)
    if float(target_minutes) > cap:
        return cap, True
    return float(target_minutes), False


def turn_target_for_budget(words: int, turn_words_max: int) -> int:
    """Turns for a word budget at a full average turn (three quarters of the max).

    Bench round 2 (2026-09-23): a wide window derived from the MAX turn size
    let the model meet the turn count with ~5-word fragments (s5: 273 turns
    of 4.5 words); a turn count built on a realistic average keeps turns full.
    """
    full = max(1, int(turn_words_max)) * 0.75
    # one turn in five is a quick reaction of ~3 words (budget_prompt_line);
    # counting them keeps the full turns full instead of squeezing all turns
    # into one length band (bench round 3: CV 0.09)
    avg = max(8, round(0.8 * full + 0.2 * 3))
    return max(4, round(words / avg))


def turn_range_for_budget(words: int, turn_words_max: int) -> tuple[int, int]:
    """T1/T2: a tight +-15 percent window around the turn target."""
    t = turn_target_for_budget(words, turn_words_max)
    return max(4, math.floor(t * 0.85)), max(4, math.ceil(t * 1.15))


def budget_prompt_line(words: int, turn_words_max: int, contract: bool = False) -> str:
    """The rule-block sentences that replace the fixed turn range.

    ``contract``: the style's output contract carries the turn lengths and the
    word split, so the sentence names only the total (the generic length
    description contradicted styles like asmr)."""
    if contract:
        return f"Write about {words} words (plus or minus 10 percent)."
    t = turn_target_for_budget(words, turn_words_max)
    t1, t2 = turn_range_for_budget(words, turn_words_max)
    twm = max(1, int(turn_words_max))
    long_max = long_turn_max(twm)
    return (
        f"Write about {words} words (plus or minus 10 percent) in about {t} turns ({t1} to {t2} turns). "
        "Vary turn length the way real talk does: about one turn in five is a quick reaction of one to "
        "five words, most turns are one to three sentences, and when a host explains a mechanism, tells "
        f"an example or builds a comparison, that turn runs long, {twm} to {long_max} words. Never give "
        "many turns in a row the same length, and never split one thought across several tiny turns."
    )


def long_turn_max(turn_words_max: int) -> int:
    """Upper bound for the long explaining turns (bench round 3: a single 25-45
    word band made every turn 24-29 words, turn length CV 0.09)."""
    return round(max(1, int(turn_words_max)) * 1.6)


def deviation_percent(actual_words: float, planned_words: float) -> float:
    if not planned_words:
        return 0.0
    return (float(actual_words) - float(planned_words)) / float(planned_words) * 100.0


def correction_action(
    actual_words: float, planned_words: float, tolerance: float = 0.15
) -> str | None:
    """'expand' or 'condense' when outside +-tolerance of the budget, else None."""
    if not planned_words:
        return None
    dev = (float(actual_words) - float(planned_words)) / float(planned_words)
    if dev > tolerance:
        return "condense"
    if dev < -tolerance:
        return "expand"
    return None


def outline_split(total_words: int, section_max: int = SECTION_WORDS_MAX) -> list[int]:
    """Split a word budget into near-equal per-section budgets summing to it."""
    total = max(1, int(total_words))
    n = max(1, math.ceil(total / max(1, section_max)))
    base = total // n
    rem = total - base * n
    return [base + (1 if i < rem else 0) for i in range(n)]


def rolling_wpm(old_wpm: float, new_wpm: float, weight: float = 0.2) -> float:
    """Rolling average: the fresh measurement weighs `weight`, history the rest."""
    return round(float(old_wpm) * (1.0 - weight) + float(new_wpm) * weight, 2)
