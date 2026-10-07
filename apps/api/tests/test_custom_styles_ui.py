"""Gate for VOZONDA-CUSTOM-STYLES-UI: text checks on the web sources.

No server, no GPU, no network: reads the Svelte/TS sources as text.
"""

from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "lib"
EDITOR = WEB / "components" / "CustomStyleEditor.svelte"
SETTINGS = WEB / "components" / "SettingsScreen.svelte"
API = WEB / "api.ts"
STYLES = WEB / "styles.ts"

RHYTHM_TYPES = ["peer", "host_expert", "narrator_listener", "interrogator", "calm"]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_editor_exists_with_rhythm_types_and_role_fields():
    text = _read(EDITOR)
    for rt in RHYTHM_TYPES:
        assert rt in text, f"rhythm type {rt!r} missing in CustomStyleEditor.svelte"
    for needle in ["host A role", "host B role", "rhythm", "tone", "maxlength=\"40\"",
                   "maxlength=\"120\"", "maxlength=\"400\"", "maxlength=\"300\""]:
        assert needle in text, f"{needle!r} missing in CustomStyleEditor.svelte"


def test_api_has_four_custom_style_calls():
    text = _read(API)
    for needle in ["listCustomStyles", "createCustomStyle", "updateCustomStyle", "deleteCustomStyle"]:
        assert needle in text, f"{needle!r} missing in api.ts"
    assert text.count("/styles/custom") >= 4, "api.ts must call /styles/custom four times"


def test_sec_script_mounts_your_styles_section():
    text = _read(SETTINGS)
    assert 'id="sec-script"' in text
    assert "your styles" in text
    assert "CustomStyleEditor" in text
    sec = text.index('id="sec-script"')
    assert text.index("your styles", sec) > sec


def test_custom_group_in_style_picker():
    text = _read(STYLES)
    assert "custom" in text
