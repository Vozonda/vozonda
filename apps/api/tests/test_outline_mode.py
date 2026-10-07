"""Outline mode (long episodes): each section prompt carries the SECTION budget,
never the episode's. It kept 'Write about 3200 words' and every section wrote a
whole episode (34,729 words for a 20-minute target, 2026-09-24)."""

import asyncio

from vozonda_api import pipeline
from vozonda_api.length import budget_prompt_line


def test_sections_get_their_own_budget_and_role(monkeypatch):
    prompts = []

    async def fake_chat(prov, prompt, max_tokens=0):
        return '["Intro", "Middle", "End"]'

    async def fake_script_call(*, prompt, **kw):
        prompts.append(prompt)
        return [{"speaker": "AB"[i % 2], "text": "word " * 25} for i in range(40)], "d"

    monkeypatch.setattr(pipeline, "_chat_completion", fake_chat)
    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    episode_prompt = "Rules:\n- " + budget_prompt_line(3200, 45) + "\nSource text:\nabc"
    lines, _ = asyncio.run(pipeline._script_outline(episode_prompt, {"base": "x"}, 3200, turn_words_max=45))
    assert len(prompts) == 3
    for p in prompts:
        assert "3200 words" not in p.split("OUTLINE MODE")[0]
        assert "Write about 1067 words" in p or "Write about 1066 words" in p
    assert "Open the episode." in prompts[0]
    assert "no new opening, no summary" in prompts[1]
    assert "Close the episode" in prompts[2]
    assert len(lines) == 120


def test_a_runaway_section_is_retried_then_fails(monkeypatch):
    async def fake_chat(prov, prompt, max_tokens=0):
        return '["A", "B"]'

    async def huge(*, prompt, **kw):
        return [{"speaker": "AB"[i % 2], "text": "word " * 40} for i in range(300)], "d"

    monkeypatch.setattr(pipeline, "_chat_completion", fake_chat)
    monkeypatch.setattr(pipeline, "script_call", huge)
    try:
        asyncio.run(pipeline._script_outline("Write about 2500 words", {"base": "x"}, 2500))
    except ValueError as exc:
        assert "runaway" in str(exc)
    else:
        raise AssertionError("a runaway section must not be accepted")


def test_a_section_without_json_gets_a_third_attempt_with_the_reminder(monkeypatch):
    """Bench round 3 (2026-09-24): s3 failed on one section with 'no JSON array'
    after two attempts; sections now share the episode path's 3 attempts."""
    prompts = []

    async def fake_chat(prov, prompt, max_tokens=0):
        return '["A", "B"]'

    async def flaky(*, prompt, **kw):
        prompts.append(prompt)
        if len(prompts) in (1, 2):  # first section: prose twice, then JSON
            raise ValueError("no JSON array in output")
        return [{"speaker": "AB"[i % 2], "text": "word " * 25} for i in range(20)], "d"

    monkeypatch.setattr(pipeline, "_chat_completion", fake_chat)
    monkeypatch.setattr(pipeline, "script_call", flaky)
    lines, _ = asyncio.run(pipeline._script_outline("Write about 1000 words", {"base": "x"}, 1000))
    assert lines
    assert pipeline.SCRIPT_JSON_REMINDER not in prompts[0] and pipeline.SCRIPT_JSON_REMINDER not in prompts[1]
    assert pipeline.SCRIPT_JSON_REMINDER in prompts[2]
