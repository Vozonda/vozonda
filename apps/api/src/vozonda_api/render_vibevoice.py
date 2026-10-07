"""VibeVoice-1.5B renderer script for vozonda.

Reads a config JSON (segments, voices, gap_ms, language, out), builds a
multi-speaker chat-template conversation, and writes episode audio with the
VibeVoice-1.5B model via Hugging Face transformers >= 5.17.

CLI contract matches render_kokoro.py:
    render_vibevoice.py --config cfg.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np


def _env(name: str, default: str | None = None) -> str | None:
    """vozonda_api.env without a top-level import: plain-file runs lack the path."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from vozonda_api.env import env as _read_env

    return _read_env(name, default)

MODEL = "vibevoice/VibeVoice-1.5B-hf"
DEFAULT_VOICE = "en-Frank_man.wav"


def resolve_sample(voices_dir: Path, timbre: str) -> Path | None:
    """Voice id or file name -> reference wav inside voices_dir.

    Vozonda passes voice ids ('frank', 'maya'); the upstream demo voices are
    named 'en-Frank_man.wav'. Accept an exact file name first, then the first
    wav whose name contains the id as a word. Anything outside voices_dir is
    refused.
    """
    base = voices_dir.resolve()
    exact = (voices_dir / timbre).resolve()
    if exact.is_file() and base in exact.parents:
        return exact
    token = re.compile(rf"(?:^|[-_]){re.escape(timbre)}(?:[-_.]|$)", re.IGNORECASE)
    for cand in sorted(voices_dir.glob("*.wav")):
        if token.search(cand.name):
            return cand.resolve()
    return None


def build_conversation(
    segments: list[dict], voices: dict, voices_dir: Path
) -> list[dict]:
    """Build a single multi-speaker conversation for VibeVoice.

    Each segment maps to a turn.  A speaker's *first* turn also carries
    ``{'type': 'audio', 'url': <sample_path>}`` so that the VibeVoice
    processor can use the reference voice sample.

    Args:
        segments: List of segment dicts with ``speaker`` and ``text`` keys.
        voices: Mapping from speaker label (e.g. ``'A'``, ``'B'``) to a
            voice config dict with ``timbre`` or a plain timbre string.
        voices_dir: Directory containing voice sample ``.wav`` files.

    Returns:
        A list containing one conversation (list of turn dicts) in the
        VibeVoice chat-template format.

    Raises:
        ValueError: If more than 4 unique speakers are requested.
    """
    speaker_order: list[str] = []
    for seg in segments:
        spk = seg.get("speaker", "A")
        if spk not in speaker_order:
            speaker_order.append(spk)

    if len(speaker_order) > 4:
        raise ValueError(
            f"VibeVoice supports at most 4 speakers, got {len(speaker_order)}",
        )

    conversation: list[dict] = []
    first_turn_for_speaker: set[str] = set()

    for seg in segments:
        spk = seg.get("speaker", "A")
        text = seg.get("text", "").strip()
        if not text:
            continue

        # Clean text of stage directions like [laughs], (sighs)
        text = re.sub(r"\[[a-zA-Z0-9\s_,-]+\]", "", text).strip()
        text = re.sub(r"\([a-zA-Z0-9\s_,-]+\)", "", text).strip()
        if not text:
            continue

        role = str(speaker_order.index(spk))
        turn: dict = {"role": role, "content": text}

        # Attach voice sample on first turn for this speaker
        if spk not in first_turn_for_speaker:
            vc = voices.get(spk, {})
            timbre = vc.get("timbre") if isinstance(vc, dict) else vc
            if timbre:
                sample_path = resolve_sample(voices_dir, str(timbre))
                if sample_path is not None:
                    turn["type"] = "audio"
                    turn["url"] = str(sample_path)
            first_turn_for_speaker.add(spk)

        conversation.append(turn)

    return [conversation]


def _to_template_format(conversation: list[dict]) -> list[dict]:
    """Convert build_conversation output to apply_chat_template format.

    VibeVoice's apply_chat_template expects content items as lists:
    ``[{"type": "text", "text": "..."}, {"type": "audio", "url": "..."}]``
    whereas build_conversation returns the simpler turn-level format
    where audio is carried as ``{"type": "audio", "url": ...}`` on the
    turn dict itself.
    """
    result: list[dict] = []
    for turn in conversation:
        role = turn["role"]
        content: list[dict] = [{"type": "text", "text": turn["content"]}]
        if turn.get("type") == "audio" and "url" in turn:
            content.append({"type": "audio", "url": turn["url"]})
        result.append({"role": role, "content": content})
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    segments = cfg["segments"]
    voices = cfg.get("voices", {})
    out = Path(cfg["out"])
    out.parent.mkdir(parents=True, exist_ok=True)

    voices_dir = Path(
        _env("VIBEVOICE_VOICES",
            "/data/projects/tts-spike/VibeVoice/demo/voices",
        ),
    )

    # Import heavy deps only inside main()
    import torch
    from transformers import AutoModelForTextToWaveform, AutoProcessor

    # Build conversation
    try:
        conversations = build_conversation(segments, voices, voices_dir)
    except ValueError as exc:
        print(f"VibeVoice conversation error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not conversations or not conversations[0]:
        print("no audio produced", file=sys.stderr)
        sys.exit(1)

    # Convert to apply_chat_template format
    template_conversations = [
        _to_template_format(conv) for conv in conversations
    ]

    # Load model and processor (reference pattern)
    processor = AutoProcessor.from_pretrained(MODEL)
    model = AutoModelForTextToWaveform.from_pretrained(
        MODEL,
        dtype=torch.bfloat16,
        device_map="auto",
    )
    model.eval()

    # Set max_new_tokens: ~4 tokens per word, minimum 400
    total_words = sum(
        len(turn["content"].split()) for conv in conversations for turn in conv
    )
    max_new_tokens = max(400, 4 * total_words)

    # Generate audio (one conversation at a time, concatenate)
    pieces: list[np.ndarray] = []
    sr_ref: int | None = None

    for conv in template_conversations:
        inputs = processor.apply_chat_template(
            conv,
            return_dict=True,
            tokenize=True,
            add_generation_prompt=True,
        ).to(model.device, model.dtype)
        model.generation_config.max_new_tokens = max_new_tokens
        with torch.inference_mode():
            audio = model.generate(**inputs)
        sr_ref = 24000  # VibeVoice fixed output sample rate

        # Extract waveform from model output
        # generate() returns (batch, samples) or (batch, 1, samples); soundfile
        # needs 1-D, otherwise it reads the samples as channels and fails.
        waveform = np.asarray(audio[0].cpu().float().numpy()).reshape(-1)
        pieces.append(waveform)

    if not pieces:
        print("no audio produced", file=sys.stderr)
        sys.exit(1)

    full = np.concatenate(pieces)
    import soundfile as sf  # type: ignore[import-not-found]

    sf.write(str(out), full, sr_ref)

    # Write timing metadata
    turn_durations: list[float] = []
    total_chars = sum(
        len(t["content"]) for c in conversations for t in c
    ) or 1
    total_duration = round(len(full) / sr_ref, 2) if sr_ref else 0.0
    for conv in conversations:
        for turn in conv:
            duration = total_duration * len(turn["content"]) / total_chars
            turn_durations.append(round(duration, 3))

    meta_path = out.with_suffix(".json")
    meta_path.write_text(
        json.dumps({
            "turns": turn_durations,
            "sample_rate": sr_ref or 24000,
            "duration_s": total_duration,
            "engine": "vibevoice",
        }),
    )

    timing_file = out.parent / f"{out.stem}.timing.json"
    timing_file.write_text(json.dumps(turn_durations))

    print(
        f"vibevoice: {len(conversations[0]) if conversations else 0} turns, "
        f"{total_duration}s total, written to {out}",
    )


if __name__ == "__main__":
    main()