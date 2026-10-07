"""VibeVoice-1.5B TTS provider seam (local GPU, multi-speaker, voice cloning).

Compact local model via Hugging Face transformers >= 5.17. Uses the chat-template
with voice sample references on each speaker's first turn for multi-speaker audio.
"""

from __future__ import annotations

from pathlib import Path

from ..config import VOZONDA_ROOT
from ..env import env
from ..plugins.types import Permission, PluginKind, PluginMeta

RENDER_PY = Path(
    env("VIBEVOICE_PY",
        str(VOZONDA_ROOT / "projects/tts-spike/.venv-vibevoice/bin/python"),
    ),
)
VOICES_DIR = Path(
    env("VIBEVOICE_VOICES",
        str(VOZONDA_ROOT / "projects/tts-spike/VibeVoice/demo/voices"),
    ),
)

SPEAKERS = [
    {"id": "frank", "sample": "en-Frank_man.wav", "gender": "male", "label": "Frank (male)"},
    {"id": "carter", "sample": "en-Carter_man.wav", "gender": "male", "label": "Carter (male)"},
    {"id": "maya", "sample": "en-Maya_woman.wav", "gender": "female", "label": "Maya (female)"},
    {"id": "alice", "sample": "en-Alice_woman.wav", "gender": "female", "label": "Alice (female)"},
]


def is_installed() -> bool:
    """Return True when both the renderer python and voices directory exist."""
    return RENDER_PY.exists() and VOICES_DIR.is_dir()


META = PluginMeta(
    id="vibevoice",
    kind=PluginKind.TTS_ENGINE,
    label="vibevoice (VibeVoice-1.5B, local GPU, multi-speaker, voice cloning)",
    permissions=frozenset({Permission.SUBPROCESS, Permission.GPU}),
    renderer="render_vibevoice.py",
    license="MIT",
    commercial_use=True,
    ui_badge="local GPU",
    ui_fix_hint=(
        "set VOZONDA_VIBEVOICE_PY to a python with transformers>=5.17 "
        f"(e.g. {VOZONDA_ROOT / 'projects/tts-spike/.venv-vibevoice/bin/python'})"
    ),
)