"""Turn cache of the Qwen renderer: a hit must load (it crashed with ValueError before), and any
change to text, voice, instruction or language must miss."""

import numpy as np
import pytest
import soundfile as sf

render = pytest.importorskip("vozonda_api.render_vozonda", reason="needs torch (tts-qwen extra)")


def test_cache_hit_loads_mono_audio(tmp_path):
    path = render.turn_cache_path(tmp_path, 3, "A", "Hello there.", "aiden", "calm", "English")
    sf.write(path, np.stack([np.ones(2400), np.zeros(2400)], axis=1).astype(np.float32), 24000)
    wav, sr = render.read_cached_turn(path)
    assert sr == 24000
    assert wav.dtype == np.float32 and wav.ndim == 1 and len(wav) == 2400
    assert np.allclose(wav, 0.5, atol=1e-3)  # 16-bit PCM rounds 1.0 to 0.99997


def test_missing_or_empty_cache_is_a_miss(tmp_path):
    path = tmp_path / "0000_A_x.wav"
    assert render.read_cached_turn(path) is None
    path.write_bytes(b"\0" * 44)
    assert render.read_cached_turn(path) is None


def test_every_audio_input_changes_the_cache_name(tmp_path):
    base = ("Hello there.", "aiden", "calm", "English")
    names = {render.turn_cache_path(tmp_path, 0, "A", *base).name}
    for i in range(4):
        changed = list(base)
        changed[i] += "x"
        names.add(render.turn_cache_path(tmp_path, 0, "A", *changed).name)
    assert len(names) == 5
    # position and speaker stay readable in the name
    assert render.turn_cache_path(tmp_path, 7, "B", *base).name.startswith("0007_B_")
