"""Default voice casts give every host a different voice (2026-09-23: English
two-host episodes rendered as 'ryan' + 'ryan', one voice talking to itself)."""

from vozonda_api.voices import DEFAULT_TIMBRE_FOR, KOKORO_DEFAULTS, KOKORO_SPEAKERS, QWEN_SPEAKERS


def test_every_language_casts_distinct_hosts():
    for lang, cast in DEFAULT_TIMBRE_FOR.items():
        assert len({cast["a"], cast["b"], cast["c"]}) == 3, (lang, cast)


def test_default_casts_use_real_qwen_voices():
    ids = {s["id"] for s in QWEN_SPEAKERS}
    for lang, cast in DEFAULT_TIMBRE_FOR.items():
        assert set(cast.values()) <= ids, (lang, cast)


def test_kokoro_casts_are_distinct_and_real():
    ids = {s["id"] for s in KOKORO_SPEAKERS}
    for lang, cast in KOKORO_DEFAULTS.items():
        assert len({cast["a"], cast["b"], cast["c"]}) == 3, (lang, cast)
        assert set(cast.values()) <= ids, (lang, cast)


def test_each_engine_gets_a_cast_of_its_own_voices():
    """Every engine used to get the qwen table; kokoro/dia2 then got 'ryan'."""
    from vozonda_api.voices import default_cast_for, speakers_for

    for engine in ("kokoro", "dia2"):
        ids = {s["id"] for s in speakers_for(engine)}
        cast = default_cast_for(engine)["en"]
        assert set(cast.values()) <= ids, (engine, cast)
        assert len({cast["a"], cast["b"]}) == 2, (engine, cast)
    assert default_cast_for("qwen_tts")["en"]["b"] == "serena"


def test_meta_serves_the_cast_of_the_active_engine(monkeypatch):
    from fastapi.testclient import TestClient

    from vozonda_api import main

    monkeypatch.setattr("vozonda_api.settings_store.get_setting", lambda k: "kokoro" if k == "tts.engine" else None)
    cast = TestClient(main.app).get("/meta").json()["default_timbre_for"]["en"]
    assert cast["a"] == "af_bella" and cast["b"] == "am_adam"
