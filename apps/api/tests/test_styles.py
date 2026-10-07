import pytest

from vozonda_api import pipeline
from vozonda_api.styles import (
    EMOTION_DOCS,
    EMOTION_IDS,
    EMOTION_INSTRUCTS,
    HOOK_BRIEFS,
    SCRIPT_PARAMS,
    STYLE_DOCS,
    STYLE_IDS,
    STYLE_TEMPLATES,
    STYLES,
)


def test_styles_list_contains_powerhouse_styles():
    for s_id in ["true_crime", "tech_roast", "meditation", "noir", "trivia", "courtroom", "crisis_room"]:
        assert s_id in STYLE_IDS
    assert STYLES == STYLE_IDS


def test_style_docs_contains_all_styles():
    for s_id in STYLE_IDS:
        assert s_id in STYLE_DOCS
        assert len(STYLE_DOCS[s_id]) > 0

    assert "Atmospheric tension" in STYLE_DOCS["true_crime"]
    assert "Sharp witty debate" in STYLE_DOCS["tech_roast"]
    assert "Gentle ASMR" in STYLE_DOCS["meditation"]
    assert "cyber-noir" in STYLE_DOCS["noir"]
    assert "quiz rounds" in STYLE_DOCS["trivia"]
    assert "cross-examination" in STYLE_DOCS["courtroom"]
    assert "situation room" in STYLE_DOCS["crisis_room"]


def test_style_templates_exist_and_non_empty():
    for s_id in ["true_crime", "tech_roast", "meditation", "noir", "trivia", "courtroom", "crisis_room"]:
        assert s_id in STYLE_TEMPLATES
        tmpl = STYLE_TEMPLATES[s_id]
        assert isinstance(tmpl, str)
        assert len(tmpl) > 50
        # No em-dashes anywhere
        assert "—" not in tmpl
        assert "&mdash;" not in tmpl


def test_emotion_catalogue_has_powerhouse_styles():
    for s_id in ["true_crime", "tech_roast"]:
        assert s_id in EMOTION_IDS
        assert s_id in EMOTION_DOCS
        assert s_id in EMOTION_INSTRUCTS
        assert len(EMOTION_INSTRUCTS[s_id]) > 0


def test_script_params_contain_custom_tunings():
    assert "true_crime" in SCRIPT_PARAMS
    assert SCRIPT_PARAMS["true_crime"]["turns_min"] <= SCRIPT_PARAMS["true_crime"]["turns_max"]

    assert "tech_roast" in SCRIPT_PARAMS
    assert SCRIPT_PARAMS["tech_roast"]["short_reactions"] >= 3

    assert "meditation" in SCRIPT_PARAMS
    assert SCRIPT_PARAMS["meditation"]["turn_words_max"] <= 30

    for s_id in ["noir", "trivia", "courtroom", "crisis_room"]:
        assert s_id in SCRIPT_PARAMS
        assert SCRIPT_PARAMS[s_id]["turns_min"] <= SCRIPT_PARAMS[s_id]["turns_max"]
        assert SCRIPT_PARAMS[s_id]["turn_words_max"] <= 45
        assert SCRIPT_PARAMS[s_id]["short_reactions"] >= 3


def test_hook_briefs_include_new_styles():
    for s_id in ["true_crime", "tech_roast", "meditation", "noir", "trivia", "courtroom", "crisis_room"]:
        assert s_id in HOOK_BRIEFS


def test_pipeline_style_speaker_instructs():
    instructs = pipeline._STYLE_SPEAKER_INSTRUCTS
    for s_id in ["true_crime", "tech_roast", "meditation", "noir", "trivia", "courtroom", "crisis_room"]:
        assert s_id in instructs
        assert "A" in instructs[s_id]
        assert "B" in instructs[s_id]


@pytest.mark.asyncio
async def test_script_prompt_generation_with_engine_tailoring(monkeypatch):
    captured_prompt = None

    async def fake_script_call(prompt, model, base, key="", max_tokens=8192, stream_callback=None):
        nonlocal captured_prompt
        captured_prompt = prompt
        return [
            {"speaker": "A", "text": "Turn 1 text."},
            {"speaker": "B", "text": "Turn 2 text."},
            {"speaker": "A", "text": "Turn 3 text."},
            {"speaker": "B", "text": "Turn 4 text."},
        ], "Episode description."

    monkeypatch.setattr(pipeline, "script_call", fake_script_call)

    # 1. Test true_crime with qwen_tts (prose directive, no bracketed tags)
    await pipeline._script(
        body="Body source text about mysterious event.",
        style="true_crime",
        tts_engine="qwen_tts",
        emotion="neutral",
    )
    assert captured_prompt is not None
    assert "STYLE ENGINE DIRECTIVE" in captured_prompt
    assert "Do not use bracketed tags" in captured_prompt
    assert "tension" in captured_prompt.lower()

    # 2. Test tech_roast with voxtral (expressive tags allowed)
    await pipeline._script(
        body="Body source text about a framework rewrite.",
        style="tech_roast",
        tts_engine="voxtral",
        emotion="neutral",
    )
    assert captured_prompt is not None
    assert "STYLE ENGINE DIRECTIVE" in captured_prompt
    assert "[laughs]" in captured_prompt or "[chuckles]" in captured_prompt

    # 3. Test meditation with piper (clean speech, no tags)
    await pipeline._script(
        body="Body source text about breathing techniques.",
        style="meditation",
        tts_engine="piper",
        emotion="neutral",
    )
    assert captured_prompt is not None
    assert "Do not use bracketed tags" in captured_prompt
