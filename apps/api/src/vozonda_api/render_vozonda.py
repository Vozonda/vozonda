import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vozonda_api.env import env

os.environ.setdefault(
    "HF_HOME",
    env("HF_HOME") or str(Path.home() / ".cache" / "vozonda" / "hf"),
)

import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
DEFAULT_INSTRUCT = "Speak naturally and clearly."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    segments = cfg["segments"]
    voices = cfg.get("voices", {})
    gap_ms = int(cfg.get("gap_ms", 380))
    out = Path(cfg["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    cache_dir = out.parent / f".{out.stem}_turns"
    cache_dir.mkdir(parents=True, exist_ok=True)

    pieces = []
    turn_durations = []
    sr_ref = None
    t0 = time.time()
    done = 0

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = Qwen3TTSModel.from_pretrained(
        MODEL, device_map=device, dtype=torch.bfloat16
    )

    for i, seg in enumerate(segments):
        spk = seg.get("speaker", "A")
        text = seg.get("text", "").strip()
        text = re.sub(r'\[[a-zA-Z0-9\s_,-]+\]', '', text).strip()
        text = re.sub(r'\([a-zA-Z0-9\s_,-]+\)', '', text).strip()
        cache = cache_dir / f"{i:04d}_{spk}.wav"
        if not text:
            turn_durations.append(0.0)
            continue
        if cache.exists() and cache.stat().st_size > 44:
            wavs, sr = sf.read(cache, dtype="float32"), None
            wav = np.asarray(wavs, dtype=np.float32)
            sr = sr or 24000
            if wav.ndim > 1:
                wav = wav.mean(axis=1)
        else:
            vc = voices.get(spk, {})
            if isinstance(vc, str):
                timbre = vc
                instruct = DEFAULT_INSTRUCT
            else:
                timbre = vc.get("timbre", "aiden")
                instruct = vc.get("instruct") or DEFAULT_INSTRUCT
            with torch.no_grad():
                wavs, sr = model.generate_custom_voice(
                    text=text, speaker=timbre, language=cfg.get("language", "English"), instruct=instruct
                )
            wav = np.asarray(wavs[0] if isinstance(wavs, list) else wavs, dtype=np.float32)
            if wav.ndim > 1:
                wav = wav.mean(axis=1)
            sf.write(cache, wav, sr)
        if sr_ref is None:
            sr_ref = sr
        pieces.append(wav)
        seg_gap = int(seg.get("gap_ms", gap_ms))
        gap_samples = int(sr * seg_gap / 1000)
        pieces.append(np.zeros(gap_samples, dtype=np.float32))
        turn_durations.append(round((len(wav) + gap_samples) / sr, 3))
        done += 1
        print(f"  turn {i + 1}/{len(segments)} ok ({time.time() - t0:.0f}s)", flush=True)

    if not pieces or sr_ref is None:
        print("no audio produced", file=sys.stderr)
        sys.exit(1)

    episode = np.concatenate(pieces)
    if cfg.get("music") or cfg.get("music_bed"):
        episode = apply_music_beds(episode, sr_ref, cfg, turn_durations=turn_durations)
    sf.write(out, episode, sr_ref)
    timing_file = out.parent / f"{out.stem}.timing.json"
    timing_file.write_text(json.dumps(turn_durations))
    print(f"done: {done} turns -> {out}", flush=True)


def apply_music_beds(
    audio: np.ndarray,
    sr: int,
    cfg: dict,
    turn_durations: list[float] | None = None,
) -> np.ndarray:
    """Mix intro and outro musical jingle beds with ducking under speech (#113)."""
    music_mode = cfg.get("music") or cfg.get("music_bed")
    if not music_mode or music_mode in ("none", "false", False):
        return audio

    try:
        try:
            from vozonda_api.music import mix_music_beds
        except ImportError:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from vozonda_api.music import mix_music_beds

        intro_path = cfg.get("intro_music")
        outro_path = cfg.get("outro_music")
        duck_db = float(cfg.get("duck_db", -12.0))

        return mix_music_beds(
            speech=audio,
            sr=sr,
            intro_music=intro_path,
            outro_music=outro_path,
            duck_db=duck_db,
            turn_durations=turn_durations,
        )
    except Exception as exc:
        print(f"warning: music bed mixing failed ({exc}), keeping plain audio", file=sys.stderr)
        return audio


if __name__ == "__main__":
    main()
