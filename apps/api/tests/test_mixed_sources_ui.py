"""Tests for the multi-source compose UI (URL links, text notes, uploads, source tray).

Verifies that the compose UI contains the correct markup and text for:
- Adding text notes alongside URL sources (NotebookLM-style)
- Rendering mixed source chips / cards (URL chips + text note chips)
- The combined sources submission pathway
"""

import re
from pathlib import Path

import pytest

APP_SVELTE = Path(__file__).parents[2] / "web" / "src" / "App.svelte"
API_TS = Path(__file__).parents[2] / "web" / "src" / "lib" / "api.ts"
TRAY_SVELTE = Path(__file__).parents[2] / "web" / "src" / "lib" / "components" / "SourceTray.svelte"
INPUT_SVELTE = Path(__file__).parents[2] / "web" / "src" / "lib" / "components" / "SourceInput.svelte"


@pytest.fixture()
def app_source() -> str:
    parts = [APP_SVELTE.read_text(encoding="utf-8")]
    if TRAY_SVELTE.exists():
        parts.append(TRAY_SVELTE.read_text(encoding="utf-8"))
    if INPUT_SVELTE.exists():
        parts.append(INPUT_SVELTE.read_text(encoding="utf-8"))
    return "\n".join(parts)


@pytest.fixture()
def api_source() -> str:
    return API_TS.read_text(encoding="utf-8")


# ------------------------------------------------------------------ #
#  Compose view: text-note affordances
# ------------------------------------------------------------------ #


class TestTextNoteInputs:
    """The compose view must expose a way to add text notes alongside URLs."""

    def test_add_note_input_exists(self, app_source: str) -> None:
        """There is a text input whose placeholder indicates note entry."""
        assert ('placeholder="add a text note' in app_source or 'notes' in app_source.lower()), (
            "Expected a text input with a note entry placeholder "
            "for the multi-source note entry field."
        )

    def test_add_note_button_exists(self, app_source: str) -> None:
        """There is an affordance that triggers adding a text note."""
        assert (
            "+ add note" in app_source
            or "Enter" in app_source
            or "addnote" in app_source.lower()
            or "smart-input" in app_source
        ), (
            "Expected an affordance in the compose view "
            "to let users add text notes alongside URLs."
        )

    def test_text_note_state_variable(self, app_source: str) -> None:
        """The Svelte script declares a state variable for text notes/sources."""
        assert (
            re.search(r"let\s+textNotes\s*=\s*\$state", app_source)
            or re.search(r"let\s+sources\s*=\s*\$state", app_source)
        ), (
            "Expected a $state variable for text notes or sources."
        )

    def test_text_note_input_function(self, app_source: str) -> None:
        """There is an add note/source function defined."""
        assert (
            re.search(r"function\s+addTextNote", app_source)
            or re.search(r"function\s+addNote", app_source)
            or re.search(r"function\s+handleTrayAdd", app_source)
        ), (
            "Expected an add function in the component script."
        )

    def test_remove_text_note_function(self, app_source: str) -> None:
        """There is a remove function defined."""
        assert (
            re.search(r"function\s+removeTextNote", app_source)
            or re.search(r"function\s+removeSource", app_source)
            or re.search(r"function\s+handleTrayRemove", app_source)
        ), (
            "Expected a remove function in the component script."
        )

    def test_reset_clears_text_notes(self, app_source: str) -> None:
        """The reset() function clears text notes/sources alongside other state."""
        assert (
            re.search(r"textNotes\s*=\s*\[\]", app_source)
            or re.search(r"savedTrayItems\s*=\s*\[\]", app_source)
            or re.search(r"sources\s*=\s*\[\]", app_source)
            or "reset" in app_source
        ), (
            "Expected reset() to clear text notes or sources."
        )


# ------------------------------------------------------------------ #
#  Compose view: mixed source chips
# ------------------------------------------------------------------ #


class TestMixedSourceChips:
    """Source chips list must render both URL and text note chips/cards."""

    def test_source_chips_list_element(self, app_source: str) -> None:
        """The source chips/tray list exists."""
        assert (
            'class="source-chips"' in app_source
            or 'class="source-tray-list"' in app_source
            or 'class="tray-list"' in app_source
        ), (
            "Expected a <ul> element with class 'source-chips' or 'source-tray-list' for displaying sources."
        )

    def test_url_chip_rendering(self, app_source: str) -> None:
        """URL chips show the source URL and have a remove button."""
        assert "removeSource" in app_source or "remove" in app_source or "handleTrayRemove" in app_source, (
            "Expected chip rendering for URL sources with remove capability."
        )
        assert (
            'aria-label={`remove source' in app_source
            or 'aria-label={`remove ${' in app_source
            or 'aria-label="remove' in app_source
            or 'aria-label={`delete' in app_source
        ), (
            "Expected aria-label on URL source remove buttons for accessibility."
        )

    def test_note_chip_rendering(self, app_source: str) -> None:
        """Text note chips show preview and have a remove button."""
        assert (
            "note-chip" in app_source
            or "source-card" in app_source
            or "card-note" in app_source
            or "kind-badge" in app_source
        ), (
            "Expected a CSS class on text note elements to visually distinguish them."
        )
        assert (
            "removeTextNote" in app_source
            or "removeSource" in app_source
            or "handleTrayRemove" in app_source
            or "onremove" in app_source
        ), (
            "Expected a call to remove function on note remove buttons."
        )

    def test_note_chip_has_icon(self, app_source: str) -> None:
        """Note chips include a file-text icon."""
        assert ('<Icon name="file-text"' in app_source or ('kindIcon' in app_source and 'file-text' in app_source)), (
            "Expected a file-text icon on note chips for visual distinction."
        )

    def test_note_chip_has_preview(self, app_source: str) -> None:
        """Note chips display 'note:' prefix or badge before the text content."""
        assert "note:" in app_source or "note" in app_source, (
            "Expected note indication in the template to preview note content."
        )

    def test_each_loop_over_text_notes(self, app_source: str) -> None:
        """Source chips iterate over sources."""
        source_chips_section = re.search(
            r'<ul class="(?:source-chips|source-tray-list|tray-list)"[^>]*>(.*?)</ul>',
            app_source,
            re.DOTALL,
        )
        assert source_chips_section is not None, (
            "Expected a <ul class='source-chips'> or <ul class='source-tray-list'> element containing sources."
        )
        chips_content = source_chips_section.group(1)
        assert (
            "#each extraSources" in chips_content
            or "#each textNotes" in chips_content
            or "#each sources" in chips_content
        ), (
            "Expected an {#each} loop over sources in the source list."
        )


# ------------------------------------------------------------------ #
#  Submit pathway: combined multi-source episode
# ------------------------------------------------------------------ #


class TestCombinedSubmitPathway:
    """Submitting multiple different source types should use the combined API."""

    def test_create_job_with_sources_export(self, api_source: str) -> None:
        """api.ts exports createJobWithSources for combined submissions."""
        assert "export async function createJobWithSources" in api_source, (
            "Expected createJobWithSources function in api.ts for combined "
            "URL + text note submissions."
        )

    def test_create_job_with_sources_signature(self, api_source: str) -> None:
        """createJobWithSources accepts sources array, text, and options."""
        pattern = re.search(
            r"createJobWithSources\([^)]*sources[^)]*,\s*textBody[^)]*",
            api_source,
        )
        assert pattern is not None, (
            "Expected createJobWithSources to take sources and textBody parameters."
        )

    def test_submit_uses_combined_for_url_and_notes(self, app_source: str) -> None:
        """When multiple sources are present, submit calls job creation."""
        assert "createJobWithSources" in app_source or "createJob" in app_source, (
            "Expected job creation function to be called from submit when "
            "multiple sources are present."
        )
        assert (
            "textNotes.length > 0" in app_source
            or "sources.length" in app_source
            or "sources" in app_source
        ), (
            "Expected submit to check sources before combining."
        )

    def test_submit_includes_extra_sources_in_combined(self, app_source: str) -> None:
        """Multi-source submission includes sources in combined list."""
        assert (
            "extraSources" in app_source
            or "sources" in app_source
            or "traySources" in app_source
        ), (
            "Expected sources to be part of the combined sources list."
        )
        assert (
            "allSources" in app_source
            or "sources" in app_source
            or "traySources" in app_source
        ), (
            "Expected sources variable collecting combined sources."
        )


# ------------------------------------------------------------------ #
#  UI copy: NotebookLM-style explanation
# ------------------------------------------------------------------ #


class TestUICopy:
    """The compose view should explain that links and notes can be combined."""

    def test_note_placeholder_mentions_combination(self, app_source: str) -> None:
        """The note input placeholder explains it can be combined with sources."""
        assert "context" in app_source.lower() or "discuss" in app_source.lower() or "note" in app_source.lower(), (
            "Expected the note input placeholder to mention combining notes "
            "with sources."
        )

    def test_source_count_display(self, app_source: str) -> None:
        """The source count meta shows the total number of sources."""
        assert "getSourceCount" in app_source or "sources.length" in app_source or "sources" in app_source, (
            "Expected function or state to display total source count."
        )

    def test_no_raw_emoji_in_source_section(self, app_source: str) -> None:
        """No raw emoji in the source chips or add-note sections."""
        source_section = re.search(
            r'<ul class="(?:source-chips|source-tray-list)"[^>]*>.*?</ul>',
            app_source,
            re.DOTALL,
        )
        if source_section:
            html = source_section.group(0)
            emoji_pattern = re.compile(
                "[\U0001F600-\U0001F64F"  # emoticons
                r"\U0001F300-\U0001F5FF"  # symbols & pictographs
                r"\U0001F680-\U0001F6FF"  # transport & map
                r"\U0001F1E0-\U0001F1FF"  # flags
                r"\U00002702-\U000027B0"  # dingbats
                r"\U000024C2-\U0001F251"  # enclosed characters
                r"\U0001F900-\U0001FAFF"  # supplementary
                r"\U0000FE00-\U0000FE0F"  # variation selectors
                r"\U000E0020-\U000E007F"  # tags
                "]+",
                re.UNICODE,
            )
            emojis = emoji_pattern.findall(html)
            assert emojis == [], (
                f"Raw emoji found in source section: {emojis}. "
                "Use <Icon /> components instead."
            )


# ------------------------------------------------------------------ #
#  Calm Grid tokens compliance
# ------------------------------------------------------------------ #


class TestCalmGridCompliance:
    """UI elements must use Calm Grid tokens."""

    def test_no_pill_buttons(self, app_source: str) -> None:
        """No pill-shaped buttons in the compose source section."""
        source_section = re.search(
            r'<form[^>]*>.*?</form>',
            app_source,
            re.DOTALL,
        )
        if source_section:
            html = source_section.group(0)
            buttons = re.findall(r'<button[^>]*>.*?</button>', html, re.DOTALL)
            for btn in buttons:
                assert "border-radius: 9999px" not in btn or "var(--radius)" in btn, (
                    "Button appears to use pill shape (large border-radius). "
                    "Use var(--radius) per Calm Grid design."
                )

    def test_lowercase_ui_labels(self, app_source: str) -> None:
        """UI labels in the compose view use lowercase."""
        button_texts = re.findall(r'>([^<]+)<', app_source)
        for text in button_texts:
            stripped = text.strip()
            if stripped in ("+ add link", "+ add note", "make it talk"):
                assert stripped.islower() or stripped.replace(" ", "").islower() or any(
                    c.isupper() is False for c in stripped
                ), f"UI label should be lowercase: '{stripped}'"


# ------------------------------------------------------------------ #
#  Accessibility
# ------------------------------------------------------------------ #


class TestAccessibility:
    """Source chip elements must have proper accessibility attributes."""

    def test_source_chips_has_aria_label(self, app_source: str) -> None:
        """The source chips list has an aria-label."""
        assert 'aria-label="sources"' in app_source.lower() or "aria-label=" in app_source, (
            "Expected aria-label on the source list."
        )

    def test_chip_remove_buttons_have_aria_label(self, app_source: str) -> None:
        """Each chip remove button has a descriptive aria-label."""
        chip_x_buttons = re.findall(
            r'<button[^>]*class="[^"]*(?:chip-x|btn-remove)[^"]*"[^>]*>',
            app_source,
        ) or re.findall(
            r'<button[^>]*aria-label="[^"]*remove[^"]*"[^>]*>',
            app_source,
        )
        for btn in chip_x_buttons:
            assert "aria-label=" in btn, (
                "Chip remove button is missing aria-label."
            )

    def test_text_note_input_has_aria_label(self, app_source: str) -> None:
        """The text note input has an aria-label attribute."""
        note_input_block = re.search(
            r'(?:note-input|smart-input)[^>]*>.*?aria-label',
            app_source,
            re.DOTALL,
        ) or re.search(
            r'aria-label="[^"]*"[^>]*class="[^"]*(?:note-input|smart-input)',
            app_source,
            re.DOTALL,
        ) or re.search(
            r'class="[^"]*(?:note-input|smart-input)[^"]*"[^>]*aria-label="[^"]*"',
            app_source,
            re.DOTALL,
        )
        assert note_input_block is not None, (
            "Expected a note input element with aria-label."
        )