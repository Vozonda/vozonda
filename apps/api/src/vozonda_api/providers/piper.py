"""Piper VITS ONNX TTS provider metadata.

Piper runs 100% on CPU via the piper-tts Python package.
Rendering is handled by render_piper.py subprocess; this module
exposes only the META descriptor for registry discovery and the
speaker table accessor.
"""

from __future__ import annotations

from ..plugins.types import Permission, PluginKind, PluginMeta
from ..voices import PIPER_SPEAKERS

META = PluginMeta(
    id="piper",
    kind=PluginKind.TTS_ENGINE,
    label="piper (CPU, multi-lingual open source)",
    permissions=frozenset({Permission.SUBPROCESS}),
    supports_instructions=False,
    supports_emotion_instructions=False,
    supports_paralinguistic_tags=False,
    ui_badge="local CPU",
    ui_fix_hint="uv sync --extra tts-piper",
    renderer="render_piper.py",
    license="MIT (voice models vary)",
)

PIPER_VOICE_IDS = {s["id"] for s in PIPER_SPEAKERS}
