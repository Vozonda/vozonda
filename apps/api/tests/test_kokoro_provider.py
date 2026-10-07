from pathlib import Path

import pytest

from vozonda_api.providers.kokoro import KOKORO_VOICE_IDS, render_segment
from vozonda_api.voices import KOKORO_SPEAKERS, SPEAKER_TABLES


def test_kokoro_speaker_table_registered():
    assert "kokoro" in SPEAKER_TABLES
    ids = {s["id"] for s in KOKORO_SPEAKERS}
    assert ids == {
        "af_bella", "af_sarah", "af_nicole", "af_sky",
        "am_adam", "am_michael", "am_eric",
        "bf_emma", "bf_isabella",
        "bm_george", "bm_lewis",
    }
    assert len(KOKORO_SPEAKERS) == 11
    for s in KOKORO_SPEAKERS:
        assert "id" in s and "label" in s and "native" in s
        assert isinstance(s["id"], str) and s["id"]


def test_kokoro_voice_ids_plain_data_no_torch():
    # plain data check: no torch import required to list voices
    assert KOKORO_VOICE_IDS == {s["id"] for s in KOKORO_SPEAKERS}
    # every id follows af/am/bf/bm prefix
    for vid in KOKORO_VOICE_IDS:
        assert vid[:3] in {"af_", "am_", "bf_", "bm_"}


def test_render_segment_creates_file(tmp_path: Path):
    out = tmp_path / "seg.wav"
    result = render_segment("Hello world, this is a test.", "af_bella", out)
    assert result == out
    assert out.exists()
    assert out.stat().st_size > 44


def test_render_segment_rejects_unknown_voice(tmp_path: Path):
    out = tmp_path / "seg.wav"
    with pytest.raises(ValueError, match="unknown kokoro voice"):
        render_segment("Hello", "not_a_voice", out)


def test_render_segment_rejects_empty_text(tmp_path: Path):
    out = tmp_path / "seg.wav"
    with pytest.raises(ValueError, match="text must not be empty"):
        render_segment("   ", "af_bella", out)


def test_render_segment_fallback_without_backends(tmp_path: Path, monkeypatch):
    # Force both ONNX and HTTP to be unavailable
    import vozonda_api.providers.kokoro as kok

    monkeypatch.setattr(kok, "_try_onnx", lambda *a, **kw: False)
    monkeypatch.setattr(kok, "_try_http", lambda *a, **kw: False)
    out = tmp_path / "fallback.wav"
    result = render_segment("Fallback test text for kokoro provider.", "bf_emma", out, speed=1.0)
    assert result == out
    assert out.exists()
    assert out.stat().st_size > 44


def test_render_segment_http_fallback(monkeypatch, tmp_path: Path):
    import vozonda_api.providers.kokoro as kok

    monkeypatch.setattr(kok, "_try_onnx", lambda *a, **kw: False)

    def fake_http(text, voice_id, out_path):
        out_path.write_bytes(b"RIFF....WAVEfake")
        # ensure >44 bytes
        if out_path.stat().st_size <= 44:
            out_path.write_bytes(b"RIFF" + b"\x00" * 50)
        return True

    monkeypatch.setattr(kok, "_try_http", fake_http)
    out = tmp_path / "http.wav"
    result = render_segment("Hello via http", "am_adam", out)
    assert result == out
    assert out.exists()


def test_kokoro_provider_seam_probe_and_capabilities():
    from vozonda_api.providers import PROVIDER_CAPABILITIES, _probe_installed_engines, get_provider_capabilities

    caps = get_provider_capabilities("kokoro")
    assert caps["supports_instructions"] is False
    assert caps["supports_emotion_instructions"] is False
    assert caps["supports_paralinguistic_tags"] is False
    assert "kokoro" in PROVIDER_CAPABILITIES

    engines = _probe_installed_engines()
    ids = [e["id"] for e in engines]
    assert "kokoro" in ids
    kok = next(e for e in engines if e["id"] == "kokoro")
    assert "label" in kok and "installed" in kok and "fix" in kok
    assert "kokoro" in kok["label"].lower()


def test_kokoro_voices_groupable():
    af = [s for s in KOKORO_SPEAKERS if s["id"].startswith("af_")]
    am = [s for s in KOKORO_SPEAKERS if s["id"].startswith("am_")]
    bf = [s for s in KOKORO_SPEAKERS if s["id"].startswith("bf_")]
    bm = [s for s in KOKORO_SPEAKERS if s["id"].startswith("bm_")]
    assert len(af) == 4
    assert len(am) == 3
    assert len(bf) == 2
    assert len(bm) == 2
