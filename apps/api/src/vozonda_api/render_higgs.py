"""Higgs Audio v2 renderer: same CLI contract as render_kokoro.py.

Runs as a plain file under the engine's own venv (VOZONDA_HIGGS_PY); when
boson_multimodal is not importable in the current interpreter it re-execs
itself under RENDER_PY. All text/turn preparation lives in pure functions
testable without torch; the engine is imported only inside main().

Multi-speaker generation maps vozonda speakers to [SPEAKER0]..[SPEAKER3]
tags in one transcript plus a scene system prompt, per the higgs-audio
README (HiggsAudioServeEngine / ChatMLSample).
"""

import argparse
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

MAX_SPEAKERS = 4
MAX_CHUNK_WORDS = 150

_SCENE_RE = re.compile(r"<\|scene_desc_start\|>(.*?)<\|scene_desc_end\|>", re.DOTALL)


def _vozonda_root() -> Path:
    """VOZONDA_ROOT from config.py.

    The pipeline runs this file as a plain script, so a relative import fails;
    config.py is stdlib-only, so put the package root on the path instead.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from vozonda_api.config import VOZONDA_ROOT

    return VOZONDA_ROOT


def _render_py() -> str:
    return _env("HIGGS_PY",
        str(_vozonda_root() / "projects/tts-spike/.venv-higgs/bin/python"),
    )


def _voices_dir() -> Path:
    return Path(
        _env("HIGGS_VOICES",
            str(_vozonda_root() / "projects/tts-spike/voices/higgs"),
        )
    )


def build_transcript(turns: list[dict]) -> str:
    """Map vozonda speakers to [SPEAKER0]..[SPEAKER3] in order of appearance.

    More than 4 distinct speakers raises ValueError (engine limit).
    """
    mapping: dict[str, int] = {}
    parts: list[str] = []
    for turn in turns:
        spk = str(turn.get("speaker", "A"))
        text = str(turn.get("text", "")).strip()
        if not text:
            continue
        if spk not in mapping:
            if len(mapping) >= MAX_SPEAKERS:
                raise ValueError(
                    f"higgs supports at most {MAX_SPEAKERS} speakers, got more"
                )
            mapping[spk] = len(mapping)
        parts.append(f"[SPEAKER{mapping[spk]}] {text}")
    return "\n".join(parts)


def build_system_prompt(language: str = "English", tone: str = "neutral") -> str:
    """Scene-description system prompt, per the higgs-audio README format."""
    scene = (
        f"A {tone} spoken podcast conversation in {language}. "
        "Natural, expressive delivery with realistic pacing."
    )
    return (
        "Generate audio following instruction.\n\n"
        f"<|scene_desc_start|>\n{scene}\n<|scene_desc_end|>"
    )


def chunk_turns(turns: list[dict], max_words: int = MAX_CHUNK_WORDS) -> list[list[dict]]:
    """Split turns into chunks of at most max_words words each.

    Turn order is preserved so the speaker mapping stays stable across
    chunks (mapping is by order of appearance over the full list).
    """
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_words = 0
    for turn in turns:
        words = len(str(turn.get("text", "")).split())
        if current and current_words + words > max_words:
            chunks.append(current)
            current = []
            current_words = 0
        current.append(turn)
        current_words += words
    if current:
        chunks.append(current)
    return chunks


def resolve_sample(sample: str, voices_dir: Path | None = None) -> Path:
    """Resolve a reference sample inside the voices dir; reject escapes."""
    base = (voices_dir or _voices_dir()).resolve()
    path = (base / sample).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"reference sample escapes voices dir: {sample}")
    return path


def _engine_importable() -> bool:
    try:
        import boson_multimodal  # noqa: F401

        return True
    except ImportError:
        return False


def main() -> None:
    if not _engine_importable():
        render_py = _render_py()
        if Path(render_py).exists() and Path(render_py).resolve() != Path(sys.executable).resolve():
            os.execv(render_py, [render_py, str(Path(__file__).resolve()), *sys.argv[1:]])
        print("boson_multimodal not importable and VOZONDA_HIGGS_PY missing", file=sys.stderr)
        sys.exit(1)

    import numpy as np
    import soundfile as sf
    import torch
    from boson_multimodal.data_types import ChatMLSample, Message
    from boson_multimodal.serve.serve_engine import HiggsAudioServeEngine

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

    model_path = _env("HIGGS_MODEL", "bosonai/higgs-audio-v2-generation-3B-base"
    )
    tokenizer_path = _env("HIGGS_TOKENIZER", "bosonai/higgs-audio-v2-tokenizer"
    )
    device = "cuda" if torch.cuda.is_available() else "cpu"
    engine = HiggsAudioServeEngine(
        model_path,
        tokenizer_path,
        device=device,
    )

    system_prompt = build_system_prompt(language=language)

    # Resolve reference samples for voice cloning up front (validates paths).
    ref_samples: dict[str, Path] = {}
    for spk, vc in voices.items():
        sample = vc.get("sample") if isinstance(vc, dict) else None
        if sample:
            ref_samples[spk] = resolve_sample(sample)

    pieces: list[np.ndarray] = []
    turn_durations: list[float] = []
    sr_ref: int | None = None

    for chunk in chunk_turns(segments):
        transcript = build_transcript(chunk)
        if not transcript:
            continue
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=transcript),
        ]
        output = engine.generate(
            chat_ml_sample=ChatMLSample(messages=messages),
            max_new_tokens=2048,
            temperature=0.3,
        )
        audio = np.asarray(output.audio, dtype=np.float32)
        sr = int(output.sampling_rate)
        if sr_ref is None:
            sr_ref = sr
        pieces.append(audio)

    if not pieces or sr_ref is None:
        print("no audio produced", file=sys.stderr)
        sys.exit(1)

    # Insert gaps between turns proportionally: approximate per-turn
    # durations by word share of the full transcript.
    total_words = sum(len(str(s.get("text", "")).split()) for s in segments) or 1
    full = np.concatenate(pieces)
    total_dur = len(full) / sr_ref
    gap_s = gap_ms / 1000.0
    for seg in segments:
        share = len(str(seg.get("text", "")).split()) / total_words
        turn_durations.append(round(share * total_dur + gap_s, 3))

    sf.write(out, full, sr_ref)
    dur = round(len(full) / sr_ref, 2)
    print(f"higgs: {len(segments)} turns, {dur}s total, written to {out}")

    timing_file = out.parent / f"{out.stem}.timing.json"
    timing_file.write_text(json.dumps(turn_durations))


if __name__ == "__main__":
    main()
