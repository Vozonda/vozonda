"""Filesystem roots from VOZONDA_* variables with defaults under ~/vozonda.

Stdlib only: renderer scripts run as plain files under engine venvs and
import this module via sys.path.
"""

from pathlib import Path

from .env import env


def _media_default() -> Path:
    shared = VOZONDA_ROOT / "media" / "vozonda"
    if shared.exists():
        return shared
    return Path(__file__).resolve().parents[4] / "media"


VOZONDA_ROOT = Path(env("ROOT") or str(Path.home() / "vozonda"))
VOZONDA_SECRETS_DIR = Path(env("SECRETS_DIR") or str(VOZONDA_ROOT / "secrets"))
VOZONDA_MEDIA = Path(env("MEDIA") or _media_default())
VOZONDA_MODELS_DIR = Path(env("MODELS_DIR") or str(VOZONDA_ROOT / "models"))

__all__ = [
    "VOZONDA_MEDIA",
    "VOZONDA_MODELS_DIR",
    "VOZONDA_ROOT",
    "VOZONDA_SECRETS_DIR",
]
