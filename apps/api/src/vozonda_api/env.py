"""VOZONDA_* environment lookup.

Stdlib only: renderer scripts run as plain files under engine venvs and
import this module via sys.path, where third-party packages are missing.
"""

import os
from typing import overload


@overload
def env(name: str, default: str) -> str: ...


@overload
def env(name: str, default: None = None) -> str | None: ...


def env(name: str, default: str | None = None) -> str | None:
    """Return the environment variable VOZONDA_<name>, else default."""
    return os.environ.get(f"VOZONDA_{name}", default)
