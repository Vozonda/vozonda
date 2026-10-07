"""Every top-level API path is proxied by the web preview (vite.config.ts API_PATHS).

A missing path makes the preview answer with index.html instead of JSON: on 2026-09-28
the settings showed the LLM offline; on 2026-10-02 /distribution, /billing and /feed
were missing. Routers included into the app count too (they hide behind
_IncludedRouter in this FastAPI version)."""
import pathlib
import re

from vozonda_api.main import app

VITE = pathlib.Path(__file__).resolve().parents[2] / "web" / "vite.config.ts"


def _top_level_paths() -> set[str]:
    paths = []
    for r in app.routes:
        if hasattr(r, "path"):
            paths.append(r.path)
        elif hasattr(r, "original_router"):
            paths += [x.path for x in r.original_router.routes if hasattr(x, "path")]
    return {"/" + p.split("/")[1] for p in paths
            if p.startswith("/") and len(p) > 1 and not p.split("/")[1].startswith("{")}


def test_every_api_path_is_proxied_by_the_preview():
    listed = set(re.findall(r"'(/[^']+)'", VITE.read_text(encoding="utf-8")))
    assert _top_level_paths() - listed == set()
