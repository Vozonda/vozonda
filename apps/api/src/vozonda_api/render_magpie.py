"""Magpie TTS Multilingual renderer (NVIDIA NIM, hosted): same CLI contract as render_voxtral.py.

One gRPC call per chunk of a turn to grpc.nvcf.nvidia.com. Long turns are
split at sentence ends; rate limits (the trial key allows about 40 requests
a minute) and transient errors are retried with backoff. Each turn is cached
next to the output, so a retried job does not pay for finished turns again.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vozonda_api.providers.magpie import FUNCTION_ID, SERVER, SPEAKERS

SAMPLE_RATE = 44100
MAX_CHARS = 350
DEFAULT_VOICE = "en_aria"
RETRY_CODES = {"RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED"}
BACKOFF_S = (2, 5, 10, 20, 40, 60)

_BY_ID = {s["id"]: s for s in SPEAKERS}
_sleep = time.sleep


def voice_for(voice_id: str) -> tuple[str, str]:
    """(Magpie voice name, language code) for a vozonda voice id."""
    s = _BY_ID.get(str(voice_id).lower()) or _BY_ID[DEFAULT_VOICE]
    return s["magpie"], s["locale"]


def chunks(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Split a turn at sentence ends (then at spaces) into pieces of at most max_chars."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    out: list[str] = []
    cur = ""
    for sent in sentences:
        while len(sent) > max_chars:
            cut = sent.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if cur:
                out.append(cur)
                cur = ""
            out.append(sent[:cut].strip())
            sent = sent[cut:].strip()
        if cur and len(cur) + 1 + len(sent) > max_chars:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return [c for c in out if c]


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    try:
        code = code() if callable(code) else code
    except Exception:
        return ""
    return getattr(code, "name", str(code or ""))


def _synth_retry(synth, text: str, voice: str, lang: str) -> bytes:
    for attempt, wait in enumerate((0,) + BACKOFF_S):
        if wait:
            _sleep(wait)
        try:
            return synth(text, voice, lang)
        except Exception as exc:
            if _error_code(exc) not in RETRY_CODES or attempt == len(BACKOFF_S):
                raise
            print(f"  magpie {_error_code(exc)}, retry in {BACKOFF_S[attempt]}s", flush=True)
    raise RuntimeError("unreachable")


def render(cfg: dict, synth) -> None:
    segments = cfg["segments"]
    voices = cfg.get("voices", {})
    gap_ms = int(cfg.get("gap_ms", 380))
    out = Path(cfg["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    cache_dir = out.parent / f".{out.stem}_magpie_turns"
    cache_dir.mkdir(parents=True, exist_ok=True)

    pieces: list[np.ndarray] = []
    turn_durations: list[float] = []
    t0 = time.time()
    for i, seg in enumerate(segments):
        spk = seg.get("speaker", "A")
        text = str(seg.get("text", "")).strip()
        if not text:
            turn_durations.append(0.0)
            continue
        vc = voices.get(spk, {})
        timbre = vc if isinstance(vc, str) else (vc.get("timbre") or DEFAULT_VOICE)
        voice, lang = voice_for(timbre)
        cache = cache_dir / f"{i:04d}_{hashlib.sha256(f'{voice}|{text}'.encode()).hexdigest()[:10]}.wav"
        if cache.exists() and cache.stat().st_size > 44:
            wav, _sr = sf.read(cache, dtype="float32")
        else:
            pcm = b"".join(_synth_retry(synth, part, voice, lang) for part in chunks(text))
            wav = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            sf.write(cache, wav, SAMPLE_RATE)
        gap = np.zeros(int(SAMPLE_RATE * int(seg.get("gap_ms", gap_ms)) / 1000), dtype=np.float32)
        pieces += [wav, gap]
        turn_durations.append(round((len(wav) + len(gap)) / SAMPLE_RATE, 3))
        print(f"  turn {i + 1}/{len(segments)} ok ({time.time() - t0:.1f}s)", flush=True)

    if not pieces:
        print("no audio produced", file=sys.stderr)
        sys.exit(1)
    full = np.concatenate(pieces)
    sf.write(out, full, SAMPLE_RATE)
    dur = round(len(full) / SAMPLE_RATE, 2)
    print(f"magpie: {sum(1 for d in turn_durations if d)} turns, {dur}s total, written to {out}")
    out.with_suffix(".json").write_text(json.dumps(
        {"turns": turn_durations, "sample_rate": SAMPLE_RATE, "duration_s": dur, "engine": "magpie"}))
    (out.parent / f"{out.stem}.timing.json").write_text(json.dumps(turn_durations))


def make_synth():
    """A synth(text, voice, lang) -> 16-bit PCM bytes over the hosted NIM gRPC API."""
    import riva.client

    from vozonda_api.providers import nim_api_key

    key = nim_api_key()
    if not key:
        print("Missing NVIDIA NIM key (settings llm.nim_api_key, VOZONDA_NIM_API_KEY or "
              "secrets/nvidia_nim_api.key)", file=sys.stderr)
        sys.exit(1)
    auth = riva.client.Auth(uri=SERVER, use_ssl=True, metadata_args=[
        ["function-id", FUNCTION_ID], ["authorization", f"Bearer {key}"]])
    service = riva.client.SpeechSynthesisService(auth)

    def synth(text: str, voice: str, lang: str) -> bytes:
        return service.synthesize(text, voice_name=voice, language_code=lang,
                                  sample_rate_hz=SAMPLE_RATE).audio

    return synth


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    render(json.loads(Path(args.config).read_text()), make_synth())


if __name__ == "__main__":
    main()
