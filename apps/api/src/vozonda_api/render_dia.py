"""Dia (Nari Labs 1.6B) renderer script for vozonda.

Reads a config JSON (segments, voices, gap_ms, language, out), prepares
dialogue text using [S1]/[S2] tags, and writes episode audio via the
Hugging Face transformers Dia model.

CLI contract matches render_kokoro.py:
    render_dia.py --config cfg.json
"""

from __future__ import annotations

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

SUPPORTED_NONVERBALS = frozenset([
    "laughs", "clears throat", "sighs", "gasps", "coughs",
    "singing", "sings", "mumbles", "beep", "groans", "sniffs",
    "claps", "screams", "inhales", "exhales", "applause",
    "burps", "humming", "sneezes", "chuckle", "whistles",
])

_MODEL = "nari-labs/Dia-1.6B-0626"


def to_dia_text(turn: str) -> str:
    """Keep only README-supported nonverbal tags, strip other text.

    Removes text inside square brackets ``[...]`` and parentheses ``(...)``
    unless the content matches one of the supported nonverbal markers.

    Args:
        turn: Raw turn text possibly containing tags and bracketed
            expressions.

    Returns:
        Cleaned text with only supported nonverbal tags.
    """
    # Remove all [bracketed] content
    text = re.sub(r"\[[^\]]*\]", "", turn)
    kept: list[str] = []
    for part in text.split(" "):
        # Check if the token is a supported (tag)
        if re.fullmatch(r"\(([a-zA-Z0-9_ ]+)\)", part):
            inner = part.strip("()")
            if inner in SUPPORTED_NONVERBALS:
                kept.append(f"({inner})")
        elif "[" not in part and part.strip("()"):
            kept.append(part)
    return " ".join(kept)


def _chunk_text(text: str, max_words: int = 120) -> list[str]:
    """Split text into chunks respecting sentence boundaries.

    Splits on sentence-ending punctuation (. ! ?) to keep sentences
    together.  Falls back to word-based splitting when no sentence
    boundaries exist.

    Args:
        text: Input text (already tagged with [S1]/[S2]).
        max_words: Maximum words per chunk.

    Returns:
        List of text chunks, each with at most max_words words.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s for s in sentences if s.strip()]

    if not sentences:
        return []

    chunks: list[str] = []
    current_words = 0
    current_chunk: list[str] = []

    for sent in sentences:
        word_count = len(sent.split())
        if current_words + word_count > max_words and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sent]
            current_words = word_count
        else:
            current_chunk.append(sent)
            current_words += word_count

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def chunk_dialogue(turns: list[dict], max_words: int = 120) -> list[str]:
    """Build dia-formatted chunks from a list of turns.

    Maps first speaker to [S1], second to [S2].  Third+ speaker
    triggers ValueError.  Never splits a turn.  Each chunk always
    starts with the speaker of its first turn.

    Args:
        turns: List of ``{"speaker": "A", "text": "..."}`` dicts.
        max_words: Maximum words per chunk (controls ~20-30 s audio).

    Returns:
        List of dia-formatted text chunks for generate().

    Raises:
        ValueError: If more than 2 unique speakers are present.
    """
    speakers: list[str] = []
    for t in turns:
        spk = t.get("speaker", "A")
        if spk not in speakers:
            speakers.append(spk)

    if len(speakers) > 2:
        raise ValueError(
            f"Dia supports exactly 2 speakers, got {len(speakers)}: "
            f"{speakers}",
        )

    mapping: dict[str, str] = {"A": "S1"}
    if len(speakers) == 2:
        mapping[speakers[1]] = "S2"

    formatted: list[str] = []
    for t in turns:
        spk = mapping.get(t.get("speaker", "A"), "S1")
        text = to_dia_text(t.get("text", "").strip())
        if text:
            formatted.append(f"[{spk}] {text}")

    raw = " ".join(formatted)
    return _chunk_text(raw, max_words)


def resolve_sample(voices_dir: Path, timbre: str) -> Path | None:
    """Resolve a voice reference sample inside voices_dir.

    Accepts ``'s1'`` or ``'s2'`` (maps to s1.wav / s2.wav) or exact
    filenames.  Anything outside voices_dir raises ValueError.

    Args:
        voices_dir: Directory containing voice samples.
        timbre: Speaker id or file name to resolve.

    Returns:
        Resolved Path if found inside voices_dir.

    Raises:
        ValueError: If the resolved path escapes voices_dir.
    """
    base = voices_dir.resolve()
    # Exact match first
    exact = (voices_dir / timbre).resolve()
    if exact.is_file():
        try:
            exact.relative_to(base)
        except ValueError:
            raise ValueError(
                f"voice sample {timbre!r} escapes voices_dir",
            )
        return exact
    # Partial match (word boundary)
    for name in sorted(voices_dir.glob("*.wav")):
        if re.search(
            rf"(?:^|[-_]){re.escape(timbre)}[-_.]|$",
            name.name, re.IGNORECASE,
        ):
            candidate = (voices_dir / name).resolve()
            if candidate.is_file():
                try:
                    candidate.relative_to(base)
                except ValueError:
                    raise ValueError(
                        f"voice sample {name!r} escapes voices_dir",
                    )
                return candidate
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    # Re-exec under dia venv if engine package not importable
    try:
        import transformers  # noqa: F401
    except ImportError:
        re_py = _env("DIA_PY", "")
        if re_py and Path(re_py).exists():
            os.execv(
                re_py, [re_py, __file__, "--config", args.config],
            )
            return  # unreachable, but mypy-quiet

    cfg = json.loads(Path(args.config).read_text())
    segments = cfg["segments"]
    gap_ms = int(cfg.get("gap_ms", 150))
    language = cfg.get("language", "en")
    out = Path(cfg["out"])
    out.parent.mkdir(parents=True, exist_ok=True)

    # The pipeline passes display names ("English"), tests and callers may pass codes.
    if str(language).strip().lower() not in {"en", "english"}:
        print(
            f"Dia supports English only, got {language!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Import heavy deps only inside main()
    import torch
    from transformers import AutoProcessor, DiaForConditionalGeneration

    # Chunk the dialogue
    try:
        chunks = chunk_dialogue(segments)
    except ValueError as exc:
        print(f"Dia dialogue error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not chunks:
        print("no audio produced", file=sys.stderr)
        sys.exit(1)

    # Load model and processor
    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = AutoProcessor.from_pretrained(_MODEL)
    model = DiaForConditionalGeneration.from_pretrained(
        _MODEL,
        torch_dtype=torch.float16,
        device_map="auto" if device == "cuda" else None,
    )
    model.eval()

    sr_ref = 24000  # Dia fixed output sample rate

    pieces: list = []

    for i, chunk in enumerate(chunks):
        inputs = processor(
            text=chunk, padding=True, return_tensors="pt",
        ).to(model.device, model.dtype)

        # Dia picks new random voices per generate(); one seed per render keeps
        # S1/S2 the same voices across chunks. (Voice cloning needs the
        # reference transcript as a text prefix; not wired up yet.)
        torch.manual_seed(int(cfg.get("seed", 1234)))
        max_new_tokens = max(512, 24 * len(chunk.split()))
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                guidance_scale=3.0,
                temperature=1.8,
                top_p=0.90,
                top_k=45,
            )

        decoded = processor.batch_decode(outputs)
        if decoded:
            waveform = decoded[0]
            if isinstance(waveform, torch.Tensor):
                waveform = waveform.cpu().float().numpy().reshape(-1)
            pieces.append(waveform)

        print(f"  chunk {i + 1}/{len(chunks)} ok", flush=True)

    if not pieces:
        print("no audio produced", file=sys.stderr)
        sys.exit(1)

    if len(pieces) == 1:
        full = pieces[0]
    else:
        import numpy as np  # type: ignore[import-not-found]

        sr_int = int(sr_ref)
        gap_samples = int(sr_int * gap_ms / 1000)
        gap = np.zeros(gap_samples, dtype="float32")
        all_pieces: list = [pieces[0]]
        for p in pieces[1:]:
            all_pieces.append(gap)
            all_pieces.append(p)
        full = np.concatenate(all_pieces)

    import soundfile as sf  # type: ignore[import-not-found]
    sf.write(str(out), full, sr_ref)

    meta_path = out.with_suffix(".json")
    meta_path.write_text(json.dumps({
        "turns": [round(len(p) / sr_ref, 3) for p in pieces],
        "sample_rate": sr_ref,
        "duration_s": round(len(full) / sr_ref, 2),
        "engine": "dia",
    }))

    timing_file = out.parent / f"{out.stem}.timing.json"
    timing_file.write_text(
        json.dumps([round(len(p) / sr_ref, 3) for p in pieces]),
    )

    print(
        f"dia: {len(chunks)} chunks, {len(full) / sr_ref:.1f}s total, "
        f"written to {out}",
    )


if __name__ == "__main__":
    main()