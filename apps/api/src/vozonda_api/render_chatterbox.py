"""Chatterbox renderer: same CLI contract as render_kokoro.py.

--config cfg.json with {segments, voices, gap_ms, language, out}; writes the
final WAV to cfg["out"] plus a .timing.json sidecar with per-turn durations.

Chatterbox synthesizes a single speaker per call and clones from a reference
WAV, so each turn is rendered on its own and joined with the gap logic from
render_kokoro.py. All text/turn preparation lives in pure functions so the
tests can exercise them without torch; the engine is imported only in main().
"""

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    """vozonda_api.env without a top-level import: plain-file runs lack the path."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from vozonda_api.env import env as _read_env

    return _read_env(name, default)

DEFAULT_VOICE = "cb_host_f"

# vozonda language code -> chatterbox mtl language_id
LANGUAGE_IDS = {
    "en": "en",
    "de": "de",
    "es": "es",
    "fr": "fr",
    "it": "it",
    "pt": "pt",
    "ru": "ru",
    "zh": "zh",
    "ja": "ja",
    "ko": "ko",
}

# vozonda display names -> code (pipeline passes e.g. "English")
LANGUAGE_NAMES = {
    "english": "en",
    "german": "de",
    "spanish": "es",
    "french": "fr",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
}

_EMOTION_PARAMS = {
    "neutral": (0.5, 0.5),
    "excited": (0.8, 0.3),
    "energetic": (0.8, 0.3),
    "calm": (0.3, 0.6),
    "dramatic": (0.7, 0.4),
}


def emotion_params(emotion: str) -> tuple[float, float]:
    """Map a vozonda emotion to (exaggeration, cfg_weight); unknown -> neutral."""
    return _EMOTION_PARAMS.get((emotion or "").strip().lower(), _EMOTION_PARAMS["neutral"])


def language_id_for(language: str) -> str:
    """Map a vozonda language code or display name to a chatterbox language_id."""
    key = (language or "").strip().lower()
    if key in LANGUAGE_IDS:
        return LANGUAGE_IDS[key]
    return LANGUAGE_IDS.get(LANGUAGE_NAMES.get(key, "en"), "en")


def clean_text(text: str) -> str:
    """Strip bracketed/parenthesized tags the engine would read aloud."""
    text = re.sub(r"\[[a-zA-Z0-9\s_,-]+\]", "", text)
    text = re.sub(r"\([a-zA-Z0-9\s_,-]+\)", "", text)
    return text.strip()


def resolve_reference(sample: str, voices_dir: Path) -> Path:
    """Resolve a reference sample strictly inside the voices dir.

    Anything escaping the configured dir (absolute paths, .., symlinks)
    is a ValueError: the engine clones from this file, so it must be one
    of the curated references.
    """
    root = Path(voices_dir).resolve()
    candidate = (root / sample).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"reference sample escapes voices dir: {sample}")
    return candidate


def voice_config(voices: dict, speaker: str) -> dict:
    """Normalize a voices-map entry to {timbre, speed, emotion}."""
    vc = voices.get(speaker, {})
    if isinstance(vc, str):
        return {"timbre": vc or DEFAULT_VOICE, "speed": 1.0, "emotion": "neutral"}
    return {
        "timbre": vc.get("timbre") or DEFAULT_VOICE,
        "speed": float(vc.get("speed", 1.0)),
        "emotion": str(vc.get("emotion") or "neutral"),
    }


def _engine_available() -> bool:
    return importlib.util.find_spec("chatterbox") is not None


# Runs under the engine venv, which has no httpx, so the renderer must not
# import the provider. config.py is stdlib-only: put the package root on the
# path and derive the same defaults the provider uses (tests keep them in sync).
def _root() -> Path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from vozonda_api.config import VOZONDA_ROOT

    return Path(VOZONDA_ROOT)


def render_py_default() -> str:
    return str(_root() / "projects/tts-spike/.venv-chatterbox/bin/python")


def voices_dir_default() -> str:
    return str(_root() / "projects/tts-spike/voices/chatterbox")


def sample_for(voice_id: str) -> str:
    """Speaker id -> reference file name: 'cb_host_f' -> 'host_f.wav'."""
    return f"{voice_id.removeprefix('cb_')}.wav"


def _reexec_under_render_py() -> None:
    """Re-exec this script under the chatterbox venv interpreter."""
    render_py = _env("CHATTERBOX_PY") or render_py_default()
    if Path(render_py).exists() and Path(render_py).resolve() != Path(sys.executable).resolve():
        os.execv(render_py, [render_py, str(Path(__file__).resolve()), *sys.argv[1:]])


def main() -> None:
    if not _engine_available():
        _reexec_under_render_py()
    if not _engine_available():
        print("chatterbox package not importable and no VOZONDA_CHATTERBOX_PY venv found", file=sys.stderr)
        sys.exit(1)

    import numpy as np
    import soundfile as sf

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    segments = cfg["segments"]
    voices = cfg.get("voices", {})
    gap_ms = int(cfg.get("gap_ms", 380))
    language = cfg.get("language", "English")
    out = Path(cfg["out"])
    out.parent.mkdir(parents=True, exist_ok=True)

    voices_dir = Path(_env("CHATTERBOX_VOICES") or voices_dir_default())
    lang_id = language_id_for(language)

    if lang_id == "en":
        from chatterbox.tts import ChatterboxTTS

        model = ChatterboxTTS.from_pretrained(device="cuda")

        def synth(text: str, ref: Path, exag: float, cfg_w: float):
            return model.generate(
                text,
                audio_prompt_path=str(ref),
                exaggeration=exag,
                cfg_weight=cfg_w,
            )
    else:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")

        def synth(text: str, ref: Path, exag: float, cfg_w: float):
            return model.generate(
                text,
                language_id=lang_id,
                audio_prompt_path=str(ref),
                exaggeration=exag,
                cfg_weight=cfg_w,
            )

    pieces = []
    turn_durations: list[float] = []
    sr_ref = None

    for i, seg in enumerate(segments):
        spk = seg.get("speaker", "A")
        text = clean_text(seg.get("text", ""))
        if not text:
            turn_durations.append(0.0)
            continue
        vc = voice_config(voices, spk)
        ref = resolve_reference(sample_for(vc["timbre"]), voices_dir)
        if not ref.exists():
            print(f"chatterbox: reference sample missing: {ref}", file=sys.stderr)
            sys.exit(1)
        exag, cfg_w = emotion_params(vc["emotion"])

        wav = synth(text, ref, exag, cfg_w)
        wav = np.asarray(wav, dtype=np.float32).reshape(-1)
        sr = int(getattr(model, "sr", 24000))

        if sr_ref is None:
            sr_ref = sr
        pieces.append(wav)
        seg_gap = int(seg.get("gap_ms", gap_ms))
        gap_samples = int(sr * seg_gap / 1000)
        pieces.append(np.zeros(gap_samples, dtype=np.float32))
        turn_durations.append(round((len(wav) + gap_samples) / sr, 3))
        print(f"  turn {i + 1}/{len(segments)} ok", flush=True)

    if not pieces or sr_ref is None:
        print("no audio produced", file=sys.stderr)
        sys.exit(1)

    full = np.concatenate(pieces)
    sf.write(out, full, sr_ref)
    dur = round(len(full) / sr_ref, 2)
    print(f"chatterbox: {len(turn_durations)} turns, {dur}s total, written to {out}")

    timing_file = out.parent / f"{out.stem}.timing.json"
    timing_file.write_text(json.dumps(turn_durations))


if __name__ == "__main__":
    main()
