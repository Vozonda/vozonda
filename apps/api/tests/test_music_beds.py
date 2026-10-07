"""Tests for audio DSP intro/outro music beds and ducking in master stage (Gitea #113).

Covers:
- Procedural harmonic jingle synthesis (intro and outro)
- Intro ducking envelope (-12dB under opening dialogue turns for 3-5s)
- Outro envelope (ducked under sign-off turn, swells after speech ends)
- mix_music_beds DSP mixing, peak limiting, and turn duration adaptation
- Custom audio track loading, resampling, and format handling
- apply_music_beds_to_file WAV file processing
- render_vozonda and pipeline integration
- settings_store music keys roundtrip and validation
"""

import numpy as np
import pytest
import soundfile as sf

from vozonda_api.music import (
    apply_music_beds_to_file,
    build_intro_envelope,
    build_outro_envelope,
    find_music_assets,
    generate_jingle,
    load_audio_track,
    mix_music_beds,
)
from vozonda_api.pipeline import _is_music_enabled, _master
try:  # the Qwen renderer imports torch (the tts-qwen extra); its test skips without it
    from vozonda_api.render_vozonda import apply_music_beds as render_apply_music_beds
except ImportError:
    render_apply_music_beds = None
from vozonda_api.settings_store import all_settings, get_setting, set_setting

# ---------------------------------------------------------------------------
# 1. Procedural Jingle Synthesis
# ---------------------------------------------------------------------------


def test_generate_jingle_intro():
    sr = 24000
    dur = 6.0
    jingle = generate_jingle(duration=dur, sr=sr, is_outro=False)
    assert isinstance(jingle, np.ndarray)
    assert jingle.dtype == np.float32
    assert len(jingle) == int(sr * dur)
    assert np.max(np.abs(jingle)) > 0.05
    assert np.max(np.abs(jingle)) <= 1.0


def test_generate_jingle_outro():
    sr = 24000
    dur = 8.0
    jingle = generate_jingle(duration=dur, sr=sr, is_outro=True)
    assert isinstance(jingle, np.ndarray)
    assert jingle.dtype == np.float32
    assert len(jingle) == int(sr * dur)
    assert np.max(np.abs(jingle)) > 0.05
    assert np.max(np.abs(jingle)) <= 1.0


def test_generate_jingle_sample_rates():
    for sr in (16000, 22050, 24000, 44100):
        jingle = generate_jingle(duration=2.0, sr=sr, is_outro=False)
        assert len(jingle) == int(sr * 2.0)


# ---------------------------------------------------------------------------
# 2. Ducking Envelopes
# ---------------------------------------------------------------------------


def test_build_intro_envelope_ducking_level():
    sr = 24000
    duck_gain = float(10.0 ** (-12.0 / 20.0))  # ~0.2512
    total_samples = int(8.0 * sr)
    env = build_intro_envelope(
        total_samples=total_samples,
        sr=sr,
        duck_gain=duck_gain,
        intro_duck_s=4.0,
        speech_dur=20.0,
    )

    # 1. Starts at 0, ramps up
    assert env[0] == 0.0
    # At t=0.4s (end of fade-in), should be near peak 1.0
    idx_peak = int(0.4 * sr)
    assert np.isclose(env[idx_peak], 1.0, atol=0.05)

    # At t=2.0s (during ducked hold), should be at -12dB (0.2512)
    idx_duck = int(2.0 * sr)
    assert np.isclose(env[idx_duck], duck_gain, atol=0.01)

    # At t=7.5s (after fade-out), should be 0.0
    idx_end = int(7.5 * sr)
    assert env[idx_end] == 0.0


def test_build_outro_envelope_ducking_and_swell():
    sr = 24000
    duck_gain = float(10.0 ** (-12.0 / 20.0))  # ~0.2512
    overlap_samples = int(3.5 * sr)
    total_samples = int(7.0 * sr)

    env = build_outro_envelope(
        outro_dur_samples=total_samples,
        overlap_samples=overlap_samples,
        sr=sr,
        duck_gain=duck_gain,
    )

    # Under speech (before speech ends at overlap_samples):
    # At t = 2.0s (during dialogue overlap), ducked at duck_gain
    idx_under_speech = int(2.0 * sr)
    assert np.isclose(env[idx_under_speech], duck_gain, atol=0.01)

    # After speech ends (at t = 4.5s), swells to 1.0 (full volume)
    idx_solo = int(4.8 * sr)
    assert np.isclose(env[idx_solo], 1.0, atol=0.05)

    # At the very end (t = 6.9s), fades out towards 0.0
    idx_tail = int(6.9 * sr)
    assert env[idx_tail] < 0.15


# ---------------------------------------------------------------------------
# 3. DSP Mixing (mix_music_beds)
# ---------------------------------------------------------------------------


def test_mix_music_beds_synthetic_speech():
    sr = 24000
    speech_dur = 10.0
    t = np.linspace(0, speech_dur, int(sr * speech_dur), endpoint=False, dtype=np.float32)
    speech = 0.4 * np.sin(2 * np.pi * 300 * t)

    mixed = mix_music_beds(
        speech=speech,
        sr=sr,
        duck_db=-12.0,
        intro_duck_s=4.0,
        outro_tail_s=3.5,
    )

    # Total duration should be speech duration + outro tail
    expected_samples = len(speech) + int(3.5 * sr)
    assert len(mixed) == expected_samples

    # Audio should not clip
    assert np.max(np.abs(mixed)) <= 1.0

    # Intro portion has combined audio
    assert np.max(np.abs(mixed[:int(1.0 * sr)])) > 0.01

    # Outro tail (after speech ends) has pure music
    outro_tail = mixed[len(speech):]
    assert len(outro_tail) == int(3.5 * sr)
    assert np.max(np.abs(outro_tail)) > 0.01


def test_mix_music_beds_turn_durations_adaptation():
    sr = 24000
    speech_dur = 12.0
    speech = np.zeros(int(sr * speech_dur), dtype=np.float32)
    turn_durations = [2.0, 2.5, 4.0, 3.5]  # Opening turns: 4.5s total, Closing turn: 3.5s

    mixed = mix_music_beds(
        speech=speech,
        sr=sr,
        turn_durations=turn_durations,
    )
    assert len(mixed) > len(speech)
    assert np.max(np.abs(mixed)) > 0.0


def test_mix_music_beds_custom_tracks(tmp_path):
    sr = 24000
    speech = np.zeros(int(sr * 6.0), dtype=np.float32)

    # Generate custom intro and outro wav files
    intro_wav = tmp_path / "custom_intro.wav"
    outro_wav = tmp_path / "custom_outro.wav"
    custom_intro = 0.5 * np.sin(2 * np.pi * 440 * np.linspace(0, 5.0, int(sr * 5.0), dtype=np.float32))
    custom_outro = 0.5 * np.sin(2 * np.pi * 880 * np.linspace(0, 5.0, int(sr * 5.0), dtype=np.float32))
    sf.write(str(intro_wav), custom_intro, sr)
    sf.write(str(outro_wav), custom_outro, sr)

    mixed = mix_music_beds(
        speech=speech,
        sr=sr,
        intro_music=intro_wav,
        outro_music=outro_wav,
    )
    assert len(mixed) > len(speech)
    assert np.max(np.abs(mixed)) > 0.0


def test_mix_music_beds_edge_cases():
    sr = 24000
    # Empty speech
    empty_speech = np.array([], dtype=np.float32)
    res = mix_music_beds(empty_speech, sr=sr)
    assert len(res) == 0

    # Extremely short speech (< 1s)
    short_speech = np.ones(int(0.5 * sr), dtype=np.float32) * 0.1
    res_short = mix_music_beds(short_speech, sr=sr)
    assert len(res_short) > len(short_speech)
    assert np.max(np.abs(res_short)) <= 1.0

    # Stereo input should be downmixed to mono
    stereo_speech = np.ones((int(2.0 * sr), 2), dtype=np.float32) * 0.1
    res_stereo = mix_music_beds(stereo_speech, sr=sr)
    assert res_stereo.ndim == 1


# ---------------------------------------------------------------------------
# 4. File-Level Processing
# ---------------------------------------------------------------------------


def test_apply_music_beds_to_file(tmp_path):
    sr = 24000
    wav_path = tmp_path / "speech.wav"
    out_path = tmp_path / "speech_mastered.wav"

    speech = 0.3 * np.sin(2 * np.pi * 220 * np.linspace(0, 5.0, int(sr * 5.0), dtype=np.float32))
    sf.write(str(wav_path), speech, sr)

    applied = apply_music_beds_to_file(
        wav_path=wav_path,
        out_path=out_path,
        intro_duck_s=3.0,
    )
    assert applied.exists()
    data, read_sr = sf.read(str(applied), dtype="float32")
    assert read_sr == sr
    assert len(data) > len(speech)


def test_load_audio_track_resampling(tmp_path):
    orig_sr = 44100
    target_sr = 24000
    wav_path = tmp_path / "track_44k.wav"
    sig = np.sin(2 * np.pi * 440 * np.linspace(0, 2.0, int(orig_sr * 2.0), dtype=np.float32))
    sf.write(str(wav_path), sig, orig_sr)

    loaded = load_audio_track(wav_path, target_sr=target_sr)
    assert len(loaded) == int(target_sr * 2.0)
    assert loaded.dtype == np.float32


def test_find_music_assets(tmp_path):
    intro_p, outro_p = find_music_assets(tmp_path)
    # Empty dir should return None
    assert intro_p is None
    assert outro_p is None

    # Create dummy music files
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    (music_dir / "intro.wav").write_bytes(b"RIFF" + b"\x00" * 200)
    (music_dir / "outro.wav").write_bytes(b"RIFF" + b"\x00" * 200)

    found_intro, found_outro = find_music_assets(tmp_path)
    assert found_intro is not None
    assert found_outro is not None


# ---------------------------------------------------------------------------
# 5. Integration with render_vozonda & pipeline
# ---------------------------------------------------------------------------


def test_render_vozonda_apply_music_beds():
    if render_apply_music_beds is None:
        pytest.skip("needs torch (tts-qwen extra)")
    sr = 24000
    audio = 0.2 * np.sin(2 * np.pi * 300 * np.linspace(0, 6.0, int(sr * 6.0), dtype=np.float32))

    # Enabled via config
    cfg_on = {"music_bed": True}
    res_on = render_apply_music_beds(audio, sr, cfg_on)
    assert len(res_on) > len(audio)

    # Disabled via config
    cfg_off = {"music_bed": False}
    res_off = render_apply_music_beds(audio, sr, cfg_off)
    assert len(res_off) == len(audio)


def test_is_music_enabled(tmp_path, monkeypatch):
    from vozonda_api.jobs import JobStore

    db_path = tmp_path / "test_music_jobs.db"
    monkeypatch.setenv("VOZONDA_DB", str(db_path))
    store = JobStore()
    job_id = "job-music-test"
    store.create(job_id, "http://example.com")

    # Explicit job flag
    assert _is_music_enabled(store, job_id, {"music_bed": True}) is True
    assert _is_music_enabled(store, job_id, {"music_bed": False}) is False

    # Settings store key
    set_setting("music.enabled", "true")
    assert _is_music_enabled(store, job_id) is True
    set_setting("music.enabled", "false")
    assert _is_music_enabled(store, job_id) is False


@pytest.mark.asyncio
async def test_master_with_music_bed(tmp_path, monkeypatch):
    import vozonda_api.pipeline as pl_mod

    monkeypatch.setattr(pl_mod, "MEDIA_DIR", tmp_path)

    sr = 24000
    wav_path = tmp_path / "test_master.wav"
    speech = 0.2 * np.sin(2 * np.pi * 300 * np.linspace(0, 4.0, int(sr * 4.0), dtype=np.float32))
    sf.write(str(wav_path), speech, sr)

    mp3_path = await _master(wav_path, "test_master", speed=1.0, music_bed=True)
    assert mp3_path.exists()
    assert mp3_path.stat().st_size > 500


# ---------------------------------------------------------------------------
# 6. Settings Store Roundtrip & Validation
# ---------------------------------------------------------------------------


def test_music_settings_roundtrip():
    set_setting("music.enabled", "true")
    assert get_setting("music.enabled") == "true"

    set_setting("music.duck_db", "-12")
    assert get_setting("music.duck_db") == "-12"

    set_setting("music.duck_db", "-40")  # Clamped to -30
    assert get_setting("music.duck_db") == "-30"

    assert "music.enabled" in all_settings()
