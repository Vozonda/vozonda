"""Deterministic rhythm layer: what code can guarantee, code does (2026-10-02).

The model writes the content and the roles. Measured on the bench, it does not keep a
turn plan reliably: quick reactions came out at 0 or 48 percent, never the 15-35
target, and one-sided monologues of 30-40 words followed each other. Mechanical rhythm
does not need a model:
- turns far over the speaker's longest band are split at sentence boundaries, with the
  other host reacting in between
- when quick reactions are too few, the other host reacts after a long turn with a
  varied back-channel from a short list (English and German only; other languages get
  no inserted words)
- a surprise reaction ("Wait, really?", "Huh.") only follows a turn that gives it a reason
  (a number, a question, an exclamation), never a summary, never the last two turns, never
  another surprise; a misplaced one becomes a neutral back-channel (2026-10-07)
- quick reactions the model wrote are never removed: short interjections ("mhm",
  "krass", "wie geil ist das denn") make the talk human and many styles want lots of
  them (operator decision 2026-10-02); the layer only adds and splits
Who explains what (the word share per host) stays with the model; the pipeline picks the
best of a few drafts for that. Calm styles (asmr, meditation) and styles without a quick
reaction band are left untouched. The same input and seed always give the same output.
"""

from __future__ import annotations

import random
import re

from .rhythm import QUICK_MAX, Profile

# never a bare "Mhm." (the style rules forbid it too): on TTS voices it reads as
# dismissive (podcast-studio kb/back-channels.md, listening tests v1-v3)
BACK_CHANNELS = {
    "en": ["Right.", "Huh.", "Oh, nice.", "Wait, really?", "Exactly.", "Okay.", "Oh, wow.", "Interesting.", "Sure.", "Hm, fair.", "No way."],
    "de": ["Genau.", "Echt?", "Wie geil ist das denn?", "Ach so.", "Stimmt.", "Okay.", "Krass.", "Interessant.", "Ja, klar.", "Hm, fair.", "Wirklich?"],
}
# the back-channels that signal surprise: they need something surprising before them
SURPRISE = {
    "en": {"huh", "oh wow", "wait really", "no way"},
    "de": {"echt", "wie geil ist das denn", "krass", "wirklich"},
}
_REASON = re.compile(
    r"\d|\?|!|\b(?:million|billion|thousand|hundred|percent|millionen|milliarden|tausend|hundert|prozent)\b",
    re.IGNORECASE)
_SUMMARY = re.compile(
    r"to wrap (?:this|it|things) up|to sum (?:this |it )?up|in summary|to recap|in short|bottom line"
    r"|zusammenfassend|zusammengefasst|kurz gesagt|unterm strich|um es zusammenzufassen",
    re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9\"'])")


def _words(text: str) -> int:
    return len(str(text).split())


def _quick(line: dict) -> bool:
    return _words(line["text"]) <= QUICK_MAX


def applies_to(p: Profile | None) -> bool:
    return p is not None and p.quick_share is not None and (p.hard_max is None or p.hard_max > 25)


def _max_len(p: Profile, speaker: str) -> int:
    spec = p.speakers.get(speaker)
    hi = max(b[1] for b in spec.bands) if spec else 60
    return round(hi * 1.3)


def _reactor(p: Profile, speaker: str) -> str | None:
    """Who reacts to a long turn of ``speaker``: the other main host (never a rare third)."""
    others = [h for h in p.hosts if h != speaker and h != p.rare_third]
    return others[0] if others else None


def _split_sentences(text: str, limit: int) -> list[str]:
    parts, cur = [], ""
    for sent in _SENTENCE_END.split(text.strip()):
        if cur and _words(cur) + _words(sent) > limit:
            parts.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        parts.append(cur)
    return parts


def _halves(text: str) -> list[str]:
    """Two parts split at the sentence end nearest the middle (one part if there is none)."""
    sents = _SENTENCE_END.split(text.strip())
    if len(sents) < 2:
        return [text]
    total = _words(text)
    run, best, best_k = 0, None, 1
    for k in range(1, len(sents)):
        run += _words(sents[k - 1])
        if best is None or abs(run - total / 2) < best:
            best, best_k = abs(run - total / 2), k
    return [" ".join(sents[:best_k]), " ".join(sents[best_k:])]


def _join_same_speaker(lines: list[dict]) -> list[dict]:
    out: list[dict] = []
    for ln in lines:
        if out and out[-1]["speaker"] == ln["speaker"] and not _quick(ln) and not _quick(out[-1]):
            out[-1] = {**out[-1], "text": f"{out[-1]['text']} {ln['text']}"}
        else:
            out.append(ln)
    return out


def _share(lines: list[dict]) -> float:
    return sum(1 for ln in lines if _quick(ln)) / max(1, len(lines))


def apply_rhythm_layer(lines: list[dict], p: Profile | None, language: str = "en",
                       seed: str | int = 0) -> list[dict]:
    """Return a new list of turns with the profile's mechanical rhythm enforced."""
    if not applies_to(p) or len(lines) < 6:
        return list(lines)
    assert p is not None and p.quick_share is not None
    rng = random.Random(str(seed))
    lo = p.quick_share[0]
    pool = BACK_CHANNELS.get((language or "en").split("-")[0].lower())
    last: list[str] = []

    out = _join_same_speaker([dict(ln) for ln in lines])

    def _key(text: str) -> str:
        return re.sub(r"[^\w ]", "", text).strip().lower()

    # what the hosts already say: a back-channel the model used as a turn or a turn
    # opener is not inserted again (live run: "Interessant." twice within 3 turns)
    said = {_key(ln["text"]) for ln in out if _quick(ln)}
    said |= {_key(re.split(r"[.!?,]", ln["text"], maxsplit=1)[0]) for ln in out}

    def reaction() -> str:
        assert pool
        fresh = [b for b in pool if b not in last and _key(b) not in said]
        fresh = fresh or [b for b in pool if b not in last[-4:] and _key(b) not in said] or [b for b in pool if b not in last[-4:]]
        pick = rng.choice(fresh)
        last.append(pick)
        return pick

    if not pool:  # no back-channels for this language: never split or insert
        return out
    surprise = SURPRISE.get((language or "en").split("-")[0].lower(), set())

    def interleave(ln: dict, parts: list[str]) -> list[dict]:
        """A long turn becomes its parts with the other host reacting in between."""
        who = _reactor(p, ln["speaker"])
        res: list[dict] = []
        for k, part in enumerate(parts):
            if k:
                res.append({"speaker": who, "text": reaction()})
            res.append({**ln, "text": part})
        return res

    # monologues far over the speaker's longest band: split at sentence ends
    split: list[dict] = []
    for ln in out:
        parts = _split_sentences(ln["text"], _max_len(p, ln["speaker"])) if _reactor(p, ln["speaker"]) else []
        split.extend(interleave(ln, parts) if len(parts) > 1 else [ln])
    out = split

    # too few quick reactions: the other host reacts in the middle of the longest turn
    # that has a sentence end there (a reaction after the turn would sit right before
    # that host's own next turn)
    while _share(out) < lo:
        best = None
        for i, ln in enumerate(out):
            if _quick(ln) or _words(ln["text"]) < 20 or not _reactor(p, ln["speaker"]):
                continue
            parts = _halves(ln["text"])
            if (len(parts) == 2 and min(_words(x) for x in parts) >= 6
                    and (best is None or _words(ln["text"]) > _words(out[best[0]]["text"]))):
                best = (i, parts)
        if best is None:
            break
        i, parts = best
        out[i:i + 1] = interleave(out[i], parts)
    return _place_surprises(out, pool, surprise, rng, _key)


def _is_surprise(line: dict, surprise: set[str], key) -> bool:
    return _quick(line) and key(line["text"]) in surprise


def _place_surprises(out: list[dict], pool: list[str], surprise: set[str], rng: random.Random,
                     key) -> list[dict]:
    """Swap a surprise reaction that has no reason for a neutral back-channel (same turn count)."""
    neutral = [b for b in pool if key(b) not in surprise]
    if not neutral:
        return out
    for i, ln in enumerate(out):
        if not _is_surprise(ln, surprise, key):
            continue
        prev = out[i - 1]["text"] if i else ""
        if (i >= len(out) - 2 or not _REASON.search(prev) or _SUMMARY.search(prev)
                or (i and _is_surprise(out[i - 1], surprise, key))):
            near = {key(out[j]["text"]) for j in range(max(0, i - 4), min(len(out), i + 5))}
            fresh = [b for b in neutral if key(b) not in near] or neutral
            out[i] = {**ln, "text": rng.choice(fresh)}
    return out
