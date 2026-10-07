"""Gate for VOZONDA-TRAY-SETTINGS: text checks on the web sources.

The settings screen carries a 'source tray' block (max sources, max source
length) and the FAQ shows the real /meta values instead of a fixed number.
Longer sources are condensed, not cut.

No server, no GPU, no network: reads the Svelte/TS sources as text.
"""

from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "lib"
SETTINGS = WEB / "components" / "SettingsScreen.svelte"
FAQ = WEB / "components" / "FaqScreen.svelte"
API = WEB / "api.ts"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_source_tray_block_in_sec_sources_with_both_keys():
    text = _read(SETTINGS)
    assert 'id="sec-sources"' in text
    sec = text.index('id="sec-sources"')
    end = text.index('id="sec-script"')
    block = text[sec:end]
    assert "source tray" in block, "'source tray' block missing in #sec-sources"
    assert "source.max_sources" in block, "source.max_sources missing in #sec-sources"
    assert "source.max_chars" in block, "source.max_chars missing in #sec-sources"


def test_source_tray_controls_save_through_settings():
    text = _read(SETTINGS)
    assert "set('source.max_sources'" in text, "max sources control must save via set()"
    assert "set('source.max_chars'" in text, "max source length control must save via set()"
    assert "max_source_chars" in text, "auto readout must come from /meta max_source_chars"


def test_faq_honest_numbers_no_fixed_60000():
    text = _read(FAQ)
    assert "60,000" not in text, "fixed '60,000' must go, the FAQ shows the /meta values"
    assert "max_source_chars" in text, "FaqScreen must read max_source_chars from /meta"
    assert "max_sources" in text, "FaqScreen must read max_sources from /meta"
    assert "condensed, not cut" in text, "FAQ must say longer sources are condensed, not cut"


def test_meta_type_has_tray_fields():
    text = _read(API)
    assert "max_source_chars" in text
    assert "max_sources" in text
