"""Music asset store and safe URL-only ingestion seam (DUE-093).

Provides:
- SSRF-safe bounded URL audio fetching (15 MB max)
- Validation via ffprobe (must be a valid audio stream)
- Transcoding and normalization via ffmpeg (44.1kHz stereo MP3, max 120s)
- Safe storage in MEDIA_DIR / "music" / {kind}.mp3
- Status inspection and reset to procedural harmonic jazz fallbacks
"""

import asyncio
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .fetcher import FetchError, guard_url, guarded_client
from .providers import MEDIA_DIR

logger = logging.getLogger(__name__)

MAX_MUSIC_BYTES = 15_000_000  # 15 MB
MAX_DURATION_SECONDS = 120.0  # 2 minutes max for jingles/beds


def get_music_dir() -> Path:
    """Return the active music directory under MEDIA_DIR, creating it if needed."""
    music_dir = MEDIA_DIR / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    return music_dir


def _probe_audio(file_path: Path) -> tuple[float, str]:
    """Inspect an audio file using ffprobe; returns (duration_seconds, codec_name).

    Raises ValueError if ffprobe fails or the file contains no audio streams.
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(file_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=True, text=True, timeout=10)
        data = json.loads(proc.stdout)
        streams = data.get("streams", [])
        if not streams:
            raise ValueError("File contains no valid audio streams")
        codec = streams[0].get("codec_name", "unknown")
        duration = float(data.get("format", {}).get("duration", 0.0))
        return duration, codec
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.strip() or "ffprobe failed"
        raise ValueError(f"Invalid or corrupted audio file: {err_msg}") from e
    except subprocess.TimeoutExpired as e:
        raise ValueError("Audio probe timed out") from e


def _transcode_and_normalize(src_path: Path, dest_path: Path) -> float:
    """Transcode and normalize input audio to standard 44.1kHz stereo MP3 (max 120s)."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src_path),
        "-t",
        str(MAX_DURATION_SECONDS),
        "-vn",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-b:a",
        "192k",
        str(dest_path),
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=30)
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.decode("utf-8", errors="replace").strip() or "ffmpeg transcode failed"
        raise ValueError(f"Audio transcoding failed: {err_msg}") from e
    except subprocess.TimeoutExpired as e:
        raise ValueError("Audio transcoding timed out") from e

    # Re-probe final destination to verify
    duration, _ = _probe_audio(dest_path)
    return duration


def _write_bytes_sync(path: Path, data: bytes) -> None:
    path.write_bytes(data)


async def import_music_from_url(url: str, kind: str = "intro") -> dict[str, Any]:
    """Fetch an audio track safely from URL, validate, normalize, and store it."""
    url = url.strip()
    if not url:
        raise ValueError("URL cannot be empty")

    norm_kind = kind.lower().strip()
    if norm_kind in ("bed", "theme", "intro_music", "jingle_intro"):
        norm_kind = "intro"
    elif norm_kind in ("outro_music", "jingle_outro"):
        norm_kind = "outro"

    if norm_kind not in ("intro", "outro"):
        raise ValueError("kind must be 'intro' or 'outro'")

    # 1. SSRF Protection
    guard_url(url)

    music_dir = get_music_dir()
    dest_file = music_dir / f"{norm_kind}.mp3"

    # 2. Bounded Download into Temp File
    with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        downloaded = bytearray()
        async with (
            guarded_client(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True) as client,
            client.stream("GET", url, headers={"User-Agent": f"vozonda/{__version__} (+https://vozonda.com; music-download)"}) as resp,
        ):
            if resp.status_code >= 400:
                raise FetchError(f"HTTP error {resp.status_code} fetching audio from URL")
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                downloaded.extend(chunk)
                if len(downloaded) > MAX_MUSIC_BYTES:
                    raise ValueError(f"Audio file exceeds maximum size of {MAX_MUSIC_BYTES // 1_000_000} MB")

        if len(downloaded) < 512:
            raise ValueError("Downloaded file is too small to be valid audio")

        await asyncio.to_thread(_write_bytes_sync, tmp_path, bytes(downloaded))

        # 3. Probe with ffprobe
        _raw_dur, raw_codec = _probe_audio(tmp_path)

        # 4. Transcode and normalize to final destination
        final_duration = await asyncio.to_thread(_transcode_and_normalize, tmp_path, dest_file)

        return {
            "ok": True,
            "kind": norm_kind,
            "filename": dest_file.name,
            "raw_codec": raw_codec,
            "duration": round(final_duration, 2),
            "size_bytes": dest_file.stat().st_size,
            "url": f"/music/{norm_kind}.mp3",
        }
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def get_music_status() -> dict[str, Any]:
    """Inspect current music files and return status for intro and outro."""
    music_dir = get_music_dir()
    intro_file = music_dir / "intro.mp3"
    outro_file = music_dir / "outro.mp3"

    intro_info: dict[str, Any] = {"active": False, "mode": "procedural", "label": "built-in harmonic jazz"}
    if intro_file.exists() and intro_file.stat().st_size > 100:
        try:
            dur, _ = _probe_audio(intro_file)
            intro_info = {
                "active": True,
                "mode": "custom",
                "label": "custom intro track",
                "filename": intro_file.name,
                "duration": round(dur, 2),
                "size_bytes": intro_file.stat().st_size,
                "url": "/music/intro.mp3",
            }
        except Exception:
            logger.warning("intro music probe failed, using procedural fallback", exc_info=True)

    outro_info: dict[str, Any] = {"active": False, "mode": "procedural", "label": "built-in harmonic jazz"}
    if outro_file.exists() and outro_file.stat().st_size > 100:
        try:
            dur, _ = _probe_audio(outro_file)
            outro_info = {
                "active": True,
                "mode": "custom",
                "label": "custom outro track",
                "filename": outro_file.name,
                "duration": round(dur, 2),
                "size_bytes": outro_file.stat().st_size,
                "url": "/music/outro.mp3",
            }
        except Exception:
            logger.warning("outro music probe failed, using procedural fallback", exc_info=True)

    return {
        "intro": intro_info,
        "outro": outro_info,
        "procedural_palette": "Cmaj9 / Fmaj7 jazz progression with smooth raised-cosine ducking (-12 dB)",
    }


def reset_music(kind: str = "all") -> dict[str, Any]:
    """Remove imported custom music files, reverting to procedural jingles."""
    music_dir = get_music_dir()
    removed: list[str] = []

    kinds = ["intro", "outro"] if kind == "all" else [kind]
    for k in kinds:
        for ext in (".mp3", ".wav", ".ogg", ".flac"):
            p = music_dir / f"{k}{ext}"
            if p.exists():
                p.unlink(missing_ok=True)
                removed.append(p.name)

    return {"ok": True, "removed": removed, "status": get_music_status()}


def get_or_create_preview_audio(kind: str = "intro") -> Path:
    """Return path to custom audio or generate procedural preview audio if built-in."""
    music_dir = get_music_dir()
    target_file = music_dir / f"{kind}.mp3"
    if target_file.exists() and target_file.stat().st_size > 100:
        return target_file

    # Generate procedural preview track
    preview_file = music_dir / f"procedural_{kind}_preview.mp3"
    if preview_file.exists() and preview_file.stat().st_size > 100:
        return preview_file

    import soundfile as sf

    from .music import generate_jingle

    is_outro = (kind == "outro")
    sig = generate_jingle(duration=8.0, sr=24000, is_outro=is_outro, palette="jazz_calm")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        sf.write(str(tmp_path), sig, 24000)
        _transcode_and_normalize(tmp_path, preview_file)
        return preview_file
    finally:
        tmp_path.unlink(missing_ok=True)
