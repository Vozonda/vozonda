#!/usr/bin/env python3
"""Generate a one-sentence audio sample for every voice of a TTS engine.

Usage:
    python scripts/generate_voice_samples.py                       # all installed
    python scripts/generate_voice_samples.py --engine kokoro       # one engine
    python scripts/generate_voice_samples.py --engine kokoro --engine piper
    python scripts/generate_voice_samples.py --dry-run             # what would be done
    python scripts/generate_voice_samples.py --force               # overwrite existing

The script writes samples into apps/web/public/media/samples/voices/<engine>_<voice>.mp3
by writing a small JSON config and calling the engine's renderer subprocess
(the same contract that pipeline.py uses).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SAMPLE_TEXTS = {
    "en": "Vozonda turns what you read into a podcast you can subscribe to.",
    "de": "Vozonda macht aus dem, was du liest, einen Podcast zum Abonnieren.",
}

# Default text language per engine: engines that support multiple languages
# use EN because the sample is about voice timbre, not language.
ENGINE_LANG: dict[str, str] = {
    "kokoro": "en",
    "piper": "en",
    "voxtral": "en",
    "qwen_tts": "en",
}


def sample_dir() -> Path:
    """Return the directory where samples are stored."""
    return Path(__file__).resolve().parents[1] / "apps" / "web" / "public" / "media" / "samples" / "voices"


def write_cfg(out: Path, voice_id: str, engine_id: str, text: str) -> Path:
    """Write a renderer config for a single-voice sample."""
    voices_cfg = {"A": {"timbre": voice_id}}
    cfg = {
        "segments": [{"speaker": "A", "text": text}],
        "voices": voices_cfg,
        "gap_ms": 0,
        "language": ENGINE_LANG.get(engine_id, "en"),
        "out": str(out),
    }
    cfg_path = out.with_suffix(".cfg.json")
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False))
    return cfg_path


def renderer_for(engine_id: str) -> tuple[Path | None, Path | None]:
    """Return (renderer_path, render_python) or (None, None) if unknown."""
    from vozonda_api.providers import TTS_PY, tts_engines

    engines = tts_engines()
    meta = engines.get(engine_id)
    if not meta:
        return None, None

    here = Path(__file__).resolve().parents[1] / "apps" / "api" / "src"
    renderer_path = here / "vozonda_api" / (getattr(meta, "renderer", "") or "render_vozonda.py")
    if not renderer_path.exists():
        renderer_path = here / "vozonda_api" / "render_vozonda.py"

    try:
        from vozonda_api.plugins import registry

        render_py = getattr(registry.get(engine_id), "RENDER_PY", TTS_PY) or TTS_PY
    except Exception:  # noqa: BLE001
        render_py = TTS_PY

    return renderer_path, Path(render_py)


def check_installed(engine_id: str) -> bool:
    """Return True if the engine's provider module can be imported and
    the renderer path is discoverable."""
    try:
        from vozonda_api.providers import TTS_PY, tts_engines

        engines = tts_engines(refresh=True)
        meta = engines.get(engine_id)
        if not meta:
            return False
        try:
            from vozonda_api.plugins import registry

            render_py = getattr(registry.get(engine_id), "RENDER_PY", TTS_PY) or TTS_PY
        except Exception:  # noqa: BLE001
            render_py = TTS_PY
        return render_py is not None
    except Exception:  # noqa: BLE001
        return False


def render_one(out: Path, cfg_path: Path, renderer_path: Path, render_py: Path) -> bool:
    """Run a single renderer subprocess. Returns True on success."""
    from vozonda_api.providers import HF_HOME

    env = {**os.environ, "HF_HOME": HF_HOME}
    try:
        proc = subprocess.run(
            [str(render_py), str(renderer_path), "--config", str(cfg_path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=env,
        )
        if proc.returncode != 0 or not out.exists():
            print(f"  render failed ({proc.returncode}): {proc.stderr[:200]}", file=sys.stderr, flush=True)
            return False
        return True
    except subprocess.TimeoutExpired:
        print("  render timeout", file=sys.stderr, flush=True)
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"  render error: {exc}", file=sys.stderr, flush=True)
        return False


def plan(
    engine_id: str,
    force: bool = False,
    sample_dir_path: Path | None = None,
) -> list[tuple[Path, str, str]]:
    """Generate the plan for an engine: list of (output_path, voice_id, text).

    Only includes voices that don't already have a sample (unless --force).
    """
    from vozonda_api.voices import speakers_for

    voices = speakers_for(engine_id)
    if not voices:
        return []

    lang = ENGINE_LANG.get(engine_id, "en")
    text = SAMPLE_TEXTS[lang]
    sd = sample_dir_path or sample_dir()
    plan_items = []
    for spk in voices:
        vid = spk["id"]
        out = sd / f"{engine_id}_{vid}.mp3"
        if out.exists() and not force:
            continue
        plan_items.append((out, vid, text))
    return plan_items


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate voice samples for TTS engines")
    parser.add_argument(
        "--engine",
        action="append",
        default=None,
        help="Engine id(s) to generate. Repeatable. Default: all installed.",
    )
    parser.add_argument("--force", action="store_true", help="Re-render existing samples")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without rendering")
    args = parser.parse_args()

    engine_ids = args.engine
    if engine_ids:
        engine_ids = sorted(set(engine_ids))
    else:
        from vozonda_api.providers import tts_engines

        engine_ids = sorted(tts_engines().keys())

    samples_dir = sample_dir()
    samples_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    skipped = 0
    failed = 0
    started = time.time()

    for eid in engine_ids:
        if not check_installed(eid):
            print(f"skipping {eid}: not installed", file=sys.stderr)
            continue

        plan_items = plan(eid, force=args.force)
        if not plan_items:
            if args.dry_run:
                print(f"{eid}: no new samples (all up to date)")
            skipped += 1
            continue

        for out, vid, text in plan_items:
            out.parent.mkdir(parents=True, exist_ok=True)
            cfg_path = write_cfg(out, vid, eid, text)
            if args.dry_run:
                print(f"{eid} {vid}: {out}")
                total += 1
                continue

            renderer_path, render_py = renderer_for(eid)
            if not renderer_path or not render_py:
                print(f"{eid} {vid}: no renderer found, skipping", file=sys.stderr)
                failed += 1
                continue

            ok = render_one(out, cfg_path, renderer_path, render_py)
            if ok:
                size_kb = out.stat().st_size / 1024
                print(f"{eid} {vid}: {out} ({size_kb:.0f} KB)")
            else:
                failed += 1

        # clean up temp cfg (write_cfg uses out.with_suffix(".cfg.json"))
        for out, _, _ in plan_items:
            cfg_path = out.with_suffix(".cfg.json")
            if cfg_path.exists():
                cfg_path.unlink()

    elapsed = time.time() - started
    if args.dry_run:
        print(f"dry run: {total} samples would be generated")
    else:
        print(
            f"done: {total - failed - skipped} rendered, {skipped} up-to-date, "
            f"{failed} failed, {elapsed:.1f}s total"
        )


if __name__ == "__main__":
    main()
