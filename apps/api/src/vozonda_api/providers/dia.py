"""Dia (Nari Labs 1.6B) TTS provider seam (local GPU, dialogue-native).

Compact dialogue TTS model via Hugging Face transformers. Generates highly
realistic two-speaker dialogue from a transcript using [S1] / [S2] tags with
nonverbal markers. English only.
"""

from __future__ import annotations

from pathlib import Path

from ..config import VOZONDA_ROOT
from ..env import env
from ..plugins.types import Permission, PluginKind, PluginMeta

RENDER_PY = Path(
    env("DIA_PY",
        str(VOZONDA_ROOT / "projects/tts-spike/.venv-dia/bin/python"),
    ),
)
VOICES_DIR = Path(
    env("DIA_VOICES",
        str(VOZONDA_ROOT / "projects/tts-spike/voices/dia"),
    ),
)

SPEAKERS = [
    {"id": "s1", "sample": "s1.wav", "gender": "male", "label": "Speaker 1 (male default)"},
    {"id": "s2", "sample": "s2.wav", "gender": "female", "label": "Speaker 2 (female default)"},
]


def is_installed() -> bool:
    """The renderer python must exist; reference voices are optional (not used yet)."""
    return RENDER_PY.exists()


META = PluginMeta(
    id="dia",
    kind=PluginKind.TTS_ENGINE,
    label="dia (Nari Labs 1.6B, dialogue-native 2 speakers, nonverbal tags, English)",
    permissions=frozenset({Permission.SUBPROCESS, Permission.GPU}),
    renderer="render_dia.py",
    license="Apache-2.0",
    commercial_use=True,
    supports_paralinguistic_tags=True,
    ui_badge="local GPU",
    ui_fix_hint=(
        "set VOZONDA_DIA_PY to a python with `pip install "
        "git+https://github.com/huggingface/transformers.git` "
        f"(e.g. {VOZONDA_ROOT / 'projects/tts-spike/.venv-dia/bin/python'})"
    ),
)