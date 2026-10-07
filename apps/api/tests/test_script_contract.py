"""Output contract and targeted role repair (2026-10-02, replaces the per-turn TURN PLAN).

Live A/B on the 35B: the JSON plan skeleton gave no JSON in 6 of 9 runs; contract +
rhythm layer met the profile in 7 of 9, and the targeted repair fixed the other two
(host A 12/15 percent -> 28 percent) plus a weak English run."""

import pytest

from vozonda_api import script_contract as sc
from vozonda_api.rhythm import PROFILES


@pytest.mark.parametrize("style", sorted(PROFILES))
def test_every_style_gets_a_contract_with_its_own_numbers(style):
    p = PROFILES[style]
    block = sc.contract_block(p)
    assert block.startswith("SUCCESS CRITERIA")
    for h in p.hosts:
        assert f"host {h}" in block or f"Host {h}" in block
    lo, hi = p.speakers[p.hosts[0]].share
    assert f"{round(lo * 100)} to {round(hi * 100)} percent" in block
    if p.hard_max:
        assert f"longer than {p.hard_max} words" in block
    assert "LAST CHECK" in sc.reminder_line(p)


def test_balanced_reminder_names_the_role_split():
    assert "A about 36 percent, B about 64 percent" in sc.reminder_line(PROFILES["balanced"])


def _expert_monologue():
    lines = []
    for i in range(10):
        lines += [{"speaker": "A", "text": f"Question {i}?"},
                  {"speaker": "B", "text": f"First point {i} " + "word " * 25 + f"end. Second point {i} " + "word " * 25 + "end."}]
    return lines


def test_quiet_host_and_targets_pick_the_loud_hosts_longest_multi_sentence_turns():
    lines = _expert_monologue()
    assert sc.quiet_host(lines, PROFILES["balanced"]) == ("A", "B")
    idx = sc.repair_targets(lines, PROFILES["balanced"])
    assert idx and all(lines[i]["speaker"] == "B" for i in idx) and len(idx) <= 4


def test_no_targets_when_the_split_is_inside_the_profile():
    ok = [{"speaker": "AB"[i % 2], "text": "word " * (12 if i % 2 == 0 else 22) + "end. And more."} for i in range(20)]
    assert sc.quiet_host(ok, PROFILES["balanced"]) is None and sc.repair_targets(ok, PROFILES["balanced"]) == []


@pytest.mark.parametrize("raw", [
    "B: First half of the point.\nA: And the second half in my words.",
    "<think>hm</think>\n**B:** First half of the point.\n**A:** And the second half in my words.",
    "Sure! B: First half of the point. A: And the second half in my words.",
])
def test_parse_parts_reads_both_layouts_the_model_uses(raw):
    assert sc.parse_parts(raw, "A", "B") == [
        {"speaker": "B", "text": "First half of the point."},
        {"speaker": "A", "text": "And the second half in my words."},
    ]


def test_parse_parts_rejects_a_missing_part():
    assert sc.parse_parts("B: only one part here.", "A", "B") is None


def test_accept_repair_guards_content_and_the_quiet_hosts_part():
    orig = {"speaker": "B", "text": "word " * 40}
    good = [{"speaker": "B", "text": "word " * 20}, {"speaker": "A", "text": "word " * 20}]
    assert sc.accept_repair(orig, good, "A", "B")[1]["speaker"] == "A"
    crumb = [{"speaker": "B", "text": "word " * 36}, {"speaker": "A", "text": "word " * 4}]
    lost = [{"speaker": "B", "text": "word " * 10}, {"speaker": "A", "text": "word " * 10}]
    swapped = [good[1], good[0]]
    assert sc.accept_repair(orig, crumb, "A", "B") is None
    assert sc.accept_repair(orig, lost, "A", "B") is None
    assert sc.accept_repair(orig, swapped, "A", "B") is None


def test_splice_replaces_only_the_repaired_spots():
    lines = [{"speaker": "A", "text": "a"}, {"speaker": "B", "text": "b"}, {"speaker": "A", "text": "c"}]
    out = sc.splice(lines, {1: [{"speaker": "B", "text": "b1"}, {"speaker": "A", "text": "b2"}]})
    assert [ln["text"] for ln in out] == ["a", "b1", "b2", "c"]
