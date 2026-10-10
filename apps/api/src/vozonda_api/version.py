"""Vozonda version resolution.

Follows PEP 440 and SemVer 2.0.0 open-source best practices.
- Single source of truth for the base milestone version: BASE_VERSION = "0.6.0"
- In development / git clones: dynamically increments the patch/dev counter
  so that every commit deployed or tested has a strictly monotonic,
  observable build identifier in UI footers, logs, and /meta.
- In production / tag release: exact tag returns canonical SemVer "0.6.0".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

BASE_VERSION = "0.7.2"


def _get_git_info() -> tuple[str, int | None, str | None]:
    """Retrieve (short_hash, commit_count, exact_tag) from git."""
    try:
        root = Path(__file__).resolve().parents[3]
        # Check exact tag first (e.g. v0.6.0)
        tag_proc = subprocess.run(
            ["git", "describe", "--tags", "--exact-match"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=root,
            check=False,
        )
        exact_tag = None
        if tag_proc.returncode == 0:
            tag_str = tag_proc.stdout.strip()
            if tag_str.startswith("v"):
                exact_tag = tag_str[1:]
            elif tag_str:
                exact_tag = tag_str

        # Commit rev
        rev_proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=root,
            check=False,
        )
        git_rev = rev_proc.stdout.strip() if rev_proc.returncode == 0 else "unknown"

        # Monotonic commit count on HEAD
        count_proc = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=root,
            check=False,
        )
        commit_count = (
            int(count_proc.stdout.strip())
            if count_proc.returncode == 0 and count_proc.stdout.strip().isdigit()
            else None
        )

        return git_rev or "unknown", commit_count, exact_tag
    except Exception:
        return "unknown", None, None


GIT_REV, COMMIT_COUNT, EXACT_TAG = _get_git_info()

if EXACT_TAG:
    __version__ = EXACT_TAG
    DISPLAY_VERSION = EXACT_TAG
elif COMMIT_COUNT is not None:
    # PEP 440 development format & monotonic build identifier
    __version__ = f"{BASE_VERSION}.dev{COMMIT_COUNT}"
    DISPLAY_VERSION = f"{BASE_VERSION}-dev.{COMMIT_COUNT}"
else:
    __version__ = BASE_VERSION
    DISPLAY_VERSION = BASE_VERSION


def get_version_info() -> dict[str, str | int | None]:
    """Return comprehensive version metadata dictionary for /meta."""
    return {
        "version": DISPLAY_VERSION,
        "pep440_version": __version__,
        "base_version": BASE_VERSION,
        "git_rev": GIT_REV,
        "commit_count": COMMIT_COUNT,
    }
