"""Relative links in the entry-point docs resolve (README, AGENTS, docs index)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENTRY_DOCS = ["README.md", "AGENTS.md", "docs/README.md"]
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def test_relative_links_in_entry_docs_resolve():
    broken = []
    for doc in ENTRY_DOCS:
        path = ROOT / doc
        for target in LINK.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if not (path.parent / target).exists():
                broken.append(f"{doc} -> {target}")
    assert not broken, broken
