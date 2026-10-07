"""Storage stats and media retention cleanup (360 days default).

Calculates disk usage of MEDIA_DIR and prunes audio files older than
the retention threshold on demand or scheduled.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .providers import MEDIA_DIR

DEFAULT_RETENTION_DAYS = 360
PROTECTED_FILENAMES = {"og-default.png", ".gitkeep"}


def get_storage_stats(media_dir: Path | None = None, retention_days: int = DEFAULT_RETENTION_DAYS) -> dict[str, Any]:
    """Return disk usage statistics for MEDIA_DIR."""
    root = media_dir or MEDIA_DIR
    if not root.exists():
        return {
            "total_bytes": 0,
            "file_count": 0,
            "audio_files": 0,
            "retention_days": retention_days,
            "prunable_files": 0,
            "prunable_bytes": 0,
        }

    now = time.time()
    cutoff = now - (retention_days * 86400)

    total_bytes = 0
    file_count = 0
    audio_files = 0
    prunable_files = 0
    prunable_bytes = 0

    try:
        for entry in root.iterdir():
            if not entry.is_file() or entry.name in PROTECTED_FILENAMES:
                continue
            try:
                st = entry.stat()
                sz = st.st_size
                total_bytes += sz
                file_count += 1
                if entry.suffix.lower() in (".mp3", ".wav"):
                    audio_files += 1

                if st.st_mtime < cutoff:
                    prunable_files += 1
                    prunable_bytes += sz
            except (OSError, PermissionError):
                continue
    except (OSError, PermissionError):
        pass

    return {
        "total_bytes": total_bytes,
        "file_count": file_count,
        "audio_files": audio_files,
        "retention_days": retention_days,
        "prunable_files": prunable_files,
        "prunable_bytes": prunable_bytes,
    }


def purge_old_media(media_dir: Path | None = None, days: int = DEFAULT_RETENTION_DAYS) -> dict[str, Any]:
    """Delete media files older than `days` days from MEDIA_DIR."""
    root = media_dir or MEDIA_DIR
    if not root.exists():
        return {
            "purged_count": 0,
            "freed_bytes": 0,
            "days": days,
            "remaining_bytes": 0,
        }

    now = time.time()
    cutoff = now - (days * 86400)

    purged_count = 0
    freed_bytes = 0

    try:
        for entry in root.iterdir():
            if not entry.is_file() or entry.name in PROTECTED_FILENAMES:
                continue
            try:
                st = entry.stat()
                if st.st_mtime < cutoff:
                    sz = st.st_size
                    entry.unlink(missing_ok=True)
                    purged_count += 1
                    freed_bytes += sz
            except (OSError, PermissionError):
                continue
    except (OSError, PermissionError):
        pass

    stats = get_storage_stats(media_dir=root, retention_days=days)

    return {
        "purged_count": purged_count,
        "freed_bytes": freed_bytes,
        "days": days,
        "remaining_bytes": stats["total_bytes"],
    }
