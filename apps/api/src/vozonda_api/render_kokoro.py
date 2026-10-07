"""Kokoro-82M renderer: same CLI contract as render_piper.py.

--config cfg.json with {segments, voices, gap_ms, language, out}; writes the
final WAV to cfg["out"] plus a .timing.json sidecar with per-turn durations.

The pipeline runs this file as a plain script under the engine venv, where
httpx does not exist: stdlib only at module level, kokoro_onnx / numpy /
soundfile are imported inside main(). Model files (kokoro-v1.0.onnx and
voices-v1.0.bin) download on first use into VOZONDA_KOKORO_DIR and are never
baked into the image.
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    """vozonda_api.env without a top-level import: plain-file runs lack the path."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from vozonda_api.env import env as _read_env

    return _read_env(name, default)

DEFAULT_VOICE = "af_bella"

# job language -> Kokoro lang code (everything outside this map renders
# with Piper when kokoro is the engine, see providers.resolve_voice_engine)
KOKORO_LANG_MAP = {
    "en": "en-us",
    "es": "es",
    "fr": "fr-fr",
    "it": "it",
    "pt": "pt-br",
    "hi": "hi",
    "ja": "ja",
    "zh": "zh",
}

# default voice per job language, all present in voices-v1.0.bin
KOKORO_DEFAULT_VOICES = {
    "en": "af_bella",
    "es": "ef_dora",
    "fr": "ff_siwis",
    "it": "if_sara",
    "pt": "pf_dora",
    "hi": "hf_alpha",
    "ja": "jf_alpha",
    "zh": "zf_xiaobei",
}

# pipeline passes display names ("English"); accept those too
_LANGUAGE_NAMES = {
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "italian": "it",
    "portuguese": "pt",
    "hindi": "hi",
    "japanese": "ja",
    "chinese": "zh",
}

MODEL_FILE = "kokoro-v1.0.onnx"
VOICES_FILE = "voices-v1.0.bin"
MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
)
VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
)


def kokoro_dir() -> Path:
    """Where model files live (a docker volume in the quickstart)."""
    return Path(_env("KOKORO_DIR") or Path.home() / ".local/share/kokoro")


def model_paths(directory: Path | None = None) -> tuple[Path, Path]:
    """Expected (model, voices) paths for a kokoro dir."""
    d = Path(directory) if directory is not None else kokoro_dir()
    return d / MODEL_FILE, d / VOICES_FILE


def normalize_lang(language: str) -> str:
    """Job language code or display name -> base code (en, es, ...)."""
    key = (language or "").strip().lower()
    if key in KOKORO_LANG_MAP:
        return key
    mapped = _LANGUAGE_NAMES.get(key)
    if mapped:
        return mapped
    # "en-us" or "pt-br" style codes collapse back to the job code
    for code, kok_code in KOKORO_LANG_MAP.items():
        if key == kok_code or key.startswith(code):
            return code
    return key


def kokoro_lang_for(language: str) -> str:
    """Job language -> Kokoro lang code; unknown falls back to en-us."""
    return KOKORO_LANG_MAP.get(normalize_lang(language), "en-us")


def default_voice_for(language: str) -> str:
    """Default voice id for a job language; unknown -> DEFAULT_VOICE."""
    return KOKORO_DEFAULT_VOICES.get(normalize_lang(language), DEFAULT_VOICE)


def _download(url: str, dest: Path) -> None:
    print(f"  downloading kokoro model {dest.name} ...", flush=True)
    # write to .part and rename when complete: a killed process (container stop, OOM)
    # must not leave a truncated file that the next start takes for the model
    part = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, open(part, "wb") as fh:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
        part.replace(dest)
    except Exception as exc:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(
            f"could not download {dest.name} from {url} (offline?): {exc}. "
            f"Set VOZONDA_KOKORO_DIR or place {MODEL_FILE} and {VOICES_FILE} in {kokoro_dir()}."
        ) from exc


def ensure_models(directory: Path | None = None) -> tuple[Path, Path]:
    """Model and voices paths, downloading them on first use."""
    d = Path(directory) if directory is not None else kokoro_dir()
    d.mkdir(parents=True, exist_ok=True)
    model, voices = model_paths(d)
    if not model.exists():
        _download(MODEL_URL, model)
    if not voices.exists():
        _download(VOICES_URL, voices)
    if not model.exists() or not voices.exists():
        raise RuntimeError(
            f"Kokoro model or voices missing in {d} (offline?): "
            f"download {MODEL_FILE} and {VOICES_FILE} from the kokoro-onnx release "
            "and place them there."
        )
    return model, voices


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    import numpy as np
    import soundfile as sf

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from kokoro_onnx import Kokoro

    cfg = json.loads(Path(args.config).read_text())
    segments = cfg["segments"]
    voices = cfg.get("voices", {})
    gap_ms = int(cfg.get("gap_ms", 380))
    out = Path(cfg["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    cache_dir = out.parent / f".{out.stem}_kokoro_turns"
    cache_dir.mkdir(parents=True, exist_ok=True)

    job_lang = normalize_lang(str(cfg.get("language", "en")))
    kokoro_lang = kokoro_lang_for(job_lang)

    model_path, voices_path = ensure_models()
    kok = Kokoro(str(model_path), str(voices_path))

    pieces = []
    turn_durations = []
    sr_ref = None
    t0 = time.time()
    done = 0

    for i, seg in enumerate(segments):
        spk = seg.get("speaker", "A")
        text = seg.get("text", "").strip()
        text = re.sub(r"\[[a-zA-Z0-9\s_,-]+\]", "", text).strip()
        text = re.sub(r"\([a-zA-Z0-9\s_,-]+\)", "", text).strip()
        vc = voices.get(spk, {})
        if isinstance(vc, str):
            timbre = vc
            speed = 1.0
        else:
            timbre = vc.get("timbre") or default_voice_for(job_lang)
            speed = float(vc.get("speed", 1.0))
        text_hash = hashlib.sha256(f"{text}_{timbre}_{speed}".encode()).hexdigest()[:10]
        cache = cache_dir / f"{i:04d}_{spk}_{text_hash}.wav"
        if not text:
            turn_durations.append(0.0)
            continue

        if cache.exists() and cache.stat().st_size > 44:
            wav, sr = sf.read(cache, dtype="float32")
            if wav.ndim > 1:
                wav = wav.mean(axis=1)
        else:
            try:
                samples, sr = kok.create(text, voice=timbre, speed=speed, lang=kokoro_lang)
                sf.write(cache, samples, sr)
                wav = samples.astype(np.float32)
            except Exception as e:
                print(f"Kokoro synthesis error on turn {i} ({timbre}): {e}", file=sys.stderr)
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
    print(f"kokoro: {done} turns, {dur}s total, written to {out}")

    meta_path = out.with_suffix(".json")
    meta_path.write_text(json.dumps({
        "turns": turn_durations,
        "sample_rate": sr_ref,
        "duration_s": dur,
        "engine": "kokoro",
    }))
    timing_file = out.parent / f"{out.stem}.timing.json"
    timing_file.write_text(json.dumps(turn_durations))


if __name__ == "__main__":
    main()
