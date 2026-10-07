import os
from pathlib import Path

from .env import env


def load_env_file(path: str | Path | None = None) -> list[str]:
    """Parse KEY=VALUE pairs from a .env file into os.environ.

    Values already present in the real environment always win. A missing
    file is not an error. Returns the list of keys this call set.
    """
    env_path = (
        Path(path)
        if path is not None
        else Path(
            env("ENV_FILE")
            or (Path.cwd() / ".env" if (Path.cwd() / ".env").exists() else Path(__file__).resolve().parents[4] / ".env")
        )
    )
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    loaded: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key.isidentifier():
            continue
        value = value.strip()
        quoted = len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"')
        if quoted:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
