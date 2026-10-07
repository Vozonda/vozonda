"""Higgs Audio v2 (Boson AI) TTS engine provider.

License: the boson-ai/higgs-audio repo ships under the Apache License 2.0
(code).  The model weights on Hugging Face (bosonai/higgs-tts-2-3b-base)
carry "License: other" with no explicit commercial-use grant, so
commercial_use stays False until the model license is clarified.

The engine runs in its own venv (boson_multimodal from the higgs-audio
repo); RENDER_PY points at that interpreter and the renderer re-execs
itself under it when the package is not importable here.
"""

from pathlib import Path

from ..config import VOZONDA_ROOT
from ..env import env
from ..plugins.types import Permission, PluginKind, PluginMeta

META = PluginMeta(
    id="higgs",
    kind=PluginKind.TTS_ENGINE,
    label="higgs (Boson Higgs Audio v2 3B, multi-speaker, expressive)",
    permissions=frozenset({Permission.SUBPROCESS, Permission.GPU}),
    renderer="render_higgs.py",
    license="Apache-2.0",
    commercial_use=False,
    supports_emotion_instructions=True,
    supports_paralinguistic_tags=False,
    ui_badge="local GPU",
    ui_fix_hint=(
        "create a venv with pip install -r requirements.txt from the "
        "higgs-audio repo (boson_multimodal) and set VOZONDA_HIGGS_PY"
    ),
)

RENDER_PY = env("HIGGS_PY",
    str(VOZONDA_ROOT / "projects/tts-spike/.venv-higgs/bin/python"),
)

VOICES_DIR = Path(
    env("HIGGS_VOICES",
        str(VOZONDA_ROOT / "projects/tts-spike/voices/higgs"),
    )
)

# Reference voices the engine clones from; sample paths must resolve
# inside VOICES_DIR (enforced by the renderer).
SPEAKERS = [
    {"id": "belinda", "label": "Belinda (f)", "gender": "f", "sample": "belinda.wav"},
    {"id": "broom_salesman", "label": "Broom Salesman (m)", "gender": "m", "sample": "broom_salesman.wav"},
    {"id": "chadwick", "label": "Chadwick (m)", "gender": "m", "sample": "chadwick.wav"},
    {"id": "en_man", "label": "En Man (m)", "gender": "m", "sample": "en_man.wav"},
    {"id": "en_woman", "label": "En Woman (f)", "gender": "f", "sample": "en_woman.wav"},
    {"id": "mabel", "label": "Mabel (f)", "gender": "f", "sample": "mabel.wav"},
    {"id": "vex", "label": "Vex (f)", "gender": "f", "sample": "vex.wav"},
    {"id": "zh_man_sichuan", "label": "ZH Man Sichuan (m)", "gender": "m", "sample": "zh_man_sichuan.wav"},
]


def is_installed() -> bool:
    """The engine is usable when its venv interpreter exists."""
    return bool(RENDER_PY) and Path(RENDER_PY).exists()
