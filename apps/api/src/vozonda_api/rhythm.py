"""Per-style rhythm profiles: who speaks how much, how long, how often briefly.

Every style has its own script shape (operator review 2026-10-02): asmr caps turns
at twelve words, socrates has A ask only questions while B's answers shrink,
storyteller is A's narration with B reacting, and even 'balanced' is a curious host
with an expert, not two equal speakers. One balanced 50/50 plan broke them, and the
model kept the template's roles anyway (balanced: one host at 10-22 percent).

A profile turns the template's roles into numbers. It drives three things:
- plan_for_profile: the per-turn TURN PLAN (speaker, words) the prompt carries
- rhythm_problems_for: the check behind the one RHYTHM CORRECTION pass
- profile_rules: the style's own lines for reactions, questions and repairs, which
  replace the shared ones that contradicted it ('about one turn in six asks a
  question' for socrates, 'mix quick reactions' for asmr)
The bench derives its per-style targets from the same profiles.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

QUICK_MAX = 5  # a turn of at most this many words is a quick reaction


@dataclass(frozen=True)
class Speaker:
    share: tuple[float, float]  # share of all words
    bands: tuple[tuple[int, int, float], ...]  # (min words, max words, weight)


@dataclass(frozen=True)
class Profile:
    speakers: dict[str, Speaker]
    quick_share: tuple[float, float] | None  # share of quick turns; None: not a feature of this style
    questions: tuple[float, float]  # share of turns with a question mark
    rules: str  # the style's own lines on reactions, questions, repairs
    hard_max: int | None = None  # no turn above this, ever
    trend: dict[str, tuple[float, float]] = field(default_factory=dict)  # speaker -> length factor start, end
    rare_third: str | None = None  # a third host who only drifts in now and then
    no_adjacent_quick: bool = True

    @property
    def hosts(self) -> str:
        return "".join(self.speakers)


def _sp(lo: float, hi: float, *bands: tuple[int, int, float]) -> Speaker:
    return Speaker((lo, hi), tuple(bands))


_EQUAL = (
    _sp(0.40, 0.60, (2, 5, 0.25), (10, 20, 0.40), (30, 60, 0.35)),
    _sp(0.40, 0.60, (2, 5, 0.25), (10, 20, 0.40), (30, 60, 0.35)),
)
_REACT = (
    "Quick reactions vary: at least three different ones, never the same one twice in a row, "
    "never a bare \"Mhm.\"."
)
_REPAIR = (
    "Once or twice in the episode {who} restarts a sentence the way people do when they find a "
    "better way to say it (\"Wait, sorry, what I mean is\", \"Let me back up\"; in German "
    "\"Moment, ich meine\", \"Also nein, eigentlich\")."
)
_HOST_EXPERT_RULES = (
    "ROLES IN NUMBERS: A asks, frames and sums up in short and medium turns but also explains one "
    "point in a longer turn now and then; B carries the long explanations and reacts briefly when A "
    "lands a point. " + _REACT + " " + _REPAIR.format(who="a host")
    + " About one turn in six is a question, mostly A's, and each gets a concrete answer."
)

PROFILES: dict[str, Profile] = {
    # equal partners
    "debate": Profile(dict(zip("AB", _EQUAL)), (0.15, 0.32), (0.10, 0.25),
                      "Both sides argue in long turns and answer each other briefly. " + _REACT + " "
                      + _REPAIR.format(who="a debater") + " About one turn in six is a question."),
    "clash": Profile(dict(zip("AB", _EQUAL)), (0.18, 0.35), (0.10, 0.30),
                     "Both fire back fast and both build long attacks; interruptions are short turns. "
                     + _REACT + " " + _REPAIR.format(who="a host")),
    "slang": Profile(dict(zip("AB", _EQUAL)), (0.18, 0.35), (0.10, 0.25),
                     "Two friends: both tell, both react. " + _REACT + " " + _REPAIR.format(who="a friend")),
    # host and expert
    "balanced": Profile({"A": _sp(0.30, 0.42, (2, 5, 0.30), (8, 18, 0.50), (25, 45, 0.20)),
                         "B": _sp(0.58, 0.70, (2, 5, 0.12), (12, 22, 0.30), (35, 65, 0.58))},
                        (0.15, 0.32), (0.10, 0.25), _HOST_EXPERT_RULES),
    "serious": Profile({"A": _sp(0.30, 0.42, (2, 5, 0.20), (10, 20, 0.60), (25, 40, 0.20)),
                        "B": _sp(0.58, 0.70, (2, 5, 0.08), (15, 25, 0.32), (35, 60, 0.60))},
                       (0.10, 0.25), (0.12, 0.28), _HOST_EXPERT_RULES),
    "sensational": Profile({"A": _sp(0.30, 0.42, (2, 5, 0.30), (8, 18, 0.50), (25, 40, 0.20)),
                            "B": _sp(0.58, 0.70, (2, 5, 0.15), (12, 22, 0.30), (30, 60, 0.55))},
                           (0.15, 0.35), (0.10, 0.25), _HOST_EXPERT_RULES),
    "tech_roast": Profile({"A": _sp(0.25, 0.40, (2, 5, 0.30), (6, 15, 0.55), (20, 35, 0.15)),
                           "B": _sp(0.60, 0.75, (2, 5, 0.10), (12, 25, 0.40), (30, 55, 0.50))},
                          (0.15, 0.35), (0.08, 0.25),
                          "A fires deadpan one-liners and short jabs; B defends with the real mechanics "
                          "in longer turns and snaps back briefly. " + _REACT + " " + _REPAIR.format(who="B")),
    "futbol": Profile({"A": _sp(0.22, 0.35, (6, 16, 0.85), (2, 5, 0.15)),
                       "B": _sp(0.65, 0.78, (2, 5, 0.15), (15, 30, 0.35), (35, 60, 0.50))},
                      (0.10, 0.30), (0.05, 0.20),
                      "A sets up each play in one calm sentence; B erupts in long rising calls and short "
                      "exclamations. " + _REACT),
    # role styles from the profile table approved 2026-10-02
    "asmr": Profile({"A": _sp(0.40, 0.60, (3, 7, 0.45), (8, 12, 0.55)),
                     "B": _sp(0.40, 0.60, (3, 7, 0.45), (8, 12, 0.55))},
                    None, (0.0, 0.12),
                    "Every turn is a soft observation of three to twelve words; no exclamations, no "
                    "quick interjections like \"Wow!\". Questions are rare. Nobody corrects themselves.",
                    hard_max=12, no_adjacent_quick=False),
    "meditation": Profile({"A": _sp(0.55, 0.75, (10, 18, 0.5), (18, 25, 0.5)),
                           "B": _sp(0.25, 0.45, (2, 5, 0.35), (6, 12, 0.65))},
                          (0.05, 0.30), (0.0, 0.12),
                          "A guides in calm turns of up to twenty-five words; B answers with gentle short "
                          "affirmations (\"Yes.\", \"Softly now.\"). No exclamations, rare questions, "
                          "nobody corrects themselves.",
                          hard_max=25),
    "socrates": Profile({"A": _sp(0.20, 0.38, (5, 12, 0.6), (12, 20, 0.4)),
                         "B": _sp(0.62, 0.80, (30, 60, 0.7), (12, 30, 0.3))},
                        (0.0, 0.35), (0.38, 0.60),
                        "A asks ONLY questions, short ones, every A turn is a question. B starts with long "
                        "confident answers that get shorter with every round, down to a few words at the "
                        "end. B may restart a sentence as the defence crumbles; A never does.",
                        trend={"B": (1.0, 0.25)}),
    "conspiracy": Profile({"A": _sp(0.40, 0.60, (8, 20, 0.8), (2, 5, 0.2)),
                           "B": _sp(0.40, 0.60, (10, 30, 1.0))},
                          (0.05, 0.25), (0.30, 0.55),
                          "A answers in short flat sentences; B's turns build on A's answer and end in a "
                          "sharper question. Late in the episode A starts hedging and restarting sentences "
                          "(\"that is what the text says\", \"I had not noticed that\")."),
    "eli5": Profile({"A": _sp(0.20, 0.38, (2, 5, 0.30), (5, 15, 0.70)),
                     "B": _sp(0.62, 0.80, (20, 45, 0.85), (8, 15, 0.15))},
                    (0.10, 0.30), (0.15, 0.35),
                    "A, the child, asks and guesses in short turns and reacts with short wonder; B "
                    "explains through images in longer turns. " + _REACT
                    + " B may restart a sentence once to find a simpler picture."),
    "storyteller": Profile({"A": _sp(0.68, 0.85, (40, 70, 0.8), (15, 30, 0.2)),
                            "B": _sp(0.15, 0.32, (2, 5, 0.55), (6, 15, 0.45))},
                           (0.20, 0.42), (0.05, 0.25),
                           "A narrates in long scene-painting turns; B reacts briefly, gasps, guesses and "
                           "asks what happens next. " + _REACT + " Nobody corrects themselves."),
    "trivia": Profile({"A": _sp(0.40, 0.60, (15, 32, 0.6), (6, 15, 0.4)),
                       "B": _sp(0.40, 0.60, (2, 5, 0.45), (6, 15, 0.30), (15, 25, 0.25))},
                      (0.20, 0.42), (0.22, 0.45),
                      "A runs the rounds and asks the questions; B buzzes in fast, often with a few words, "
                      "and thinks aloud in medium turns. " + _REACT
                      + " B changes an answer mid-sentence once or twice (\"No wait, it's\").",
                      no_adjacent_quick=False),
    "noir": Profile({"A": _sp(0.58, 0.72, (25, 45, 0.7), (10, 20, 0.3)),
                     "B": _sp(0.28, 0.42, (2, 5, 0.35), (5, 20, 0.65))},
                    (0.10, 0.30), (0.05, 0.22),
                    "A speaks in long slow metaphors; B answers terse and factual, sometimes in two or "
                    "three words. Nobody corrects themselves."),
    "true_crime": Profile({"A": _sp(0.40, 0.60, (2, 5, 0.15), (12, 25, 0.35), (28, 48, 0.50)),
                           "B": _sp(0.40, 0.60, (2, 5, 0.15), (12, 25, 0.35), (28, 48, 0.50))},
                          (0.08, 0.25), (0.10, 0.28),
                          "Both build tension in long turns; short turns are pauses and quiet reactions, "
                          "never exclamations. " + _REACT + " " + _REPAIR.format(who="a host").replace(
                              "Once or twice", "Once")),
    "courtroom": Profile({"A": _sp(0.38, 0.52, (2, 5, 0.20), (10, 22, 0.45), (28, 45, 0.35)),
                          "B": _sp(0.48, 0.62, (2, 5, 0.15), (12, 25, 0.35), (30, 50, 0.50))},
                         (0.12, 0.28), (0.18, 0.38),
                         "A presses with exhibits and pointed questions; B answers with context in longer "
                         "turns; short turns are objections and sharp replies (\"Objection.\"). " + _REACT
                         + " Nobody corrects themselves."),
    "crisis_room": Profile({"A": _sp(0.28, 0.42, (2, 5, 0.35), (5, 15, 0.50), (15, 22, 0.15)),
                            "B": _sp(0.58, 0.72, (2, 5, 0.15), (12, 25, 0.45), (25, 40, 0.40))},
                           (0.18, 0.38), (0.15, 0.35),
                           "A gives short orders and asks for status; B reports in dense medium and long "
                           "turns. " + _REACT + " B corrects a number mid-sentence once (\"forty, no, "
                           "forty-two percent\")."),
    "dude": Profile({"A": _sp(0.30, 0.48, (2, 5, 0.25), (8, 20, 0.50), (20, 35, 0.25)),
                     "B": _sp(0.40, 0.60, (10, 25, 0.30), (30, 55, 0.70)),
                     "C": _sp(0.02, 0.12, (2, 8, 1.0))},
                    (0.10, 0.35), (0.05, 0.25),
                    "A drawls in relaxed medium turns and short shrugs (\"Yeah, well, man.\"); B rants in "
                    "long turns; C drifts in rarely with a few confused words. Nobody corrects themselves.",
                    rare_third="C", no_adjacent_quick=False),
}


def profile_for(style: str, n_hosts: int) -> Profile | None:
    """The style's profile when it fits the cast (two hosts, or three for a rare_third style)."""
    p = PROFILES.get(style)
    if p is None and style.startswith("custom_"):
        # user styles carry no profile of their own: they borrow their rhythm type's
        from .custom_styles import get_custom_style

        try:
            row = get_custom_style(style)
        except Exception:
            return None
        try:
            p = rhythm_profile_for(row["rhythm_type"])
        except Exception:
            return None
    if p is None:
        return None
    if p.rare_third:
        return p if n_hosts >= 3 else None
    return p if n_hosts == 2 else None


def _sequence(n: int, p: Profile, rng: random.Random) -> list[str]:
    main = [h for h in p.hosts if h != p.rare_third]
    seq = [main[i % len(main)] for i in range(n)]
    if p.rare_third:
        lo, hi = p.speakers[p.rare_third].share
        # third host's turns are short, so a few turns make its word share
        k = max(2, round(n * (lo + hi) / 2 * 2.5))
        slots = sorted(rng.sample(range(2, n - 1), min(k, max(0, n - 3))))
        for i in slots:
            seq[i] = p.rare_third
    return seq


def _sample(spec: Speaker, rng: random.Random) -> int:
    lo, hi, _ = rng.choices(spec.bands, weights=[b[2] for b in spec.bands])[0]
    return rng.randint(lo, hi)


def expected_turn(p: Profile) -> float:
    per = []
    for spec in p.speakers.values():
        tot_w = sum(b[2] for b in spec.bands)
        per.append(sum((b[0] + b[1]) / 2 * b[2] for b in spec.bands) / tot_w)
    return sum(per) / len(per)


def _separate_quick(seq: list[str], sizes: list[int], p: Profile, rng: random.Random) -> None:
    """Move quick reactions apart (and off the first turn) by swapping sizes between turns of
    the SAME speaker, which keeps every host's mix; random sampling alone almost always puts
    two quick turns side by side somewhere in a long plan."""
    if not p.no_adjacent_quick and p.quick_share is None:
        return
    n = len(sizes)

    def bad(i: int) -> bool:
        q = sizes[i] <= QUICK_MAX
        if i == 0:
            return q and p.quick_share is not None
        return p.no_adjacent_quick and q and sizes[i - 1] <= QUICK_MAX

    for _ in range(4 * n):
        i = next((k for k in range(n) if bad(k)), None)
        if i is None:
            return
        options = [j for j in range(n) if j != i and seq[j] == seq[i] and sizes[j] > QUICK_MAX
                   and (j == 0 or sizes[j - 1] > QUICK_MAX or j - 1 == i)
                   and (j + 1 >= n or sizes[j + 1] > QUICK_MAX or j + 1 == i) and j != 0]
        if not options:
            return
        j = rng.choice(options)
        sizes[i], sizes[j] = sizes[j], sizes[i]


def plan_ok(plan: list[tuple[str, int]], words: int, p: Profile, slack: float = 0.02) -> bool:
    """The numbers a plan must meet (shared with the tests)."""
    if not plan:
        return False
    total = sum(w for _, w in plan)
    if abs(total - words) > words * 0.10:
        return False
    if p.hard_max and any(w > p.hard_max for _, w in plan):
        return False
    for h, spec in p.speakers.items():
        share = sum(w for s, w in plan if s == h) / total
        if not spec.share[0] - slack <= share <= spec.share[1] + slack:
            return False
    quick = [w <= QUICK_MAX for _, w in plan]
    if p.quick_share is not None:
        q = sum(quick) / len(plan)
        if not p.quick_share[0] <= q <= p.quick_share[1]:
            return False
    if p.no_adjacent_quick and any(quick[i] and quick[i - 1] for i in range(1, len(quick))):
        return False
    return not quick[0] if p.quick_share is not None else True


def plan_for_profile(words: int, p: Profile, rng: random.Random | None = None) -> list[tuple[str, int]]:
    """A per-turn plan [(speaker, words), ...] that meets the profile."""
    rng = rng or random.Random()
    words = max(40, int(words))
    n0 = max(len(p.speakers) * 4, round(words / expected_turn(p)))
    for attempt in range(600):
        n = max(len(p.speakers) * 4, n0 + (attempt // 60) * (1 if attempt % 2 else -1))
        seq = _sequence(n, p, rng)
        sizes = []
        for i, sp in enumerate(seq):
            if sp in p.trend:
                # a trend is the point of the profile (socrates: B's answers shrink), so it is
                # not left to random band draws, which washed it out on some seeds
                a, b = p.trend[sp]
                top = max(p.speakers[sp].bands, key=lambda band: band[1])
                base = (top[0] + top[1]) / 2 * rng.uniform(0.85, 1.15)
                w = max(2, round(base * (a + (b - a) * i / max(1, n - 1))))
            else:
                w = _sample(p.speakers[sp], rng)
            sizes.append(w)
        _separate_quick(seq, sizes, p, rng)
        rest = sum(w for w in sizes if w > QUICK_MAX)
        quick = sum(w for w in sizes if w <= QUICK_MAX)
        factor = (words - quick) / max(1, rest)
        cap = p.hard_max or 10_000
        plan = []
        for sp, w in zip(seq, sizes):
            if w > QUICK_MAX:
                band_hi = max(b[1] for b in p.speakers[sp].bands)
                w = min(cap, round(band_hi * 1.25), max(QUICK_MAX + 1, round(w * factor)))
            plan.append((sp, w))
        if plan_ok(plan, words, p):
            return plan
    raise ValueError(f"no plan for {words} words with this profile")


def rhythm_problems_for(lines: list[dict], p: Profile) -> list[str]:
    """Plain-language problems against the profile, [] when the script fits it."""
    turns = [(str(ln.get("speaker", "")).upper(), len(str(ln.get("text", "")).split())) for ln in lines]
    turns = [(s, w) for s, w in turns if w > 0]
    if len(turns) < 6:
        return []
    total = sum(w for _, w in turns)
    problems: list[str] = []
    for h, spec in p.speakers.items():
        share = sum(w for s, w in turns if s == h) / total
        lo, hi = spec.share
        if share < lo - 0.07:
            problems.append(f"host {h} speaks {round(100 * share)} percent of the words; the plan gives "
                            f"{h} {round(100 * lo)} to {round(100 * hi)} percent")
        elif share > hi + 0.07:
            problems.append(f"host {h} speaks {round(100 * share)} percent of the words; the plan gives "
                            f"{h} at most {round(100 * hi)} percent")
    if p.quick_share is not None:
        q = sum(1 for _, w in turns if w <= QUICK_MAX) / len(turns)
        lo, hi = p.quick_share
        if q > hi + 0.05:
            problems.append(f"{round(100 * q)} percent of the turns are quick reactions; the plan has "
                            f"{round(100 * lo)} to {round(100 * hi)} percent")
        elif q < lo - 0.05:
            problems.append(f"only {round(100 * q)} percent of the turns are quick reactions; the plan has "
                            f"{round(100 * lo)} to {round(100 * hi)} percent")
    if p.hard_max:
        over = sum(1 for _, w in turns if w > p.hard_max)
        if over:
            problems.append(f"{over} turns exceed the hard limit of {p.hard_max} words")
    return problems


def plan_block(plan: list[tuple[str, int]]) -> str:
    """The plan as a JSON skeleton the model fills in (speaker and words fixed)."""
    import json

    skeleton = json.dumps([{"speaker": s, "words": w, "text": "..."} for s, w in plan],
                          ensure_ascii=False).replace("}, {", "},\n{")
    return (
        "TURN PLAN - your answer is this JSON array with every \"...\" replaced by the turn's text. "
        "Keep every speaker exactly as given, in this order, and give each turn about its \"words\" "
        "words. You may drop the \"words\" field in your answer.\n" + skeleton
    )


def profile_rules(p: Profile) -> str:
    return "STYLE RHYTHM: " + p.rules


_SHARED_REACTIONS = re.compile(r"\n- Mix quick reactions.*?(?=\n- )", re.DOTALL)
_SHARED_QUESTIONS = re.compile(r"\n- About one turn in six asks a question.*?(?=\n- )", re.DOTALL)
_SHARED_DISAGREEMENT = "\n- Include one disagreement and its resolution."


def apply_profile_rules(prompt: str, p: Profile) -> str:
    """Swap the shared lines that contradict the profile for the style's own rhythm rules.

    The shared rules told every style 'about one turn in six asks a question' and 'mix
    quick reactions'; socrates (A asks only questions), conspiracy (every answer opens a
    question) and asmr (no interjections) were told the opposite of their template."""
    prompt = _SHARED_REACTIONS.sub("\n- " + profile_rules(p), prompt, count=1)
    prompt = _SHARED_QUESTIONS.sub("\n- Never open turns with the same word again and again.", prompt, count=1)
    if p.quick_share is None or "No conflict" in p.rules or p is PROFILES.get("meditation"):
        prompt = prompt.replace(_SHARED_DISAGREEMENT, "", 1)
    return prompt


# --- User rhythm types (VOZONDA-CUSTOM-STYLES-API) --------------------------------
# A custom style picks one of five rhythm types instead of a full profile. Each
# type borrows its numbers from the built-in profile named, so built-in styles
# keep their own profiles untouched. Builders return copies, never the shared
# profile object itself.

RHYTHM_TYPES: dict[str, str] = {
    "peer": "debate",
    "host_expert": "balanced",
    "narrator_listener": "storyteller",
    "interrogator": "socrates",
    "calm": "meditation",
}

RHYTHM_DESCRIPTIONS: dict[str, str] = {
    "peer": "Equal conversation, both hosts argue and answer each other.",
    "host_expert": "Curious host asks, expert guest explains.",
    "narrator_listener": "One host narrates the story, the other reacts and guesses.",
    "interrogator": "One host asks only questions, the other answers shrink over time.",
    "calm": "Slow guided turns, no turn longer than twenty-five words.",
}


def _copy_profile(p: Profile) -> Profile:
    """A detached copy of a built-in profile (speakers and trend re-owned)."""
    return Profile(
        speakers={h: Speaker(s.share, s.bands) for h, s in p.speakers.items()},
        quick_share=tuple(p.quick_share) if p.quick_share is not None else None,  # type: ignore[arg-type]
        questions=tuple(p.questions),  # type: ignore[arg-type]
        rules=p.rules,
        hard_max=p.hard_max,
        trend=dict(p.trend),
        rare_third=p.rare_third,
        no_adjacent_quick=p.no_adjacent_quick,
    )


def rhythm_profile_for(rhythm_type: str) -> Profile:
    """The profile behind a user rhythm type (a copy of its built-in source)."""
    source = RHYTHM_TYPES.get(rhythm_type)
    if source is None:
        raise KeyError(f"unknown rhythm type {rhythm_type!r}")
    return _copy_profile(PROFILES[source])


def peer_profile() -> Profile:
    """Equal conversation, like debate."""
    return rhythm_profile_for("peer")


def host_expert_profile() -> Profile:
    """Curious host with an expert guest, like balanced."""
    return rhythm_profile_for("host_expert")


def narrator_listener_profile() -> Profile:
    """A narrator with a reacting listener, like storyteller."""
    return rhythm_profile_for("narrator_listener")


def interrogator_profile() -> Profile:
    """A questioner dismantles answers that shrink, like socrates."""
    return rhythm_profile_for("interrogator")


def calm_profile() -> Profile:
    """Slow guided turns with a hard cap of 25 words, like meditation."""
    return rhythm_profile_for("calm")
