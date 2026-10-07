import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

VOXTRAL_ENDPOINT = "https://api.mistral.ai/v1/audio/speech"
DEFAULT_VOICE = "gb_oliver_neutral"

VOICE_MAPPING = {
    "oliver": "gb_oliver_neutral",
    "emma": "gb_jane_sarcasm",
    "jane": "gb_jane_sarcasm",
    "paul": "en_paul_confident",
    "leopold": "de_leopold_neutral",
    "hannah": "de_hannah_neutral",
}


def _secrets_dir() -> Path:
    """VOZONDA_SECRETS_DIR from config.py.

    The pipeline runs this file as a plain script, so a relative import fails;
    config.py is stdlib-only, so put the package root on the path instead.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from vozonda_api.config import VOZONDA_SECRETS_DIR

    return VOZONDA_SECRETS_DIR


def get_api_key() -> str:
    key = os.environ.get("MISTRAL_API_KEY") or os.environ.get("VOXTRAL_API_KEY")
    if key:
        return key.strip()
    key_file = _secrets_dir() / "mistral_api.key"
    if key_file.exists():
        return key_file.read_text().strip()
    return ""


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
    cache_dir = out.parent / f".{out.stem}_voxtral_turns"
    cache_dir.mkdir(parents=True, exist_ok=True)

    api_key = get_api_key()
    if not api_key:
        print(f"Missing Mistral/Voxtral API key ({_secrets_dir() / 'mistral_api.key'})", file=sys.stderr)
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    pieces = []
    turn_durations = []
    sr_ref = None
    t0 = time.time()
    done = 0

    with httpx.Client(timeout=60.0) as client:
        for i, seg in enumerate(segments):
            spk = seg.get("speaker", "A")
            text = seg.get("text", "").strip()
            cache = cache_dir / f"{i:04d}_{spk}.wav"
            if not text:
                turn_durations.append(0.0)
                continue

            if cache.exists() and cache.stat().st_size > 44:
                wav, sr = sf.read(cache, dtype="float32")
                if wav.ndim > 1:
                    wav = wav.mean(axis=1)
            else:
                vc = voices.get(spk, {})
                timbre = vc if isinstance(vc, str) else (vc.get("timbre") or DEFAULT_VOICE)
                voice_slug = VOICE_MAPPING.get(timbre.lower(), timbre)

                payload = {
                    "model": "voxtral-mini-tts-latest",
                    "input": text,
                    "voice": voice_slug,
                }

                try:
                    resp = client.post(VOXTRAL_ENDPOINT, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    audio_b64 = data.get("audio_data") or ""
                    if not audio_b64:
                        raise ValueError("No audio_data in Voxtral response")
                    raw_bytes = base64.b64decode(audio_b64)
                    mp3_cache = cache.with_suffix(".mp3")
                    mp3_cache.write_bytes(raw_bytes)
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", str(mp3_cache), "-ar", "24000", "-ac", "1", str(cache)],
                        capture_output=True,
                        check=True,
                    )
                    wav, sr = sf.read(cache, dtype="float32")
                    if wav.ndim > 1:
                        wav = wav.mean(axis=1)
                except Exception as e:
                    print(f"Voxtral TTS generation error on turn {i} ({voice_slug}): {e}", file=sys.stderr)
                    raise

            if sr_ref is None:
                sr_ref = sr
            pieces.append(wav)
            seg_gap = int(seg.get("gap_ms", gap_ms))
            gap_samples = int(sr * seg_gap / 1000)
            pieces.append(np.zeros(gap_samples, dtype=np.float32))
            turn_durations.append(round((len(wav) + gap_samples) / sr, 3))
            done += 1
            print(f"  turn {i + 1}/{len(segments)} ok ({time.time() - t0:.1f}s)", flush=True)

    if not pieces or sr_ref is None:
        print("no audio produced", file=sys.stderr)
        sys.exit(1)

    full = np.concatenate(pieces)
    sf.write(out, full, sr_ref)
    dur = round(len(full) / sr_ref, 2)
    print(f"voxtral: {done} turns, {dur}s total, written to {out}")

    meta_path = out.with_suffix(".json")
    meta_path.write_text(json.dumps({
        "turns": turn_durations,
        "sample_rate": sr_ref,
        "duration_s": dur,
        "engine": "voxtral",
    }))
    timing_file = out.parent / f"{out.stem}.timing.json"
    timing_file.write_text(json.dumps(turn_durations))


if __name__ == "__main__":
    main()
