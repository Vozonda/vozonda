"""UI Spinner & Cancel tests (VOZONDA-UI-CLI-SPINNER-CANCEL).

Text checks only, no browser. Must fail on the current code before fix.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB_SRC = ROOT / "apps" / "web" / "src"
DESIGN = ROOT / "docs" / "design.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pipeline_checklist_no_static_bullet_for_running():
    content = read(WEB_SRC / "lib" / "components" / "PipelineChecklist.svelte")
    # running mark must be empty string
    assert "running: ''" in content or 'running: ""' in content
    # no ● or • for running in mark map
    assert not re.search(r"running\s*:\s*['\"][●•]['\"]", content)


def test_pipeline_checklist_has_braille_frames_in_css():
    content = read(WEB_SRC / "lib" / "components" / "PipelineChecklist.svelte")
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    assert frames in content, "10 braille frames must be present in CSS ::before content"


def test_pipeline_checklist_spinner_uses_css_keyframes_steps():
    content = read(WEB_SRC / "lib" / "components" / "PipelineChecklist.svelte")
    assert "@keyframes braille-spin" in content
    assert "steps(10)" in content


def test_pipeline_checklist_prefers_reduced_motion_rule():
    content = read(WEB_SRC / "lib" / "components" / "PipelineChecklist.svelte")
    assert "@media (prefers-reduced-motion: reduce)" in content
    # static ▸ under reduced motion
    assert re.search(r"\.spinner::before\s*\{[^}]*content\s*:\s*['\"]▸['\"]", content)
    # animation disabled
    assert re.search(r"\.spinner\s*\{[^}]*animation\s*:\s*none", content)


def test_pipeline_checklist_no_js_timer():
    content = read(WEB_SRC / "lib" / "components" / "PipelineChecklist.svelte")
    assert "setInterval" not in content
    assert "setTimeout" not in content


def test_pipeline_checklist_spinner_aria_hidden():
    content = read(WEB_SRC / "lib" / "components" / "PipelineChecklist.svelte")
    assert '<span class="spinner" aria-hidden="true"></span>' in content


def test_queue_indicator_has_cancel_button():
    content = read(WEB_SRC / "lib" / "components" / "QueueIndicator.svelte")
    assert 'class="qi-cancel mono"' in content
    assert "onclick={requestCancel}" in content


def test_queue_indicator_cancel_aria_label_with_title():
    content = read(WEB_SRC / "lib" / "components" / "QueueIndicator.svelte")
    # aria-label with jobTitle interpolation
    assert re.search(r'aria-label=\{`Cancel ".*\$\{jobTitle\}"`\}', content)


def test_queue_indicator_cancel_disabled_while_in_flight():
    content = read(WEB_SRC / "lib" / "components" / "QueueIndicator.svelte")
    assert "disabled={cancelPending}" in content


def test_queue_indicator_inline_confirm_for_running_with_voice_stage():
    content = read(WEB_SRC / "lib" / "components" / "QueueIndicator.svelte")
    assert "cancelConfirm && voiceStageStarted" in content
    assert "cancel render?" in content
    assert "yes" in content and "no" in content


def test_queue_indicator_no_confirm_for_queued():
    content = read(WEB_SRC / "lib" / "components" / "QueueIndicator.svelte")
    assert "isQueued || !voiceStageStarted" in content
    assert "cancelConfirm = false" in content


def test_queue_indicator_calls_on_cancel_callback():
    content = read(WEB_SRC / "lib" / "components" / "QueueIndicator.svelte")
    assert "await onCancel(jobId)" in content


def test_design_md_motion_mentions_braille_spinner():
    content = read(DESIGN)
    assert "CSS-only braille terminal spinner" in content
    assert "decision 2026-10-01" in content
    assert "prefers-reduced-motion" in content
    assert "exception to" in content and "nothing else moves" in content