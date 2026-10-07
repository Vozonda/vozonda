"""Tests for script JSON retry loop with format reminder (VOZONDA-JSON-3).

Verifies that the non-outline script path retries up to 3 times on ValueError,
appends the format reminder ONLY on attempt 3, and correctly raises ValueError
after 3 failures or runaway script output.
"""

from typing import Any

import pytest

import vozonda_api.pipeline as pipeline
from vozonda_api.pipeline import (
    SCRIPT_JSON_REMINDER,
    _script,
    _script_direct,
)

SAMPLE_TURNS = [
    {"speaker": "A", "text": "Welcome to the overview."},
    {"speaker": "B", "text": "Thanks, glad to be here."},
    {"speaker": "A", "text": "Let us examine the key findings."},
    {"speaker": "B", "text": "The results look quite promising."},
]

SAMPLE_PROV: dict[str, Any] = {
    "name": "test_llm",
    "base": "http://127.0.0.1:30001/v1",
    "model": "qwen3.6-35b",
    "key": "",
}


@pytest.mark.asyncio
async def test_fails_twice_then_succeeds_with_reminder_on_third_attempt(monkeypatch):
    """Fails twice with ValueError, succeeds on 3rd attempt with format reminder appended."""
    call_prompts: list[str] = []

    async def mock_script_call(*, prompt: str, **kwargs: Any) -> tuple[list[dict[str, Any]], str]:
        call_prompts.append(prompt)
        if len(call_prompts) < 3:
            raise ValueError("no JSON array in output")
        return SAMPLE_TURNS, "A short test description."

    monkeypatch.setattr(pipeline, "script_call", mock_script_call)

    base_prompt = "Generate a podcast dialogue script about quantum computing."
    lines, desc = await _script_direct(
        prompt=base_prompt,
        prov=SAMPLE_PROV,
        planned_words=None,
        fmt="dialog",
        n_hosts=2,
    )

    assert len(call_prompts) == 3
    assert SCRIPT_JSON_REMINDER not in call_prompts[0]
    assert SCRIPT_JSON_REMINDER not in call_prompts[1]
    assert SCRIPT_JSON_REMINDER in call_prompts[2]
    assert call_prompts[0] == base_prompt
    assert call_prompts[1] == base_prompt
    assert call_prompts[2] == f"{base_prompt}\n{SCRIPT_JSON_REMINDER}"
    assert lines == SAMPLE_TURNS
    assert desc == "A short test description."


@pytest.mark.asyncio
async def test_fails_three_times_raises_value_error(monkeypatch):
    """Fails 3 times with ValueError("no JSON array in output") and re-raises ValueError."""
    call_prompts: list[str] = []

    async def mock_script_call(*, prompt: str, **kwargs: Any) -> tuple[list[dict[str, Any]], str]:
        call_prompts.append(prompt)
        raise ValueError("no JSON array in output")

    monkeypatch.setattr(pipeline, "script_call", mock_script_call)

    base_prompt = "Generate a podcast dialogue script."
    with pytest.raises(ValueError, match="no JSON array in output"):
        await _script_direct(
            prompt=base_prompt,
            prov=SAMPLE_PROV,
            planned_words=None,
            fmt="dialog",
            n_hosts=2,
        )

    assert len(call_prompts) == 3
    assert SCRIPT_JSON_REMINDER not in call_prompts[0]
    assert SCRIPT_JSON_REMINDER not in call_prompts[1]
    assert SCRIPT_JSON_REMINDER in call_prompts[2]
    assert call_prompts[0] == base_prompt
    assert call_prompts[1] == base_prompt
    assert call_prompts[2] == f"{base_prompt}\n{SCRIPT_JSON_REMINDER}"


@pytest.mark.asyncio
async def test_runaway_output_on_all_attempts_raises_value_error(monkeypatch):
    """Runaway output exceeding 2.2x planned_words on all attempts raises ValueError."""
    call_prompts: list[str] = []

    # 4 turns with 50 words each = 200 words. Budget is 50 words; 2.2x is 110 words.
    runaway_turns = [
        {"speaker": "A", "text": "word " * 50},
        {"speaker": "B", "text": "word " * 50},
        {"speaker": "A", "text": "word " * 50},
        {"speaker": "B", "text": "word " * 50},
    ]

    async def mock_script_call(*, prompt: str, **kwargs: Any) -> tuple[list[dict[str, Any]], str]:
        call_prompts.append(prompt)
        return runaway_turns, "Runaway description."

    monkeypatch.setattr(pipeline, "script_call", mock_script_call)

    base_prompt = "Generate a podcast dialogue script."
    with pytest.raises(ValueError, match="runaway script, far over the word budget"):
        await _script_direct(
            prompt=base_prompt,
            prov=SAMPLE_PROV,
            planned_words=50,
            fmt="dialog",
            n_hosts=2,
        )

    assert len(call_prompts) == 3
    assert SCRIPT_JSON_REMINDER not in call_prompts[0]
    assert SCRIPT_JSON_REMINDER not in call_prompts[1]
    assert SCRIPT_JSON_REMINDER in call_prompts[2]
    assert call_prompts[0] == base_prompt
    assert call_prompts[1] == base_prompt
    assert call_prompts[2] == f"{base_prompt}\n{SCRIPT_JSON_REMINDER}"


@pytest.mark.asyncio
async def test_runaway_output_recovers_on_third_attempt(monkeypatch):
    """Runaway output on attempts 1 and 2 recovers with valid turns on attempt 3."""
    call_prompts: list[str] = []

    runaway_turns = [
        {"speaker": "A", "text": "word " * 50},
        {"speaker": "B", "text": "word " * 50},
        {"speaker": "A", "text": "word " * 50},
        {"speaker": "B", "text": "word " * 50},
    ]

    async def mock_script_call(*, prompt: str, **kwargs: Any) -> tuple[list[dict[str, Any]], str]:
        call_prompts.append(prompt)
        if len(call_prompts) < 3:
            return runaway_turns, "Runaway description."
        return SAMPLE_TURNS, "Normal description."

    monkeypatch.setattr(pipeline, "script_call", mock_script_call)

    base_prompt = "Generate a podcast dialogue script."
    lines, desc = await _script_direct(
        prompt=base_prompt,
        prov=SAMPLE_PROV,
        planned_words=50,
        fmt="dialog",
        n_hosts=2,
    )

    assert len(call_prompts) == 3
    assert SCRIPT_JSON_REMINDER not in call_prompts[0]
    assert SCRIPT_JSON_REMINDER not in call_prompts[1]
    assert SCRIPT_JSON_REMINDER in call_prompts[2]
    assert lines == SAMPLE_TURNS
    assert desc == "Normal description."


@pytest.mark.asyncio
async def test_script_entrypoint_recovers_on_third_attempt(monkeypatch):
    """The _script entrypoint succeeds when script_call fails twice then recovers on attempt 3."""
    call_prompts: list[str] = []

    async def mock_script_call(*, prompt: str, **kwargs: Any) -> tuple[list[dict[str, Any]], str]:
        call_prompts.append(prompt)
        if len(call_prompts) < 3:
            raise ValueError("no JSON array in output")
        return SAMPLE_TURNS, "Valid description."

    monkeypatch.setattr(pipeline, "script_call", mock_script_call)
    monkeypatch.setattr(pipeline, "llm_chain", lambda: [SAMPLE_PROV])

    lines, desc = await _script(
        body="This is an article about artificial intelligence and programming.",
        style="balanced",
        fmt="dialog",
        n_hosts=2,
    )

    assert len(call_prompts) == 3
    assert SCRIPT_JSON_REMINDER not in call_prompts[0]
    assert SCRIPT_JSON_REMINDER not in call_prompts[1]
    assert SCRIPT_JSON_REMINDER in call_prompts[2]
    assert len(lines) == len(SAMPLE_TURNS)
    assert desc == "Valid description."


@pytest.mark.asyncio
async def test_first_attempt_success_no_reminder(monkeypatch):
    """When the first attempt succeeds, no retries occur and reminder is not included."""
    call_prompts: list[str] = []

    async def mock_script_call(*, prompt: str, **kwargs: Any) -> tuple[list[dict[str, Any]], str]:
        call_prompts.append(prompt)
        return SAMPLE_TURNS, "Description."

    monkeypatch.setattr(pipeline, "script_call", mock_script_call)

    base_prompt = "Generate a podcast dialogue script."
    lines, desc = await _script_direct(
        prompt=base_prompt,
        prov=SAMPLE_PROV,
        planned_words=None,
        fmt="dialog",
        n_hosts=2,
    )

    assert len(call_prompts) == 1
    assert SCRIPT_JSON_REMINDER not in call_prompts[0]
    assert lines == SAMPLE_TURNS
