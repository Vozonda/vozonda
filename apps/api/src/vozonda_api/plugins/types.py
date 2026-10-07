"""Plugin type definitions for vozonda.

Lightweight descriptors that are importable without heavy dependencies.
Every plugin exposes a frozen PluginMeta at module level.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Literal


class PluginKind(enum.Enum):
    """Category of pipeline plugin."""

    INGESTOR = "ingestor"
    SCRIPT_ENGINE = "script_engine"
    TTS_ENGINE = "tts_engine"
    AUDIO_FILTER = "audio_filter"
    DISTRIBUTION = "distribution"


class Permission(enum.Enum):
    """Capability a plugin declares it needs at runtime."""

    NETWORK = "network"
    DISK_READ = "disk_read"
    DISK_WRITE = "disk_write"
    GPU = "gpu"
    SUBPROCESS = "subprocess"


@dataclass(frozen=True)
class PluginParam:
    """Describes a user-tunable parameter the frontend can render.

    The frontend reads these from /meta and generates matching controls
    (sliders, toggles, chip selectors) without plugin-specific Svelte code.
    """

    key: str
    label: str
    kind: Literal["float", "int", "enum", "bool"] = "float"
    default: float | int | str | bool = 0.0
    min_val: float | int | None = None
    max_val: float | int | None = None
    enum_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginMeta:
    """Lightweight descriptor every plugin module exposes as META.

    Must be importable without heavy deps (no torch, no ONNX, etc.).
    """

    id: str
    kind: PluginKind
    label: str
    version: str = "0.1.0"
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    supports_instructions: bool = False
    supports_emotion_instructions: bool = False
    supports_paralinguistic_tags: bool = False
    ui_badge: str = ""
    ui_fix_hint: str = ""
    parameters: tuple[PluginParam, ...] = ()
    # TTS engines: the renderer script next to pipeline.py that voices a script,
    # and the licence of the model weights. commercial_use False blocks the
    # engine while billing is enabled (non-commercial weights).
    renderer: str = ""
    license: str = ""
    commercial_use: bool = True
