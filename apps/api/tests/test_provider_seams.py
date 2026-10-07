import re

from vozonda_api.providers import get_provider_capabilities, resolve_emotion_delivery
from vozonda_api.styles import EMOTION_DOCS, EMOTION_IDS, EMOTION_INSTRUCTS


def test_provider_capabilities_declared_engines():
    voxtral_caps = get_provider_capabilities("voxtral")
    assert voxtral_caps["supports_instructions"] is True
    assert voxtral_caps["supports_emotion_instructions"] is True
    assert voxtral_caps["supports_paralinguistic_tags"] is True

    qwen_caps = get_provider_capabilities("qwen_tts")
    assert qwen_caps["supports_instructions"] is True
    assert qwen_caps["supports_emotion_instructions"] is True
    assert qwen_caps["supports_paralinguistic_tags"] is False

    piper_caps = get_provider_capabilities("piper")
    assert piper_caps["supports_instructions"] is False
    assert piper_caps["supports_emotion_instructions"] is False
    assert piper_caps["supports_paralinguistic_tags"] is False


def test_provider_capabilities_unknown_and_none():
    unknown_caps = get_provider_capabilities("unknown_future_tts")
    assert unknown_caps["supports_instructions"] is False
    assert unknown_caps["supports_emotion_instructions"] is False
    assert unknown_caps["supports_paralinguistic_tags"] is False

    none_caps = get_provider_capabilities(None)
    assert none_caps["supports_instructions"] is True
    assert none_caps["supports_emotion_instructions"] is True
    assert none_caps["supports_paralinguistic_tags"] is False


def test_resolve_emotion_delivery_voxtral_expressive():
    res = resolve_emotion_delivery("voxtral", emotion="energetic")
    assert res["supports_paralinguistic_tags"] is True
    assert res["supports_emotion_instructions"] is True
    assert "OVERALL EMOTIONAL REGISTER: Shape the dialogue energy and host interaction to be energetic." in res["prompt_directive"]
    assert "[laughs]" in res["prompt_directive"]
    assert "energetically" in res["instruct_text"]


def test_resolve_emotion_delivery_qwen_prose_directive():
    res = resolve_emotion_delivery("qwen_tts", emotion="dramatic")
    assert res["supports_paralinguistic_tags"] is False
    assert res["supports_emotion_instructions"] is True
    assert "OVERALL EMOTIONAL REGISTER: Shape the dialogue energy and host interaction to be dramatic." in res["prompt_directive"]
    assert "TTS PROSE DIRECTIVE: Do not use bracketed tags" in res["prompt_directive"]
    assert "dramatically" in res["instruct_text"]


def test_resolve_emotion_delivery_piper_no_instructs():
    res = resolve_emotion_delivery("piper", emotion="cheerful")
    assert res["supports_paralinguistic_tags"] is False
    assert res["supports_emotion_instructions"] is False
    assert "TTS PROSE DIRECTIVE" in res["prompt_directive"]
    assert res["instruct_text"] is None


def test_resolve_emotion_delivery_style_override_asmr_and_futbol():
    res_asmr = resolve_emotion_delivery("qwen_tts", emotion="neutral", style="asmr")
    assert "softly and slowly" in res_asmr["instruct_text"]

    res_futbol = resolve_emotion_delivery("qwen_tts", emotion="neutral", style="futbol")
    assert "football commentator" in res_futbol["instruct_text"]

    res_piper = resolve_emotion_delivery("piper", emotion="neutral", style="futbol")
    assert res_piper["instruct_text"] is None


def test_resolve_emotion_delivery_all_catalog_emotions():
    for emo in EMOTION_IDS:
        res = resolve_emotion_delivery("qwen_tts", emotion=emo)
        assert emo in res["prompt_directive"]
        if emo == "neutral":
            assert res["instruct_text"] is None
        else:
            assert res["instruct_text"] == EMOTION_INSTRUCTS[emo]


def test_resolve_emotion_delivery_whitespace_and_case():
    res = resolve_emotion_delivery("qwen_tts", emotion="  WARM  ")
    assert "warm" in res["prompt_directive"]
    assert res["instruct_text"] == EMOTION_INSTRUCTS["warm"]


def test_tag_sanitization_regex_patterns():
    pattern_bracket = r'\[[a-zA-Z0-9\s_,-]+\]'
    pattern_paren = r'\([a-zA-Z0-9\s_,-]+\)'

    samples = [
        ("Hello [laughs] world", "Hello  world"),
        ("Check this [laugh_1] out", "Check this  out"),
        ("Wait [gasp,quiet] now", "Wait  now"),
        ("Hello (whisper123) friend", "Hello  friend"),
    ]

    for raw, expected in samples:
        cleaned = re.sub(pattern_bracket, '', raw)
        cleaned = re.sub(pattern_paren, '', cleaned)
        assert cleaned == expected


def test_styles_emotion_catalogue_consistency():
    for emo in EMOTION_IDS:
        assert emo in EMOTION_DOCS
        assert emo in EMOTION_INSTRUCTS


def test_resolve_emotion_delivery_powerhouse_styles_instructions():
    # true_crime
    tc_qwen = resolve_emotion_delivery("qwen_tts", emotion="neutral", style="true_crime")
    assert "atmospheric tension" in tc_qwen["instruct_text"].lower()
    assert "STYLE ENGINE DIRECTIVE" in tc_qwen["prompt_directive"]
    assert "Do not use bracketed tags" in tc_qwen["prompt_directive"]

    tc_voxtral = resolve_emotion_delivery("voxtral", emotion="neutral", style="true_crime")
    assert "[gasps]" in tc_voxtral["prompt_directive"] or "[whisper]" in tc_voxtral["prompt_directive"]

    # tech_roast
    tr_qwen = resolve_emotion_delivery("qwen_tts", emotion="neutral", style="tech_roast")
    assert "sharp wit" in tr_qwen["instruct_text"].lower()
    assert "STYLE ENGINE DIRECTIVE" in tr_qwen["prompt_directive"]
    assert "Do not use bracketed tags" in tr_qwen["prompt_directive"]

    tr_voxtral = resolve_emotion_delivery("voxtral", emotion="neutral", style="tech_roast")
    assert "[laughs]" in tr_voxtral["prompt_directive"] or "[chuckles]" in tr_voxtral["prompt_directive"]

    # meditation
    mz_qwen = resolve_emotion_delivery("qwen_tts", emotion="neutral", style="meditation")
    assert "soothing asmr" in mz_qwen["instruct_text"].lower()
    assert "STYLE ENGINE DIRECTIVE" in mz_qwen["prompt_directive"]
    assert "Do not use bracketed tags" in mz_qwen["prompt_directive"]

    mz_voxtral = resolve_emotion_delivery("voxtral", emotion="neutral", style="meditation")
    assert "[whisper]" in mz_voxtral["prompt_directive"] or "[sighs]" in mz_voxtral["prompt_directive"]

    # piper (no instructs)
    tc_piper = resolve_emotion_delivery("piper", emotion="neutral", style="true_crime")
    assert tc_piper["instruct_text"] is None

