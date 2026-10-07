import asyncio
import json
import re
from unittest.mock import MagicMock

import pytest

from vozonda_api import pipeline
from vozonda_api.jobs import JobStore


def _script_result(raw: str | list, desc: str = ""):
    async def fake(*, prompt: str, **kwargs):
        if isinstance(raw, str):
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            lines = json.loads(m.group(0)) if m else []
            tail = raw[m.end():] if m else ""
            dm = re.search(r"DESCRIPTION:\s*(.+)", tail)
            found = dm.group(1).strip().strip('"') if dm else ""
        else:
            lines, found = raw, desc
        return lines, found
    return fake


def test_parses_json_array_from_noisy_output(monkeypatch: pytest.MonkeyPatch) -> None:
    content = (
        'Sure! [{"speaker":"A","text":"one"},{"speaker":"B","text":"two"},'
        '{"speaker":"A","text":"three"},{"speaker":"B","text":"four"}] done'
    )
    monkeypatch.setattr(pipeline, "script_call", _script_result(content, ""))
    lines, _desc = asyncio.run(pipeline._script("source"))
    assert lines == [
        {"speaker": "A", "text": "one"},
        {"speaker": "B", "text": "two"},
        {"speaker": "A", "text": "three"},
        {"speaker": "B", "text": "four"},
    ]


def test_filters_invalid_speakers_and_empty_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = (
        '[{"speaker":"X","text":"no"},{"speaker":"A","text":""},'
        '{"speaker":"b","text":"one"},{"speaker":"B","text":"two"},'
        '{"speaker":"A","text":"three"},{"speaker":"B","text":"four"},'
        '{"speaker":"C","text":"five"}]'
    )
    monkeypatch.setattr(pipeline, "script_call", _script_result(content, ""))
    lines, _desc = asyncio.run(pipeline._script("src"))
    assert len(lines) == 5
    assert all(line["speaker"] in ("A", "B", "C") for line in lines)
    assert all(line["text"] for line in lines)


def test_rejects_scripts_shorter_than_four_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline,
        "script_call",
        _script_result('[{"speaker":"A","text":"hi"}]'),
    )
    with pytest.raises(RuntimeError, match="script too short"):
        asyncio.run(pipeline._script("src"))


def test_raises_when_output_has_no_json_array(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "script_call", _script_result("no json here, sorry", ""))
    with pytest.raises(RuntimeError, match="all script writers failed"):
        asyncio.run(pipeline._script("src"))


def test_error_names_each_failed_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*, prompt: str, **kwargs):
        raise ValueError("kaboom")

    monkeypatch.setattr(pipeline, "script_call", boom)
    with pytest.raises(RuntimeError, match="local") as excinfo:
        asyncio.run(pipeline._script("src"))
    assert "kaboom" in str(excinfo.value)


def test_narration_keeps_freely_labelled_paragraphs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = (
        '[{"speaker":"Narrator","text":"Absatz eins."},'
        '{"speaker":"N1","text":"Absatz zwei."},'
        '{"speaker":"A.","text":"Absatz drei."},'
        '{"speaker":"A","text":"Absatz vier."}]'
    )
    monkeypatch.setattr(pipeline, "script_call", _script_result(content, ""))
    lines, _desc = asyncio.run(pipeline._script("Quelle", fmt="narration"))
    assert len(lines) == 4
    assert all(line["speaker"] == "A" for line in lines)


def test_description_hook_captured_from_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = (
        '[{"speaker":"A","text":"one"},{"speaker":"B","text":"two"},'
        '{"speaker":"A","text":"three"},{"speaker":"B","text":"four"}]\n'
        'DESCRIPTION: A brisk tour of why value-for-value beats paywalls.'
    )
    monkeypatch.setattr(pipeline, "script_call", _script_result(content, ""))
    lines, _desc = asyncio.run(pipeline._script("src"))
    assert len(lines) == 4
    assert _desc == "A brisk tour of why value-for-value beats paywalls."



def test_narration_same_language_zero_llm_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same language narration: verbatim split, no _chat_completion calls."""
    body = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    store = MagicMock(spec=JobStore)
    store.get.return_value = {
        "id": "test", "format": "narration", "language": "en",
        "style": "balanced", "tone": "neutral", "explicit": False, "hosts": 2,
    }
    lines, _desc = asyncio.run(
        pipeline._narration_script(body, "en", "en", store, "test")
    )
    assert len(lines) == 3
    assert all(l["speaker"] == "Narrator" for l in lines)
    assert "3 paragraphs" in _desc


def test_narration_diff_language_one_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Different language narration: exactly one _chat_completion call."""
    body = "Hello world."
    translated = "Hallo Welt."
    call_count = 0

    async def count_calls(prov: dict, prompt: str, max_tokens: int = 4096) -> str:
        nonlocal call_count
        call_count += 1
        return translated

    store = MagicMock(spec=JobStore)
    store.get.return_value = {
        "id": "test", "format": "narration", "language": "de",
        "style": "balanced", "tone": "neutral", "explicit": False, "hosts": 2,
    }
    monkeypatch.setattr(pipeline, "_chat_completion", count_calls)
    lines, _desc = asyncio.run(
        pipeline._narration_script(body, "de", "en", store, "test")
    )
    assert call_count == 1
    assert len(lines) == 1
    assert lines[0]["text"] == "Hallo Welt."


def test_narration_auto_resolves_to_source_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto language with detected source = same lang, zero LLM calls."""
    body = "Paragraph one.\n\nParagraph two."
    store = MagicMock(spec=JobStore)
    store.get.return_value = {
        "id": "test", "format": "narration", "language": "auto",
        "style": "balanced", "tone": "neutral", "explicit": False, "hosts": 2,
    }
    lines, _desc = asyncio.run(
        pipeline._narration_script(body, "auto", "en", store, "test")
    )
    assert len(lines) == 2
    assert all(l["speaker"] == "Narrator" for l in lines)


def test_narration_fails_all_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All translation providers fail -> RuntimeError with provider names."""
    body = "Hello."
    store = MagicMock(spec=JobStore)
    store.get.return_value = {
        "id": "test", "format": "narration", "language": "de",
        "style": "balanced", "tone": "neutral", "explicit": False, "hosts": 2,
    }

    async def fail(prov: dict, prompt: str, max_tokens: int = 4096) -> str:
        raise ValueError("down")

    monkeypatch.setattr(pipeline, "llm_chain", lambda: [
        {"name": "local", "base": "http://x", "model": "m"},
    ])
    monkeypatch.setattr(pipeline, "_chat_completion", fail)

    with pytest.raises(RuntimeError, match="all translation writers failed"):
        asyncio.run(
            pipeline._narration_script(body, "de", "en", store, "test")
        )


def test_run_job_pasted_text_narration(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pasted text with format='narration' under MAX_SOURCE_CHARS must not raise UnboundLocalError."""
    import vozonda_api.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    store = JobStore()
    job_id = "test-narration-pasted"
    text = "This is a short pasted article about open source software."
    store.create(
        job_id,
        text,
        style="balanced",
        fmt="narration",
        tone="neutral",
        language="auto",
        hosts=1,
    )

    # mock blocking_problem, tts, master stages
    import vozonda_api.doctor as doc_mod
    monkeypatch.setattr(doc_mod, "blocking_problem", lambda: None)

    async def mock_voice(*args, **kwargs):
        return tmp_path / f"{job_id}.wav"

    async def mock_master(*args, **kwargs):
        return tmp_path / f"{job_id}.mp3"

    monkeypatch.setattr(pipeline, "_voice", mock_voice)
    monkeypatch.setattr(pipeline, "_master", mock_master)

    async def run():
        async for state in pipeline.run_job(store, job_id):
            pass

    asyncio.run(run())
    finished = store.get(job_id)
    assert finished["state"] == "done"
    assert finished["format"] == "narration"

