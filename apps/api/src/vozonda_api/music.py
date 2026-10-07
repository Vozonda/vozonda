from pathlib import Path

import numpy as np
import soundfile as sf

DEFAULT_DUCK_DB = -12.0
DEFAULT_INTRO_DUCK_S = 4.0
DEFAULT_OUTRO_OVERLAP_S = 3.5
DEFAULT_OUTRO_TAIL_S = 3.5


JINGLE_PALETTES: dict[str, dict[str, list[tuple[float, float, list[float]]]]] = {
    "jazz_calm": {
        "intro": [
            (0.0, 2.0, [261.63, 329.63, 392.00, 493.88, 587.33]),   # Cmaj9
            (1.8, 2.2, [174.61, 261.63, 329.63, 440.00, 523.25]),   # Fmaj7
            (3.8, 2.2, [196.00, 293.66, 392.00, 523.25, 587.33]),   # Gsus4
            (5.8, 2.5, [130.81, 196.00, 329.63, 392.00, 523.25]),   # Cadd9
        ],
        "outro": [
            (0.0, 2.5, [174.61, 261.63, 329.63, 440.00]),           # Fmaj7
            (2.2, 2.5, [196.00, 246.94, 293.66, 392.00, 493.88]),   # G7
            (4.4, 4.0, [130.81, 196.00, 261.63, 329.63, 392.00, 493.88]),  # Cmaj9 resolve
        ],
    },
    "tech_pulse": {
        "intro": [
            (0.0, 1.8, [220.00, 261.63, 329.63, 392.00, 493.88]),   # Am9
            (1.6, 2.0, [174.61, 220.00, 261.63, 329.63, 392.00]),   # Fmaj7
            (3.4, 2.0, [146.83, 220.00, 261.63, 349.23, 440.00]),   # Dm7
            (5.2, 2.8, [164.81, 246.94, 329.63, 392.00, 493.88]),   # Em7
        ],
        "outro": [
            (0.0, 2.2, [146.83, 220.00, 261.63, 349.23]),           # Dm7
            (2.0, 2.2, [164.81, 246.94, 329.63, 392.00]),           # Em7
            (4.0, 4.0, [110.00, 220.00, 261.63, 329.63, 440.00]),   # Am9 resolve
        ],
    },
    "dramatic_swell": {
        "intro": [
            (0.0, 2.2, [146.83, 220.00, 261.63, 349.23, 440.00]),   # Dm9
            (2.0, 2.2, [116.54, 174.61, 233.08, 293.66, 349.23]),   # Bbmaj7
            (4.0, 2.2, [98.00, 146.83, 196.00, 233.08, 293.66]),    # Gm9
            (6.0, 3.0, [110.00, 220.00, 277.18, 329.63, 440.00]),   # A7sus4
        ],
        "outro": [
            (0.0, 2.4, [98.00, 146.83, 196.00, 233.08]),            # Gm9
            (2.2, 2.4, [110.00, 164.81, 220.00, 277.18]),           # A7
            (4.4, 4.0, [73.42, 146.83, 220.00, 261.63, 349.23]),    # Dm resolve
        ],
    },
    "lofi_chill": {
        "intro": [
            (0.0, 2.2, [155.56, 233.08, 293.66, 349.23, 440.00]),   # Ebmaj7
            (2.0, 2.2, [103.83, 155.56, 207.65, 261.63, 311.13]),   # Abmaj7
            (4.0, 2.2, [87.31, 130.81, 174.61, 207.65, 261.63]),    # Fm7
            (6.0, 2.8, [116.54, 174.61, 233.08, 293.66, 349.23]),   # Bb9
        ],
        "outro": [
            (0.0, 2.5, [87.31, 130.81, 174.61, 207.65]),            # Fm7
            (2.2, 2.5, [116.54, 174.61, 233.08, 293.66]),           # Bb7
            (4.4, 4.0, [77.78, 155.56, 233.08, 293.66, 349.23]),    # Ebmaj7 resolve
        ],
    },
    "energetic_brass": {
        "intro": [
            (0.0, 1.8, [196.00, 246.94, 293.66, 392.00, 493.88]),   # Gmaj7
            (1.6, 1.8, [130.81, 196.00, 261.63, 329.63, 392.00]),   # Cmaj7
            (3.2, 1.8, [146.83, 220.00, 293.66, 369.99, 440.00]),   # D7
            (4.8, 2.5, [98.00, 196.00, 246.94, 293.66, 392.00]),    # G
        ],
        "outro": [
            (0.0, 2.0, [130.81, 196.00, 261.63, 329.63]),           # Cmaj7
            (1.8, 2.0, [146.83, 220.00, 293.66, 369.99]),           # D7
            (3.6, 4.0, [98.00, 196.00, 293.66, 392.00]),            # G resolve
        ],
    },
}


def style_to_jingle_preset(style: str) -> str:
    """Map a podcast style or template to its recommended jingle harmonic palette."""
    s = (style or "").lower()
    if any(k in s for k in ("news", "serious", "eli5", "conspiracy", "briefing")):
        return "tech_pulse"
    if any(k in s for k in ("duel", "debate", "drama", "storyteller", "sensational", "crime", "socrates")):
        return "dramatic_swell"
    if any(k in s for k in ("asmr", "meditation", "chill", "solo")):
        return "lofi_chill"
    if any(k in s for k in ("futbol", "dude", "slang", "witty", "clash", "stadium", "roast")):
        return "energetic_brass"
    return "jazz_calm"


def generate_jingle(
    duration: float = 8.0,
    sr: int = 24000,
    is_outro: bool = False,
    palette: str = "jazz_calm",
) -> np.ndarray:
    """Generate a clean procedural harmonic music jingle bed using pure numpy.

    Supports custom harmonic palettes: jazz_calm, tech_pulse, dramatic_swell, lofi_chill, energetic_brass.
    """
    duration = max(1.0, float(duration))
    total_samples = int(sr * duration)
    t = np.linspace(0, duration, total_samples, endpoint=False, dtype=np.float32)
    out = np.zeros(total_samples, dtype=np.float32)

    pal = JINGLE_PALETTES.get(palette, JINGLE_PALETTES["jazz_calm"])
    chords = pal["outro"] if is_outro else pal["intro"]

    for start_t, dur, freqs in chords:
        start_idx = int(start_t * sr)
        dur_samples = int(dur * sr)
        end_idx = min(total_samples, start_idx + dur_samples)
        if start_idx >= total_samples:
            continue
        chord_t = t[start_idx:end_idx] - start_t

        env = np.exp(-chord_t / (dur * 0.45)) * (1.0 - np.exp(-chord_t / 0.02))

        chord_sig = np.zeros_like(chord_t)
        for f in freqs:
            # Fundamental and musical overtones with subtle detuning chorus
            h1 = np.sin(2 * np.pi * f * chord_t)
            h2 = 0.35 * np.sin(2 * np.pi * (2 * f + 0.3) * chord_t)
            h3 = 0.12 * np.sin(2 * np.pi * (3 * f - 0.2) * chord_t)
            h4 = 0.04 * np.sin(2 * np.pi * 4 * f * chord_t)
            chord_sig += (h1 + h2 + h3 + h4) / len(freqs)

        out[start_idx:end_idx] += (chord_sig * env * 0.45).astype(np.float32)

    # Warm analog saturation
    out = (np.tanh(out * 1.25) * 0.8).astype(np.float32)
    return out


def load_audio_track(source: str | Path | np.ndarray, target_sr: int = 24000) -> np.ndarray:
    """Load an audio track from numpy array or file path (WAV/MP3/FLAC/OGG), resampled to mono target_sr."""
    if isinstance(source, np.ndarray):
        wav = source.astype(np.float32)
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        return wav

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Audio track not found: {path}")

    wav, sr = sf.read(str(path), dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)

    if sr != target_sr:
        # Resample using linear interpolation if sample rates differ
        target_len = int(len(wav) * target_sr / sr)
        orig_indices = np.linspace(0, len(wav) - 1, target_len)
        wav = np.interp(orig_indices, np.arange(len(wav)), wav).astype(np.float32)

    return wav.astype(np.float32)


def find_music_assets(media_dir: Path | None = None) -> tuple[Path | None, Path | None]:
    """Find intro and outro music tracks in media directory or standard paths."""
    search_dirs: list[Path] = []
    if media_dir:
        search_dirs.extend([media_dir / "music", media_dir])

    # Check package-level assets
    pkg_assets = Path(__file__).resolve().parent / "assets" / "music"
    search_dirs.append(pkg_assets)

    intro_path: Path | None = None
    outro_path: Path | None = None

    for d in search_dirs:
        if not d.exists() or not d.is_dir():
            continue
        if intro_path is None:
            for ext in (".mp3", ".wav", ".flac", ".ogg"):
                for name in ("intro", "intro_music", "jingle_intro", "theme", "bed"):
                    p = d / f"{name}{ext}"
                    if p.exists() and p.stat().st_size > 100:
                        intro_path = p
                        break
                if intro_path:
                    break
        if outro_path is None:
            for ext in (".mp3", ".wav", ".flac", ".ogg"):
                for name in ("outro", "outro_music", "jingle_outro", "theme", "bed"):
                    p = d / f"{name}{ext}"
                    if p.exists() and p.stat().st_size > 100:
                        outro_path = p
                        break
                if outro_path:
                    break

    return intro_path, outro_path


def build_intro_envelope(
    total_samples: int,
    sr: int,
    duck_gain: float,
    intro_duck_s: float = DEFAULT_INTRO_DUCK_S,
    speech_dur: float = 10.0,
) -> np.ndarray:
    """Build smooth ducking envelope for intro music bed.

    Structure:
    1. Fade in from 0 to 1.0 (0.4s)
    2. Duck smoothly to duck_gain (-12dB) over 0.6s
    3. Hold ducked under dialogue for intro_duck_s (3-5s)
    4. Fade out smoothly to 0.0 over 1.5s
    """
    env = np.zeros(total_samples, dtype=np.float32)
    t_in_fade = 0.4
    t_in_duck_trans = 0.6
    t_in_hold = min(intro_duck_s, max(0.5, speech_dur - 1.0))
    t_in_fade_out = 1.5

    n_f1 = max(1, int(t_in_fade * sr))
    n_d1 = max(1, int(t_in_duck_trans * sr))
    n_h = max(1, int(t_in_hold * sr))
    n_f2 = max(1, int(t_in_fade_out * sr))

    # 1. Fade in 0 -> 1.0 (raised cosine S-curve)
    idx = 0
    f1_len = min(n_f1, total_samples - idx)
    if f1_len > 0:
        env[idx:idx + f1_len] = 0.5 * (1.0 - np.cos(np.pi * np.linspace(0, 1, f1_len)))
        idx += f1_len

    # 2. Duck 1.0 -> duck_gain
    d1_len = min(n_d1, total_samples - idx)
    if d1_len > 0:
        ramp = 1.0 - (1.0 - duck_gain) * 0.5 * (1.0 - np.cos(np.pi * np.linspace(0, 1, d1_len)))
        env[idx:idx + d1_len] = ramp
        idx += d1_len

    # 3. Hold at duck_gain
    h_len = min(n_h, total_samples - idx)
    if h_len > 0:
        env[idx:idx + h_len] = duck_gain
        idx += h_len

    # 4. Fade out duck_gain -> 0.0
    f2_len = min(n_f2, total_samples - idx)
    if f2_len > 0:
        env[idx:idx + f2_len] = duck_gain * 0.5 * (1.0 + np.cos(np.pi * np.linspace(0, 1, f2_len)))
        idx += f2_len

    return env


def build_outro_envelope(
    outro_dur_samples: int,
    overlap_samples: int,
    sr: int,
    duck_gain: float,
) -> np.ndarray:
    """Build smooth ducking and swell envelope for outro music bed.

    Structure:
    1. Under final dialogue: fade in 0 -> duck_gain (-12dB) over 1.0s, hold at duck_gain until speech ends
    2. At speech end: swell duck_gain -> 1.0 (full volume) over 0.8s
    3. Solo outro: hold at 1.0 for 1.5s
    4. Fade out: 1.0 -> 0.0 over 1.5s
    """
    env = np.zeros(outro_dur_samples, dtype=np.float32)

    # 1. Under speech: fade in from 0 to duck_gain
    n_out_fadein = min(int(1.0 * sr), overlap_samples)
    if n_out_fadein > 0:
        env[:n_out_fadein] = duck_gain * 0.5 * (1.0 - np.cos(np.pi * np.linspace(0, 1, n_out_fadein)))
    if overlap_samples > n_out_fadein:
        env[n_out_fadein:overlap_samples] = duck_gain

    # 2. At speech end (overlap_samples): swell from duck_gain to 1.0
    n_swell = int(0.8 * sr)
    n_solo = int(1.5 * sr)
    idx_swell = overlap_samples
    if idx_swell < outro_dur_samples:
        actual_swell = min(n_swell, outro_dur_samples - idx_swell)
        env[idx_swell:idx_swell + actual_swell] = duck_gain + (1.0 - duck_gain) * 0.5 * (
            1.0 - np.cos(np.pi * np.linspace(0, 1, actual_swell))
        )
    idx_solo = idx_swell + n_swell
    if idx_solo < outro_dur_samples:
        actual_solo = min(n_solo, outro_dur_samples - idx_solo)
        env[idx_solo:idx_solo + actual_solo] = 1.0
    idx_out_fadeout = idx_solo + n_solo
    if idx_out_fadeout < outro_dur_samples:
        actual_out_fadeout = outro_dur_samples - idx_out_fadeout
        env[idx_out_fadeout:] = 0.5 * (1.0 + np.cos(np.pi * np.linspace(0, 1, actual_out_fadeout)))

    return env


def mix_music_beds(
    speech: np.ndarray,
    sr: int = 24000,
    intro_music: np.ndarray | str | Path | None = None,
    outro_music: np.ndarray | str | Path | None = None,
    duck_db: float = DEFAULT_DUCK_DB,
    intro_duck_s: float = DEFAULT_INTRO_DUCK_S,
    outro_overlap_s: float = DEFAULT_OUTRO_OVERLAP_S,
    outro_tail_s: float = DEFAULT_OUTRO_TAIL_S,
    turn_durations: list[float] | None = None,
    jingle_palette: str = "jazz_calm",
) -> np.ndarray:
    """Mix optional intro and outro musical jingle beds into speech audio.

    Requirements (issue #113):
    - Intro music fades in, ducks smoothly (-12dB) under the hosts' opening dialogue turns for 3-5s, and fades out.
    - Outro music fades in under the final sign-off dialogue turn and concludes after the speech ends.
    """
    if speech.ndim > 1:
        speech = speech.mean(axis=1)
    speech = speech.astype(np.float32)
    n_speech = len(speech)
    speech_dur = n_speech / sr if sr > 0 else 0.0

    if speech_dur <= 0.0:
        return speech

    # Use ground-truth turn durations if available to adapt ducking timing
    if turn_durations and len(turn_durations) > 0:
        if len(turn_durations) >= 2:
            intro_duck_s = max(3.0, min(5.0, float(turn_durations[0] + turn_durations[1])))
        else:
            intro_duck_s = max(3.0, min(5.0, float(turn_durations[0])))
        outro_overlap_s = max(2.0, min(5.0, float(turn_durations[-1])))

    duck_gain = float(10.0 ** (duck_db / 20.0))  # -12 dB = ~0.2512

    outro_tail_samples = int(outro_tail_s * sr)
    total_samples = n_speech + outro_tail_samples
    mixed = np.zeros(total_samples, dtype=np.float32)
    mixed[:n_speech] += speech

    # --- 1. Intro Music Bed ---
    t_intro_total = 0.4 + 0.6 + intro_duck_s + 1.5
    intro_samples = int(t_intro_total * sr)

    if intro_music is not None:
        intro_bed = load_audio_track(intro_music, target_sr=sr)
        if len(intro_bed) < intro_samples:
            reps = int(np.ceil(intro_samples / len(intro_bed)))
            intro_bed = np.tile(intro_bed, reps)
    else:
        intro_bed = generate_jingle(
            duration=max(t_intro_total, 6.0),
            sr=sr,
            is_outro=False,
            palette=jingle_palette,
        )

    intro_env = build_intro_envelope(
        total_samples=intro_samples,
        sr=sr,
        duck_gain=duck_gain,
        intro_duck_s=intro_duck_s,
        speech_dur=speech_dur,
    )

    intro_apply_len = min(len(mixed), len(intro_env), len(intro_bed))
    mixed[:intro_apply_len] += intro_bed[:intro_apply_len] * intro_env[:intro_apply_len]

    # --- 2. Outro Music Bed ---
    overlap_samples = min(int(outro_overlap_s * sr), n_speech)
    outro_start_idx = max(0, n_speech - overlap_samples)
    outro_dur_samples = total_samples - outro_start_idx
    t_outro_total = outro_dur_samples / sr

    if outro_music is not None:
        outro_bed = load_audio_track(outro_music, target_sr=sr)
        if len(outro_bed) < outro_dur_samples:
            reps = int(np.ceil(outro_dur_samples / len(outro_bed)))
            outro_bed = np.tile(outro_bed, reps)
    else:
        outro_bed = generate_jingle(
            duration=max(t_outro_total, 6.0),
            sr=sr,
            is_outro=True,
            palette=jingle_palette,
        )

    outro_env = build_outro_envelope(
        outro_dur_samples=outro_dur_samples,
        overlap_samples=overlap_samples,
        sr=sr,
        duck_gain=duck_gain,
    )

    outro_apply_len = min(len(mixed) - outro_start_idx, len(outro_env), len(outro_bed))
    mixed[outro_start_idx:outro_start_idx + outro_apply_len] += (
        outro_bed[:outro_apply_len] * outro_env[:outro_apply_len]
    )

    # Soft limiter / digital peak ceiling to prevent clipping
    peak = float(np.max(np.abs(mixed)))
    if peak > 0.98:
        mixed = mixed * (0.95 / peak)

    return mixed.astype(np.float32)


def apply_music_beds_to_file(
    wav_path: Path,
    out_path: Path | None = None,
    intro_path: Path | str | None = None,
    outro_path: Path | str | None = None,
    duck_db: float = DEFAULT_DUCK_DB,
    intro_duck_s: float = DEFAULT_INTRO_DUCK_S,
    outro_overlap_s: float = DEFAULT_OUTRO_OVERLAP_S,
    outro_tail_s: float = DEFAULT_OUTRO_TAIL_S,
    turn_durations: list[float] | None = None,
    jingle_palette: str = "jazz_calm",
) -> Path:
    """Apply music beds to an existing WAV audio file on disk."""
    wav_path = Path(wav_path)
    if not wav_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {wav_path}")

    speech, sr = sf.read(str(wav_path), dtype="float32")
    mixed = mix_music_beds(
        speech=speech,
        sr=sr,
        intro_music=intro_path,
        outro_music=outro_path,
        duck_db=duck_db,
        intro_duck_s=intro_duck_s,
        outro_overlap_s=outro_overlap_s,
        outro_tail_s=outro_tail_s,
        turn_durations=turn_durations,
        jingle_palette=jingle_palette,
    )

    target_out = Path(out_path) if out_path else wav_path
    target_out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(target_out), mixed, sr)
    return target_out
