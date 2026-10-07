"""Chatterbox (Resemble AI) TTS engine provider.

Self-contained: the plugin registry discovers this module via META, the
pipeline reads renderer/interpreter from here, and the renderer script
(render_chatterbox.py) does the actual synthesis. MIT licensed, commercial
use allowed (see repo LICENSE and the upstream project).
"""

from pathlib import Path

from ..config import VOZONDA_ROOT
from ..env import env
from ..plugins.types import Permission, PluginKind, PluginMeta

META = PluginMeta(
    id="chatterbox",
    kind=PluginKind.TTS_ENGINE,
    label="chatterbox (Resemble, MIT, emotion exaggeration, voice cloning, 23 languages)",
    permissions=frozenset({Permission.SUBPROCESS, Permission.GPU}),
    renderer="render_chatterbox.py",
    license="MIT",
    commercial_use=True,
    supports_emotion_instructions=True,
    supports_paralinguistic_tags=False,
    ui_badge="local GPU",
    ui_fix_hint="create a venv with pip install chatterbox-tts and set VOZONDA_CHATTERBOX_PY",
)

RENDER_PY = env("CHATTERBOX_PY",
    str(VOZONDA_ROOT / "projects/tts-spike/.venv-chatterbox/bin/python"),
)

VOICES_DIR = Path(
    env("CHATTERBOX_VOICES",
        str(VOZONDA_ROOT / "projects/tts-spike/voices/chatterbox"),
    )
)

# Chatterbox clones from a short reference WAV per voice; `sample` is the
# file inside VOICES_DIR the engine conditions on.
SPEAKERS = [
    {"id": "cb_host_m", "label": "Host (m)", "gender": "m", "native": "English", "sample": "host_m.wav"},
    {"id": "cb_host_f", "label": "Host (f)", "gender": "f", "native": "English", "sample": "host_f.wav"},
    {"id": "cb_expert_m", "label": "Expert (m)", "gender": "m", "native": "English", "sample": "expert_m.wav"},
    {"id": "cb_expert_f", "label": "Expert (f)", "gender": "f", "native": "English", "sample": "expert_f.wav"},
    {"id": "cb_narrator", "label": "Narrator (f)", "gender": "f", "native": "English", "sample": "narrator.wav"},
]


def is_installed() -> bool:
    """Interpreter must exist; the voices dir must exist with at least one WAV."""
    if not Path(RENDER_PY).exists():
        return False
    if not VOICES_DIR.is_dir():
        return False
    return any(VOICES_DIR.glob("*.wav"))
