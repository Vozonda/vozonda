"""Voxtral (Mistral EU cloud) TTS provider metadata.

Voxtral is a multimodal voice foundation model hosted in the EU (Paris)
via Mistral API. Rendering is handled by render_voxtral.py subprocess;
this module exposes only the META descriptor for registry discovery and
the speaker table accessor.
"""

from __future__ import annotations

from ..config import VOZONDA_SECRETS_DIR
from ..plugins.types import Permission, PluginKind, PluginMeta
from ..voices import VOXTRAL_SPEAKERS

META = PluginMeta(
    id="voxtral",
    kind=PluginKind.TTS_ENGINE,
    label="voxtral (Mistral EU, 30+ European voices, emotion tags)",
    permissions=frozenset({Permission.NETWORK}),
    supports_instructions=True,
    supports_emotion_instructions=True,
    supports_paralinguistic_tags=True,
    ui_badge="EU cloud",
    ui_fix_hint=f"echo 'your_key' > {VOZONDA_SECRETS_DIR / 'mistral_api.key'}",
    renderer="render_voxtral.py",
    license="Mistral API terms (hosted; the open 4B weights are CC BY-NC 4.0)",
)

VOXTRAL_VOICE_IDS = {s["id"] for s in VOXTRAL_SPEAKERS}
