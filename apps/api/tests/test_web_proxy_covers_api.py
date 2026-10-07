"""The web dev/preview proxy forwards every top-level API path.

2026-09-28: the preview's hand-kept list lacked /llm, /music, /shows and
/storage, so it answered them with index.html; the settings page showed the
LLM as offline and the new model pickers stayed empty.
"""

import re
from pathlib import Path

from vozonda_api.main import app

VITE_CONFIG = Path(__file__).resolve().parents[2] / "web" / "vite.config.ts"
SERVED_BY_WEB = {"/og-default.png"}  # the web app ships its own copy in public/


def test_every_api_prefix_is_proxied():
    block = re.search(r"const API_PATHS = \[(.*?)\]", VITE_CONFIG.read_text(), re.DOTALL).group(1)
    proxied = set(re.findall(r"'(/[^']*)'", block))
    prefixes = {"/" + r.path.strip("/").split("/")[0] for r in app.routes
                if getattr(r, "path", "/") != "/"}
    assert prefixes - SERVED_BY_WEB - proxied == set()
