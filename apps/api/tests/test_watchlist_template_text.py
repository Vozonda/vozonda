"""VOZONDA-WATCHLIST-TEMPLATE-HONEST: watchlist templates only promise what they apply.

Static source-text checks (no HTTP, no backend needed). The watchlist feed
templates used to carry an 'advanced' block (voice.speed, voice.gap_ms,
source.research_depth) that no code ever applied: applying a template never
set those values, watchlist episodes ran on the global advanced settings, and
the 'context' label advertised the lot. Templates now promise only what they
apply (hosts, voices, emotions, style), and the tune modal's advanced
settings hint names the six settings-page groups.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent
WEB_SRC = ROOT / "apps" / "web" / "src"


def _read(path: str) -> str:
    return (WEB_SRC / path).read_text(encoding="utf-8")


class TestWatchlistTemplateHonesty:
    """Templates advertise only values they actually apply."""

    def source(self) -> str:
        return _read("lib/components/WatchlistScreen.svelte")

    def _templates_block(self) -> str:
        src = self.source()
        start = src.index("const FEED_TEMPLATES")
        end = src.index("\n  ]", start)
        return src[start:end]

    def _contexts(self) -> list[str]:
        return re.findall(r"context: '([^']*)'", self._templates_block())

    def test_type_has_no_advanced_field(self) -> None:
        src = self.source()
        start = src.index("interface TemplateValues")
        block = src[start:src.index("}", start)]
        assert "advanced" not in block, "the type no longer promises an advanced block"

    def test_templates_carry_no_advanced_key(self) -> None:
        assert "advanced" not in self._templates_block(), "no template sets an advanced block"

    def test_context_labels_list_only_applied_values(self) -> None:
        contexts = self._contexts()
        assert contexts, "found the template context labels"
        for label in contexts:
            assert "gap" not in label, label
            assert "research" not in label, label
            assert re.search(r"\d+(\.\d+)?x ·", label) is None, label

    def test_advanced_settings_hint_names_the_six_groups(self) -> None:
        src = self.source()
        assert "sources · script · voice · shows · player · system" in src
        assert "pacing · value for value" not in src

    def test_hint_matches_the_settings_page_groups(self) -> None:
        settings = _read("lib/components/SettingsScreen.svelte")
        ids = re.findall(r'<div id="(sec-[a-z]+)" class="settings-group">', settings)
        groups = [i.removeprefix("sec-") for i in ids]
        expected = "sources · script · voice · shows · player · system"
        assert " · ".join(groups) == expected
        assert expected in self.source()
