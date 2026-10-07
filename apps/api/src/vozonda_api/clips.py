"""Audio clip slicing from transcript lines (DUE-020 / #184).

Extracts precise MP3 segments from a finished episode using per-turn
timestamps (script[].t0) so that the clip bounds align exactly with the
selected transcript lines.

Provider-agnostic: works regardless of TTS engine (qwen_tts, voxtral,
piper) because it slices the mastered MP3, not the raw voice wavs.
"""

from __future__ import annotations

import asyncio
import logging
import re as _re
import subprocess
from pathlib import Path
from typing import Any

from .providers import MEDIA_DIR

logger = logging.getLogger(__name__)


async def get_audio_duration(mp3: Path) -> float:
    """Return duration in seconds via ffprobe, 0.0 on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(mp3),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        if proc.returncode == 0:
            return float((out.decode() or "0").strip() or 0)
    except Exception:
        logger.debug("ffprobe duration probe failed for %s", mp3, exc_info=True)
    return 0.0


def get_audio_duration_sync(mp3: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception:
        logger.debug("ffprobe sync duration probe failed for %s", mp3, exc_info=True)
    return 0.0


def compute_clip_bounds(
    script: list[dict[str, Any]],
    turn_start: int,
    turn_end: int,
    total_duration: float | None = None,
) -> tuple[float, float]:
    """Compute start/end seconds for lines [turn_start .. turn_end] inclusive.

    Uses stored per-turn t0 when available; falls back to proportional
    character length when t0 is missing (e.g. legacy jobs).

    Returns (start_sec, end_sec) rounded to 2 decimals.
    Raises ValueError for invalid indices.
    """
    n = len(script)
    if n == 0:
        raise ValueError("no transcript lines")
    if turn_start < 0 or turn_end < 0 or turn_start >= n or turn_end >= n:
        raise ValueError(f"turn indices out of range [0,{n-1}]")
    if turn_start > turn_end:
        raise ValueError("turn_start must be <= turn_end")

    # Prefer t0-based bounds when available on the selected range
    start_entry = script[turn_start]
    start_t0 = start_entry.get("t0")

    has_t0 = isinstance(start_t0, (int, float))

    # check that all selected lines have t0, otherwise fallback to proportional
    if has_t0:
        for idx in range(turn_start, turn_end + 1):
            if not isinstance(script[idx].get("t0"), (int, float)):
                has_t0 = False
                break

    if has_t0:
        start = float(start_t0)  # type: ignore[arg-type]
        # end is t0 of next line after turn_end, or total_duration
        next_idx = turn_end + 1
        if next_idx < n and isinstance(script[next_idx].get("t0"), (int, float)):
            end = float(script[next_idx]["t0"])  # type: ignore[arg-type]
        elif total_duration and total_duration > 0:
            end = float(total_duration)
        else:
            # estimate: last selected line duration approximated from text length
            # fall back to proportional for the tail: allocate remaining proportionally
            total_chars = sum(len(ln.get("text", "")) for ln in script) or 1
            # total_duration unknown -> use character fallback without duration: add 3s per remaining line estimate
            # but we still need a concrete end; use start + heuristic
            remaining_chars = sum(len(script[i].get("text", "")) for i in range(turn_start, turn_end + 1))
            # heuristic: ~14 chars per second (average speech)
            est = remaining_chars / 14.0
            # ensure at least 1s and not overlapping next line guess
            est = max(1.0, est)
            end = start + est
            if total_duration and total_duration > 0:
                end = min(end, float(total_duration))
        # clamp and round
        start = max(0.0, round(start, 2))
        end = round(end, 2)
        if end <= start:
            end = round(start + 0.5, 2)
        return start, end

    # Fallback: proportional character approximation
    if total_duration is None or total_duration <= 0:
        # no duration at all -> give heuristic based on char count
        remaining_chars = sum(len(script[i].get("text", "")) for i in range(turn_start, turn_end + 1))
        est_start = sum(len(script[i].get("text", "")) for i in range(turn_start)) / 14.0
        est_end = est_start + max(1.0, remaining_chars / 14.0)
        return round(est_start, 2), round(est_end, 2)

    total_chars = sum(len(ln.get("text", "")) for ln in script) or 1
    chars_before = sum(len(script[i].get("text", "")) for i in range(turn_start))
    chars_selected = sum(len(script[i].get("text", "")) for i in range(turn_start, turn_end + 1))
    start = round(total_duration * chars_before / total_chars, 2)
    end = round(total_duration * (chars_before + chars_selected) / total_chars, 2)
    if end <= start:
        end = round(min(total_duration, start + 0.5), 2)
    return start, end


async def slice_audio(
    source: Path,
    dest: Path,
    start: float,
    end: float,
) -> Path:
    """Slice [start, end) from source MP3 into dest with 50 ms fades.

    Re-encodes at 128k. Uses -ss before -i for fast seek and -to for precise
    end. Duration D = end - start.

    Raises RuntimeError if ffmpeg fails or output is missing/empty.
    """
    if not source.exists():
        raise FileNotFoundError(f"source not found: {source}")
    duration = round(end - start, 3)
    if duration <= 0:
        raise ValueError("clip duration must be > 0")
    if duration < 0.08:
        # too short for both fades, use single short fade
        af = f"afade=t=in:st=0:d={duration/2:.3f},afade=t=out:st={duration/2:.3f}:d={duration/2:.3f}"
    else:
        fade_d = 0.05
        out_st = max(0.05, duration - fade_d)
        af = f"afade=t=in:st=0:d={fade_d:.3f},afade=t=out:st={out_st:.3f}:d={fade_d:.3f}"

    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-i",
        str(source),
        "-af",
        af,
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        str(dest),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size < 512:
        detail = err.decode()[-600:] if err else "unknown ffmpeg error"
        raise RuntimeError(f"ffmpeg clip failed: {detail}")
    return dest


def ffprobe_duration_sync(mp3: Path) -> float:
    """Sync helper for non-async callers."""
    return get_audio_duration_sync(mp3)


def slugify(text: str, max_len: int = 40) -> str:
    """URL-safe slug from arbitrary text.

    Lowercases, replaces non-alphanumeric runs with a single dash,
    trims leading/trailing dashes, caps at max_len without trailing dash.
    Returns 'clip' when nothing remains.
    """
    raw = text.lower().strip()
    slug = _re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    if not slug:
        return "clip"
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "clip"


def quote_snippet(text: str, max_len: int = 60) -> str:
    """Extract first sentence or leading quote (up to max_len) from a turn."""
    if not text:
        return ""
    t = text.strip().replace("\n", " ")
    # collapse whitespace
    t = _re.sub(r"\s+", " ", t).strip()
    if not t:
        return ""
    # prefer first sentence boundary (. ! ? followed by space or end)
    m = _re.search(r"(.+?[.!?])(\s|$)", t)
    if m:
        candidate = m.group(1).strip()
        # strip surrounding quotes
        candidate = candidate.strip("\"'“”‘’")
        if 10 <= len(candidate) <= max_len:
            return candidate
        if len(candidate) > max_len:
            # truncate at word boundary
            cut = candidate[:max_len].rstrip()
            # try not to cut mid-word
            if len(candidate) > max_len and " " in cut:
                cut = cut.rsplit(" ", 1)[0]
            return cut
        # candidate shorter than 10 chars, fall through to broader logic
    # no sentence boundary or short: take leading text up to max_len at word boundary
    if len(t) <= max_len:
        return t.strip("\"'“”‘’")
    cut = t[:max_len].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip("\"'“”‘’")


def clip_quote_snippet(script: list[dict[str, Any]], turn_start: int, turn_end: int) -> str:
    """First spoken snippet from the selected range for title/label use."""
    if not script or turn_start < 0 or turn_start >= len(script):
        return ""
    text = str(script[turn_start].get("text") or "").strip()
    return quote_snippet(text, 60)


def clip_quote_slug(script: list[dict[str, Any]], turn_start: int, turn_end: int) -> str:
    """Slugified form of the quote snippet for filenames and URL slugs."""
    snippet = clip_quote_snippet(script, turn_start, turn_end)
    if not snippet:
        return ""
    return slugify(snippet, 40)


def clip_title(quote: str, episode_title: str) -> str:
    """Quote-driven HTML/OpenGraph title: '"{quote}" · {episode} | Vozonda Audio Clip'."""
    ep = (episode_title or "untitled").strip()
    q = quote.strip()
    if q:
        return f'"{q}" · {ep} | Vozonda Audio Clip'
    return f"{ep} | Vozonda Audio Clip"


def clip_description(spoken_text: str, duration_seconds: float, episode_title: str) -> str:
    """Rich description: '"{text}" · {duration}s audio clip from {episode}. Listen and share...' capped at 160."""
    ep = (episode_title or "untitled").strip()
    dur = round(duration_seconds) if duration_seconds else 0
    # round returns int when ndigits omitted, but keep int semantics
    dur_int = int(dur)
    suffix = f" · {dur_int}s audio clip from {ep}. Listen and share with Vozonda."
    # spoken text should be quoted
    cleaned = _re.sub(r"\s+", " ", spoken_text.strip()).strip()
    # initial attempt
    desc = f'"{cleaned}"{suffix}'
    if len(desc) <= 160:
        return desc
    # need to truncate spoken text to fit
    available = 160 - len(suffix) - 2
    if available < 20:
        # if suffix itself too long, truncate episode part instead
        return desc[:157] + "..."
    truncated = cleaned[: max(0, available - 3)].rstrip()
    if " " in truncated:
        # keep word boundary
        truncated = truncated.rsplit(" ", 1)[0]
    truncated = truncated.rstrip(".,;:!?")
    return f'"{truncated}..."{suffix}'[:160]


def parse_clip_spec(spec: str) -> tuple[int, int, str | None]:
    """Parse '{start}-{end}' or '{start}-{end}-{slug}' into components.

    Returns (turn_start, turn_end, slug_or_none). Raises ValueError on mismatch.
    """
    m = _re.match(r"^(\d+)-(\d+)(?:-(.+))?$", spec.strip())
    if not m:
        raise ValueError("invalid clip spec")
    return int(m.group(1)), int(m.group(2)), m.group(3)


def clip_filename(job_id: str, turn_start: int, turn_end: int, slug: str | None = None) -> str:
    # Optional SEO slug suffix; ignored when empty to keep backward compat filenames
    if slug and slug.strip():
        safe = slugify(slug.strip(), 40)
        return f"{job_id}-clip-{turn_start}-{turn_end}-{safe}.mp3"
    return f"{job_id}-clip-{turn_start}-{turn_end}.mp3"


def clip_path(job_id: str, turn_start: int, turn_end: int, slug: str | None = None) -> Path:
    return MEDIA_DIR / clip_filename(job_id, turn_start, turn_end, slug)


def find_clip_file(job_id: str, turn_start: int, turn_end: int) -> Path | None:
    """Locate the clip file for a range, preferring slug-suffixed variant.

    Checks exact legacy name first, then glob for any slug variant.
    Returns Path if found, else None.
    """
    legacy = MEDIA_DIR / f"{job_id}-clip-{turn_start}-{turn_end}.mp3"
    if legacy.exists():
        return legacy
    # slug variant: {job_id}-clip-{start}-{end}-*.mp3
    pattern = f"{job_id}-clip-{turn_start}-{turn_end}-*.mp3"
    matches = sorted(MEDIA_DIR.glob(pattern))
    if matches:
        return matches[0]
    return None


def clip_display_label(
    script: list[dict[str, Any]], turn_start: int, turn_end: int, duration_seconds: float
) -> str:
    """Descriptive label: '{speaker} · "{quote}" ({duration}s)'."""
    snippet = clip_quote_snippet(script, turn_start, turn_end)
    speaker = ""
    if 0 <= turn_start < len(script):
        entry = script[turn_start]
        speaker = str(entry.get("name") or entry.get("speaker") or "").strip()
    speaker = speaker or "voice"
    dur = round(duration_seconds) if duration_seconds else 0
    dur_int = int(dur)
    if snippet:
        return f'{speaker} · "{snippet}" ({dur_int}s)'
    return f"{speaker} ({dur_int}s)"
