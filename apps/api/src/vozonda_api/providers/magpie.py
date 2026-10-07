"""Magpie TTS Multilingual (NVIDIA, hosted on NIM) as a cloud voice engine.

Called over gRPC at grpc.nvcf.nvidia.com with the NVIDIA NIM key that the
kimi_nim script writer uses (providers.nim_api_key). 12 languages, voices
with emotion variants. Tested on 2026-09-25: EN and DE, ~5 s of audio per
0.5 s. The open weights (nvidia/magpie_tts_multilingual_357m, NVIDIA Open
Model License) could later run locally; the hosted API runs on NVIDIA's API
trial terms (testing and prototyping only), hence commercial_use=False, which
blocks the engine when billing is enabled.

Listening test 2026-09-28: the German voices read English words in German
(Jobs, iTunes, Guardian, Podcasting, Player), and a custom_dictionary with
English IPA did not change that. Recommend it for English episodes only.

Rendering happens in render_magpie.py under its own venv (RENDER_PY, like
higgs and dia2): nvidia-riva-client pins older protobuf and websockets than
the API uses, so it stays out of the API's lockfile.
"""

from __future__ import annotations

from pathlib import Path

from ..config import VOZONDA_ROOT
from ..env import env
from ..plugins.types import Permission, PluginKind, PluginMeta
from . import nim_api_key

FUNCTION_ID = "877104f7-e885-42b9-8de8-f6e4c6303969"
SERVER = "grpc.nvcf.nvidia.com:443"

RENDER_PY = env("MAGPIE_PY",
    str(VOZONDA_ROOT / "projects/tts-spike/.venv-magpie/bin/python"),
)

# language prefix -> (Magpie locale, native language as voices.py uses it)
LOCALES = {
    "en": ("EN-US", "English"), "de": ("DE-DE", "German"), "fr": ("FR-FR", "French"),
    "es": ("ES-US", "Spanish"), "it": ("IT-IT", "Italian"), "pt": ("PT-BR", "Portuguese"),
    "zh": ("ZH-CN", "Chinese"), "ja": ("JA-JP", "Japanese"), "ko": ("KO-KR", "Korean"),
    "hi": ("HI-IN", "Hindi"), "ar": ("AR-AR", "Arabic"), "vi": ("VI-VN", "Vietnamese"),
}
# Voices per locale as the hosted service listed them on 2026-09-25
# (GetRivaSynthesisConfig). Gender follows the voice names; confirm by ear.
_VOICES = {
    "en": ["Aria", "Jason", "Leo", "Mia", "Ray", "Sofia"],
    "de": ["Mia", "Leo", "Jason", "Pascal", "Diego", "Ray"],
    "fr": ["Louise", "Pascal"],
    "es": ["Isabela", "Diego"],
    "it": ["Isabela", "Pascal"],
    "pt": ["Isabela", "Diego", "Louise"],
    "zh": ["HouZhen", "Siwei"],
    "ja": ["Isabela", "Louise", "HouZhen", "Ray"],
    "ko": ["Aria", "Louise", "Diego", "HouZhen", "Pascal", "Ray"],
    "hi": ["Sofia", "Leo", "Pascal", "Siwei"],
    "ar": ["Sofia", "Jason", "Ray"],
    "vi": ["Isabela", "Louise", "Jason", "Long", "Pascal", "Siwei"],
}
_FEMALE = {"Aria", "Mia", "Sofia", "Louise", "Isabela"}
_MALE = {"Jason", "Leo", "Ray", "Diego", "Pascal", "Long"}


def _gender(name: str) -> str:
    return "f" if name in _FEMALE else "m" if name in _MALE else ""


SPEAKERS = [
    {
        "id": f"{lang}_{name.lower()}",
        "label": f"{name} ({_gender(name)})" if _gender(name) else name,
        "gender": _gender(name),
        "native": LOCALES[lang][1],
        "magpie": f"Magpie-Multilingual.{LOCALES[lang][0]}.{name}",
        "locale": f"{lang}-{LOCALES[lang][0].split('-')[1]}",
    }
    for lang, names in _VOICES.items()
    for name in names
]


def _client_available() -> bool:
    return Path(RENDER_PY).exists()


def is_installed() -> bool:
    return bool(nim_api_key()) and _client_available()


META = PluginMeta(
    id="magpie",
    kind=PluginKind.TTS_ENGINE,
    label="magpie (NVIDIA NIM, best in English; other voices misread English words)",
    permissions=frozenset({Permission.NETWORK}),
    renderer="render_magpie.py",
    license="NVIDIA API trial terms (hosted, testing only; open weights: NVIDIA Open Model License)",
    commercial_use=False,
    ui_badge="NVIDIA cloud",
    ui_fix_hint=(
        "python -m venv <dir> && <dir>/bin/pip install nvidia-riva-client numpy soundfile httpx, "
        "set VOZONDA_MAGPIE_PY=<dir>/bin/python, and add an NVIDIA NIM key "
        "(settings llm.nim_api_key, VOZONDA_NIM_API_KEY or secrets/nvidia_nim_api.key)"
    ),
)
