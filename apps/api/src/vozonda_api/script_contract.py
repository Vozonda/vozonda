"""Output contract and targeted role repair (2026-10-02, replaces the per-turn TURN PLAN).

A/B on the 35B (s2/s3/s4, three runs each): the JSON skeleton of a per-turn plan gave
no JSON at all in six of nine runs and the right role split in none; an output contract
up front (roles with their word shares, the podcast-studio pattern) plus a one-line
reminder after the source text gave valid scripts in nine of nine and, with the
deterministic rhythm layer, the profile in seven of nine. Instructions in the middle
of a long prompt are followed worst, so the contract opens the prompt and the reminder
closes it.

When a host still ends up too quiet (German sources, 2 of 3 runs), the repair is
partly deterministic, like podcast-studio's coherence pass: code picks the few
longest explanations of the loud host and fixes who speaks; the model only rewrites
the text of those spots so that the quiet host takes over the second half.
"""

from __future__ import annotations

import re

from .rhythm import QUICK_MAX, Profile

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9\"'])")


def _pct(x: float) -> int:
    return round(x * 100)


def _typical_turn(p: Profile, host: str) -> tuple[int, int]:
    """The band a host's turns mostly fall in (largest weight, quick band excluded)."""
    bands = [b for b in p.speakers[host].bands if b[1] > QUICK_MAX] or list(p.speakers[host].bands)
    lo, hi, _ = max(bands, key=lambda b: b[2])
    return lo, hi


def contract_block(p: Profile) -> str:
    """The success criteria that open the prompt: word shares, turn lengths, rhythm."""
    hosts = [h for h in p.hosts if h != p.rare_third]
    share = "; ".join(
        f"host {h} holds {_pct(p.speakers[h].share[0])} to {_pct(p.speakers[h].share[1])} percent of the words, "
        f"in turns of mostly {_typical_turn(p, h)[0]} to {_typical_turn(p, h)[1]} words"
        for h in hosts
    )
    lines = [
        "SUCCESS CRITERIA (output contract, non-negotiable; failing one fails the task):",
        f"- Word split: {share}.",
    ]
    if p.rare_third:
        lo, hi = p.speakers[p.rare_third].share
        lines.append(f"- Host {p.rare_third} only drifts in now and then: {_pct(lo)} to {_pct(hi)} percent of the words.")
    if p.quick_share:
        lines.append(f"- {_pct(p.quick_share[0])} to {_pct(p.quick_share[1])} percent of the turns are quick "
                     f"reactions of one to {QUICK_MAX} words.")
    if p.hard_max:
        lines.append(f"- No turn is longer than {p.hard_max} words.")
    lines.append("- The roles are described under STYLE RHYTHM; the split above is those roles in numbers. "
                 "No host takes over the other's role, and no host is reduced to one-word replies.")
    lines.append("Treat everything below as guidance for HOW to meet these criteria.")
    return "\n".join(lines) + "\n\n"


def reminder_line(p: Profile) -> str:
    """One line after the source text, where the model's attention is high again."""
    hosts = [h for h in p.hosts if h != p.rare_third]
    split = ", ".join(f"{h} about {_pct(sum(p.speakers[h].share) / 2)} percent" for h in hosts)
    return f"LAST CHECK before you write the JSON: the word split meets the SUCCESS CRITERIA ({split})."


# --- targeted role repair ----------------------------------------------------

def _words(text: str) -> int:
    return len(str(text).split())


def shares(lines: list[dict]) -> dict[str, float]:
    total = sum(_words(ln["text"]) for ln in lines) or 1
    out: dict[str, float] = {}
    for ln in lines:
        out[ln["speaker"]] = out.get(ln["speaker"], 0.0) + _words(ln["text"]) / total
    return out


def quiet_host(lines: list[dict], p: Profile) -> tuple[str, str] | None:
    """(quiet, loud) when a main host is under the profile's share, else None."""
    sh = shares(lines)
    hosts = [h for h in p.hosts if h != p.rare_third]
    under = [h for h in hosts if sh.get(h, 0.0) < p.speakers[h].share[0]]
    if not under:
        return None
    quiet = min(under, key=lambda h: sh.get(h, 0.0) - p.speakers[h].share[0])
    loud = max((h for h in hosts if h != quiet), key=lambda h: sh.get(h, 0.0) - p.speakers[h].share[1])
    return quiet, loud


def repair_targets(lines: list[dict], p: Profile, max_spots: int = 4) -> list[int]:
    """Indices of the loud host's longest multi-sentence turns, enough to close the gap.

    Each spot hands about half of a turn to the quiet host; spots are taken longest
    first until the moved words would close the gap to the quiet host's minimum share."""
    qh = quiet_host(lines, p)
    if qh is None:
        return []
    quiet, loud = qh
    total = sum(_words(ln["text"]) for ln in lines) or 1
    gap = (p.speakers[quiet].share[0] - shares(lines).get(quiet, 0.0)) * total
    cands = sorted(
        (i for i, ln in enumerate(lines)
         if ln["speaker"] == loud and _words(ln["text"]) >= 30 and len(_SENTENCE_END.split(ln["text"].strip())) >= 2),
        key=lambda i: (-_words(lines[i]["text"]), i),
    )
    picked: list[int] = []
    moved = 0.0
    for i in cands:
        if len(picked) >= max_spots or moved >= gap:
            break
        picked.append(i)
        moved += _words(lines[i]["text"]) / 2
    return sorted(picked)


def repair_prompt(lines: list[dict], idx: int, quiet: str, loud: str, language_line: str = "") -> str:
    """One spot only, plain text: code fixes the speakers, the model writes two parts."""
    before = lines[max(0, idx - 2):idx]
    after = lines[idx + 1:idx + 2]
    ctx = "\n".join(f"{ln['speaker']}: {ln['text']}" for ln in before)
    nxt = "\n".join(f"{ln['speaker']}: {ln['text']}" for ln in after)
    return (
        f"{language_line}You edit one spot of a two-host podcast script. Host {loud} talks too much in this "
        f"episode and host {quiet} too little. Rewrite ONLY the turn marked TURN so that {loud} says the first "
        f"part and {quiet} picks up the thread and explains the rest in their own words, the way a co-host who "
        f"knows the topic continues a thought. Both parts are about equally long. Keep every fact of the turn "
        f"and add none. Keep the casual spoken style. Never use dash characters.\n\n"
        f"Before:\n{ctx}\n\nTURN ({loud}): {lines[idx]['text']}\n\nAfter:\n{nxt}\n\n"
        f"Answer with exactly two lines and nothing else:\n{loud}: <first part>\n{quiet}: <second part>"
    )


def parse_parts(raw: str, quiet: str, loud: str) -> list[dict] | None:
    """The two marked parts of a repair answer, on two lines or run together on one
    ("B: ... A: ..."); thinking blocks and chatter before the first marker are ignored."""
    raw = re.sub(r"<think>.*?(</think>|$)", "", raw, flags=re.DOTALL)
    marks = list(re.finditer(rf"(?:^|(?<=\s))\**({loud}|{quiet})\**\s*:\**\s*", raw, flags=re.MULTILINE))
    got: dict[str, str] = {}
    for k, m in enumerate(marks):
        end = marks[k + 1].start() if k + 1 < len(marks) else len(raw)
        text = raw[m.end():end].strip().strip('"').strip()
        if m.group(1) not in got and text:
            got[m.group(1)] = text
    if loud not in got or quiet not in got:
        return None
    return [{"speaker": loud, "text": got[loud]}, {"speaker": quiet, "text": got[quiet]}]


def accept_repair(original: dict, new: list[dict] | None, quiet: str, loud: str) -> list[dict] | None:
    """The two rewritten turns, or None when the answer breaks the spot's contract."""
    if not new or len(new) != 2:
        return None
    a, b = new
    if (a["speaker"], b["speaker"]) != (loud, quiet) or not a["text"] or not b["text"]:
        return None
    w_old, w_new = _words(original["text"]), _words(a["text"]) + _words(b["text"])
    if not (0.75 * w_old <= w_new <= 1.3 * w_old) or _words(b["text"]) < 0.3 * w_new:
        return None  # content lost or padded, or the quiet host still got only a crumb
    return [{**original, **a}, {**original, **b}]


def splice(lines: list[dict], repairs: dict[int, list[dict]]) -> list[dict]:
    out: list[dict] = []
    for i, ln in enumerate(lines):
        out.extend(repairs.get(i, [ln]))
    return out
