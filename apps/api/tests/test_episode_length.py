import asyncio

import pytest
from fastapi.testclient import TestClient

from vozonda_api import pipeline
from vozonda_api.length import (
    DEFAULT_WPM,
    LENGTH_PRESETS,
    budget_prompt_line,
    cap_target_minutes,
    correction_action,
    deviation_percent,
    max_minutes_for_source,
    outline_split,
    resolve_target_minutes,
    rolling_wpm,
    turn_range_for_budget,
    word_budget,
)


def test_word_budget_default_wpm():
    assert word_budget(8, "qwen_tts") == round(8 * DEFAULT_WPM)
    assert word_budget(1, "qwen_tts") == round(DEFAULT_WPM)


def test_word_budget_measured_wpm():
    settings = {"tts.wpm.qwen_tts": "200"}
    assert word_budget(3, "qwen_tts", settings) == 600
    # an engine without a measured value falls back to the default
    assert word_budget(3, "piper", settings) == round(3 * DEFAULT_WPM)


def test_source_cap():
    # thin source hits the 3-minute floor, never zero
    assert max_minutes_for_source(220) == 3.0
    assert max_minutes_for_source(2200) == 20.0
    capped, was_capped = cap_target_minutes(10, 330)
    assert was_capped
    assert capped == 3.0
    capped, was_capped = cap_target_minutes(2, 100_000)
    assert not was_capped
    assert capped == 2.0


def test_turn_range_derivation():
    # 1280 words at turn_words_max 40: full turns 30 words, one in five a
    # ~3 word reaction -> average 25 words -> about 51 turns, +-15 percent
    t1, t2 = turn_range_for_budget(1280, 40)
    assert (t1, t2) == (43, 59)
    line = budget_prompt_line(1280, 40)
    assert "1280 words" in line and "plus or minus 10 percent" in line
    assert "about 51 turns" in line and f"{t1} to {t2} turns" in line
    assert "never split one thought" in line.lower()
    assert "one to five words" in line and "40 to 64 words" in line  # long explaining turns up to 1.6x the max


def test_turn_target_keeps_turns_full():
    """Bench s5 met a wide turn window with 4.5-word fragments, so full turns
    stay at three quarters of the max; since 2026-09-25 the average also counts
    the one-in-five quick reactions (without them every turn landed in one
    length band, CV 0.09). Still far from the 4.5-word fragments."""
    from vozonda_api.length import turn_target_for_budget

    assert turn_target_for_budget(1280, 45) == 46
    assert turn_target_for_budget(3200, 45) == 114
    assert 3200 / turn_target_for_budget(3200, 45) > 25


def test_correction_action_threshold():
    assert correction_action(1100, 1280) is None  # -14%, inside +-15
    assert correction_action(1470, 1280) is None  # +14.8%, inside
    assert correction_action(1000, 1280) == "expand"
    assert correction_action(1500, 1280) == "condense"
    assert deviation_percent(1500, 1280) == pytest.approx(17.1875)


def test_outline_split_sums_to_budget():
    for total in (2401, 3000, 5000):
        parts = outline_split(total)
        assert sum(parts) == total
        assert len(parts) >= 2
        assert max(parts) - min(parts) <= 1


def test_rolling_wpm_update():
    assert rolling_wpm(160, 200) == 168.0
    assert rolling_wpm(160, 200, weight=0.5) == 180.0


def test_resolve_target_minutes():
    assert resolve_target_minutes(target_minutes=5) == 5.0
    assert resolve_target_minutes(length="short") == LENGTH_PRESETS["short"]
    assert resolve_target_minutes(length="default") == 8.0
    assert resolve_target_minutes(length="long") == 15.0
    assert resolve_target_minutes() == 8.0
    with pytest.raises(ValueError):
        resolve_target_minutes(target_minutes=0)
    with pytest.raises(ValueError):
        resolve_target_minutes(target_minutes=61)
    with pytest.raises(ValueError):
        resolve_target_minutes(length="enormous")


def _fake_lines(words_per_line: int, n: int = 4) -> list[dict]:
    speakers = ["A", "B"]
    return [
        {"speaker": speakers[i % 2], "text": " ".join(["word"] * words_per_line)}
        for i in range(n)
    ]


def test_script_corrective_pass_triggers_on_short(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    prompts: list[str] = []

    async def fake_script_call(*, prompt, **kwargs):
        calls["n"] += 1
        prompts.append(prompt)
        return _fake_lines(2), "desc"

    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    lines, _desc = asyncio.run(pipeline._script("source text about things", target_minutes=8))
    assert calls["n"] == 2  # exactly one corrective pass
    assert "LENGTH CORRECTION" in prompts[1]
    assert "expand these sections with more depth from the source, no new facts" in prompts[1]
    assert len(lines) >= 4


def test_script_corrective_pass_triggers_on_long(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    prompts: list[str] = []

    async def fake_script_call(*, prompt, **kwargs):
        calls["n"] += 1
        prompts.append(prompt)
        return _fake_lines(500), "desc"  # 2000 words vs 1280 planned: +56%

    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    lines, _desc = asyncio.run(pipeline._script("source text about things", target_minutes=8))
    assert calls["n"] == 2
    assert "condense, keep the arc and the hook" in prompts[1]
    assert len(lines) >= 4


def test_script_no_correction_within_tolerance(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def fake_script_call(*, prompt, **kwargs):
        calls["n"] += 1
        return _fake_lines(320), "desc"  # 4*320 = 1280 words == budget exactly

    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    lines, _desc = asyncio.run(pipeline._script("source text about things", target_minutes=8))
    assert calls["n"] == 1
    assert len(lines) == 4


def test_script_prompt_carries_budget_line(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    async def fake_script_call(*, prompt, **kwargs):
        captured.append(prompt)
        return _fake_lines(320), "desc"

    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    asyncio.run(pipeline._script("source text about things", target_minutes=8))
    assert "Write about 1280 words (plus or minus 10 percent)" in captured[0]
    assert "Aim for" not in captured[0].split("Write about")[0]


def test_script_outline_mode_for_long_episodes(monkeypatch: pytest.MonkeyPatch) -> None:
    script_calls = {"n": 0}

    async def fake_chat(prov, prompt, max_tokens=4096):
        return '["Act one", "Act two", "Act three"]'

    async def fake_script_call(*, prompt, **kwargs):
        script_calls["n"] += 1
        return _fake_lines(30), "desc"

    monkeypatch.setattr(pipeline, "_chat_completion", fake_chat)
    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    lines, _desc = asyncio.run(pipeline._script("source text", target_minutes=20))
    # 3200 planned words > 2400: outline split into 3 sections, one call each
    assert script_calls["n"] >= 3
    assert len(lines) >= 4


def test_job_request_rejects_out_of_range_minutes():
    import vozonda_api.main as main_mod

    client = TestClient(main_mod.app)
    payload = {"text": "word " * 30}
    assert client.post("/jobs", json={**payload, "target_minutes": 0}).status_code == 422
    assert client.post("/jobs", json={**payload, "target_minutes": 61}).status_code == 422
    assert client.post("/jobs", json={**payload, "length": "enormous"}).status_code == 422


def test_job_request_accepts_minutes_and_presets(monkeypatch: pytest.MonkeyPatch) -> None:
    import vozonda_api.main as main_mod

    async def fake_run(job_id):
        return None

    monkeypatch.setattr(main_mod, "_run", fake_run)
    client = TestClient(main_mod.app)
    payload = {"text": "word " * 30}

    r = client.post("/jobs", json={**payload, "target_minutes": 5})
    assert r.status_code == 200
    assert r.json()["target_minutes"] == 5.0

    r = client.post("/jobs", json={**payload, "length": "long"})
    assert r.status_code == 200
    assert r.json()["target_minutes"] == 15.0

    r = client.post("/jobs", json={**payload, "length": "short"})
    assert r.status_code == 200
    assert r.json()["target_minutes"] == 3.0
