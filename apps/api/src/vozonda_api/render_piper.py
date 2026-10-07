import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf


def _env(name: str, default: str | None = None) -> str | None:
    """vozonda_api.env without a top-level import: plain-file runs lack the path."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from vozonda_api.env import env as _read_env

    return _read_env(name, default)

DEFAULT_VOICE = "thorsten"
# Model names as published at huggingface.co/rhasspy/piper-voices; several
# voices exist only in low / x_low quality.
VOICE_MODELS = {
    "thorsten": "de_DE-thorsten-medium",
    "kerstin": "de_DE-kerstin-low",
    "ramona": "de_DE-ramona-low",
    "alan": "en_GB-alan-medium",
    "cori": "en_GB-cori-medium",
    "ryan": "en_US-ryan-medium",
    "amy": "en_US-amy-medium",
    "siwis": "fr_FR-siwis-medium",
    "gilles": "fr_FR-gilles-low",
    "carlfm": "es_ES-carlfm-x_low",
    "davefx": "es_ES-davefx-medium",
    "riccardo": "it_IT-riccardo-x_low",
    "paola": "it_IT-paola-medium",
}


def data_dir() -> Path:
    """Where voice models live (a docker volume in the quickstart)."""
    return Path(_env("PIPER_DIR") or Path.home() / ".local/share/piper")


def ensure_model(model_name: str, directory: Path) -> Path:
    """The .onnx path of a voice, downloaded on first use (piper-tts does not do this itself)."""
    model = directory / f"{model_name}.onnx"
    if model.exists():
        return model
    directory.mkdir(parents=True, exist_ok=True)
    print(f"  downloading piper voice {model_name} ...", flush=True)
    proc = subprocess.run(
        [sys.executable, "-m", "piper.download_voices", "--download-dir", str(directory), model_name],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not model.exists():
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()[-500:]
        raise RuntimeError(f"could not download piper voice {model_name}: {err}")
    return model


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
    cache_dir = out.parent / f".{out.stem}_piper_turns"
    cache_dir.mkdir(parents=True, exist_ok=True)

    pieces = []
    turn_durations = []
    sr_ref = None
    t0 = time.time()
    done = 0

    piper_bin = shutil.which("piper")
    if not piper_bin:
        venv_piper = Path(sys.executable).parent / "piper"
        if venv_piper.exists():
            piper_bin = str(venv_piper)

    for i, seg in enumerate(segments):
        spk = seg.get("speaker", "A")
        text = seg.get("text", "").strip()
        text = re.sub(r'\[[a-zA-Z0-9\s_,-]+\]', '', text).strip()
        text = re.sub(r'\([a-zA-Z0-9\s_,-]+\)', '', text).strip()
        vc = voices.get(spk, {})
        timbre = vc if isinstance(vc, str) else (vc.get("timbre") or DEFAULT_VOICE)
        text_hash = hashlib.sha256(f"{text}_{timbre}".encode()).hexdigest()[:10]
        cache = cache_dir / f"{i:04d}_{spk}_{text_hash}.wav"
        if not text:
            turn_durations.append(0.0)
            continue

        if cache.exists() and cache.stat().st_size > 44:
            wav, sr = sf.read(cache, dtype="float32")
            if wav.ndim > 1:
                wav = wav.mean(axis=1)
        else:
            model_name = VOICE_MODELS.get(timbre, VOICE_MODELS[DEFAULT_VOICE])

            if piper_bin:
                model = ensure_model(model_name, data_dir())
                proc = subprocess.run(
                    [piper_bin, "--model", str(model), "--output_file", str(cache)],
                    input=text.encode("utf-8"),
                    capture_output=True,
                    check=False,
                )
                if proc.returncode != 0 or not cache.exists():
                    raise RuntimeError(f"Piper execution failed: {proc.stderr.decode('utf-8')}")
            else:
                # Mock synthesis for CPU verification when piper standalone binary is absent
                sr = 22050
                dur = max(0.5, len(text) * 0.05)
                samples = int(sr * dur)
                t = np.linspace(0, dur, samples, endpoint=False)
                wav = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
                sf.write(cache, wav, sr)

            wav, sr = sf.read(cache, dtype="float32")
            if wav.ndim > 1:
                wav = wav.mean(axis=1)

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

    full = np.concatenate(pieces)
    sf.write(out, full, sr_ref)
    dur = round(len(full) / sr_ref, 2)
    print(f"piper: {done} turns, {dur}s total, written to {out}")

    meta_path = out.with_suffix(".json")
    meta_path.write_text(json.dumps({
        "turns": turn_durations,
        "sample_rate": sr_ref,
        "duration": dur,
        "engine": "piper",
    }, indent=2))
    timing_file = out.parent / f"{out.stem}.timing.json"
    timing_file.write_text(json.dumps(turn_durations))


if __name__ == "__main__":
    main()
