"""Per-style rhythm profiles (2026-10-02, profile table approved by the operator).

Replaces tests/test_turn_plan.py, which tested one balanced 50/50 plan for every style.
That plan broke the templates: asmr caps turns at twelve words, socrates has A ask only
questions while B's answers shrink, storyteller is A's narration, and even balanced is
a curious host with an expert (the model kept that role split against a 50/50 plan:
one host at 10-22 percent of the words). Planner tests run on the profiles; pipeline
tests drive the real _script with only the model call (script_call) replaced."""

import asyncio
import json
import random
import re
import statistics

import pytest

from vozonda_api import pipeline
from vozonda_api.length import OUTLINE_THRESHOLD_WORDS
from vozonda_api.rhythm import (
    PROFILES,
    QUICK_MAX,
    apply_profile_rules,
    plan_block,
    plan_for_profile,
    plan_ok,
    profile_for,
    rhythm_problems_for,
)
from vozonda_api.styles import STYLE_DOCS

SIZES = (200, 600, 1169, 2000, 2400)


def test_every_style_has_a_profile():
    assert set(STYLE_DOCS) == set(PROFILES)


@pytest.mark.parametrize("style", sorted(PROFILES))
def test_plans_meet_the_profile_for_every_size_and_seed(style):
    p = PROFILES[style]
    for words in SIZES:
        for seed in range(12):
            plan = plan_for_profile(words, p, random.Random(seed))
            assert plan_ok(plan, max(40, words), p), (style, words, seed)
            assert {s for s, _ in plan} == set(p.hosts), (style, "every host speaks")


def _shares(plan):
    total = sum(w for _, w in plan)
    return {h: sum(w for s, w in plan if s == h) / total for h in {s for s, _ in plan}}


def test_asmr_never_plans_a_turn_over_twelve_words():
    for seed in range(40):
        assert max(w for _, w in plan_for_profile(900, PROFILES["asmr"], random.Random(seed))) <= 12


def test_socrates_b_answers_shrink_over_the_episode():
    for seed in range(30):
        b = [w for s, w in plan_for_profile(1169, PROFILES["socrates"], random.Random(seed)) if s == "B"]
        third = len(b) // 3
        assert statistics.mean(b[:third]) > 2 * statistics.mean(b[-third:]), (seed, b)


@pytest.mark.parametrize(("style", "host", "lo", "hi"), [
    ("storyteller", "A", 0.65, 0.88), ("balanced", "A", 0.25, 0.45), ("socrates", "A", 0.17, 0.41),
    ("meditation", "A", 0.52, 0.78), ("noir", "A", 0.55, 0.75), ("dude", "C", 0.0, 0.15),
])
def test_role_styles_keep_their_role_split(style, host, lo, hi):
    for seed in range(30):
        share = _shares(plan_for_profile(1169, PROFILES[style], random.Random(seed)))[host]
        assert lo <= share <= hi, (style, seed, share)


def test_balanced_role_split_still_meets_the_bench_speaker_balance():
    """host/expert stays above the rubric's 0.4 smaller/larger word ratio."""
    for seed in range(30):
        sh = _shares(plan_for_profile(1169, PROFILES["balanced"], random.Random(seed)))
        assert min(sh.values()) / max(sh.values()) >= 0.38, (seed, sh)


def test_profile_for_respects_the_cast():
    assert profile_for("balanced", 2) is PROFILES["balanced"]
    assert profile_for("balanced", 3) is None  # no two-host plan for a trio
    assert profile_for("dude", 3) is PROFILES["dude"]
    assert profile_for("dude", 2) is None
    assert profile_for("unknown", 2) is None


def test_apply_profile_rules_replaces_the_contradicting_shared_lines():
    from vozonda_api.styles import dialog_rules

    shared = dialog_rules()
    assert "About one turn in six asks a question" in shared and "- Mix quick reactions" in shared
    out = apply_profile_rules(shared, PROFILES["socrates"])
    assert "About one turn in six asks a question" not in out
    assert "- Mix quick reactions" not in out
    assert "A asks ONLY questions" in out
    asmr = apply_profile_rules(shared, PROFILES["asmr"])
    assert "Include one disagreement" not in asmr and "no exclamations" in asmr


def test_plan_block_is_a_fillable_json_skeleton():
    block = plan_block([("A", 40), ("B", 3), ("A", 15)])
    arr = json.loads(block[block.index("["):])
    assert [(t["speaker"], t["words"], t["text"]) for t in arr] == [("A", 40, "..."), ("B", 3, "..."), ("A", 15, "...")]


def test_rhythm_problems_name_the_quiet_host_and_hard_limit():
    one_sided = [{"speaker": "A" if i % 2 == 0 else "B", "text": ("w " * 3) if i % 2 == 0 else ("w " * 40)}
                 for i in range(30)]
    probs = rhythm_problems_for(one_sided, PROFILES["balanced"])
    assert any("host A speaks" in p for p in probs)
    loud_asmr = [{"speaker": "AB"[i % 2], "text": "w " * 20} for i in range(20)]
    assert any("hard limit of 12" in p for p in rhythm_problems_for(loud_asmr, PROFILES["asmr"]))


# --- the real pipeline: contract, role repair, rhythm layer (2026-10-02) ------

def _alternating(n=30, a_words=12, b_words=22):
    return [{"speaker": "AB"[k % 2], "text": "word " * (a_words if k % 2 == 0 else b_words) + "end. And more."}
            for k in range(n)]


def _run(monkeypatch, style, drafts=None, n_hosts=2, minutes=6, fmt="dialog", repair=None):
    prompts: list[str] = []
    repairs: list[str] = []
    calls = iter(drafts) if drafts else None

    async def fake_chat(prov, prompt, max_tokens=0):
        if "You edit one spot" in prompt:
            repairs.append(prompt)
            return repair(prompt) if repair else ""
        return '["Intro", "Middle", "End", "Close"]'

    async def fake_script_call(*, prompt, **kw):
        prompts.append(prompt)
        nxt = next(calls) if calls else _alternating()
        return (nxt(prompt) if callable(nxt) else nxt), "d"

    monkeypatch.setattr(pipeline, "_chat_completion", fake_chat)
    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    monkeypatch.setattr(pipeline, "llm_chain", lambda: [{"name": "t", "base": "http://x", "model": "m"}])
    meta: dict = {}
    try:
        lines, _ = asyncio.run(pipeline._script("Source text. " * 600, style=style, fmt=fmt, language="en",
                                                n_hosts=n_hosts, target_minutes=minutes, length_meta=meta))
    except RuntimeError:
        lines = []
    return prompts, lines, meta, repairs


@pytest.mark.parametrize("style", sorted(PROFILES))
def test_every_style_opens_with_its_contract_and_closes_with_the_reminder(monkeypatch, style):
    from vozonda_api.script_contract import contract_block, reminder_line

    p = PROFILES[style]
    prompts, _, meta, _ = _run(monkeypatch, style, n_hosts=3 if p.rare_third else 2)
    first = prompts[0]
    assert first.startswith(contract_block(p))
    assert first.rstrip().endswith(reminder_line(p))
    assert "TURN PLAN" not in first
    assert "STYLE RHYTHM: " + p.rules[:40] in first
    assert "About one turn in six asks a question" not in first
    assert re.search(r"Write about \d+ words \(plus or minus 10 percent\)\.", first)
    assert meta["rhythm_profile"] == style


def test_narration_and_mismatched_casts_get_no_contract(monkeypatch):
    for fmt, n in (("narration", 1), ("dialog", 3)):
        prompts, _, _, _ = _run(monkeypatch, "balanced", fmt=fmt, n_hosts=n)
        assert prompts and all("SUCCESS CRITERIA (output contract" not in p and "LAST CHECK" not in p for p in prompts)


def test_long_episodes_carry_the_contract_once_per_section_without_a_plan(monkeypatch):
    prompts, _, _, _ = _run(monkeypatch, "storyteller", minutes=25)
    sections = [p for p in prompts if "OUTLINE MODE" in p]
    assert len(sections) >= 2
    for p in sections:
        assert p.count("SUCCESS CRITERIA (output contract") == 1 and "TURN PLAN" not in p
        budget = int(p.split("Write ONLY this section, about ")[1].split(" words")[0])
        assert budget <= OUTLINE_THRESHOLD_WORDS


def _expert_monologue():
    out = []
    for i in range(15):
        out += [{"speaker": "A", "text": f"Question {i}?"},
                {"speaker": "B", "text": f"First {i} " + "word " * 22 + f"end. Second {i} " + "word " * 22 + "end."}]
    return out


def _hand_over(prompt):
    turn = prompt.split("TURN (B): ")[1].split("\n")[0]
    first, second = turn.split(" end. ", 1)
    return f"B: {first} end.\nA: {second}"


def test_a_one_sided_draft_gets_spot_repairs_that_hand_turns_to_the_quiet_host(monkeypatch):
    _, lines, meta, repairs = _run(monkeypatch, "balanced", drafts=[_expert_monologue()] * 3, repair=_hand_over)
    assert repairs and all("TURN (B)" in r for r in repairs) and len(repairs) <= 4
    assert meta["role_repair"]["quiet"] == "A" and meta["role_repair"]["accepted"] == len(repairs)
    def a_share(ls):
        return sum(len(ln["text"].split()) for ln in ls if ln["speaker"] == "A") / sum(len(ln["text"].split()) for ln in ls)
    assert a_share(lines) > 1.5 * a_share(_expert_monologue()), "the quiet host got real parts"
    assert not any("RHYTHM CORRECTION" in r for r in repairs)


def test_a_broken_repair_answer_is_dropped_and_never_fails_the_episode(monkeypatch):
    _, lines, meta, repairs = _run(monkeypatch, "balanced", drafts=[_expert_monologue()] * 3,
                                   repair=lambda p: "Sure, here is the rewrite!")
    assert repairs and meta["role_repair"]["accepted"] == 0
    assert lines, "the draft is kept"


def test_a_draft_inside_the_profile_gets_no_repair_call(monkeypatch):
    _, _, meta, repairs = _run(monkeypatch, "balanced", drafts=[_alternating()] * 2)
    assert repairs == [] and "role_repair" not in meta


def test_the_rhythm_layer_runs_last_and_reports_what_it_added(monkeypatch):
    long_turns = [{"speaker": "AB"[k % 2], "text": "First half " + "word " * 12 + "end. Second half " + "word " * 12 + "end."}
                  for k in range(30)]
    _, lines, meta, _ = _run(monkeypatch, "debate", drafts=[long_turns] * 2)
    assert meta["rhythm_layer_added"] > 0
    assert sum(len(ln["text"].split()) <= QUICK_MAX for ln in lines) / len(lines) >= PROFILES["debate"].quick_share[0]


def test_quick_turn_constant_matches_the_bench_rubric():
    assert QUICK_MAX == 5  # bench: short_turn_share counts turns of <= 4-5 words
