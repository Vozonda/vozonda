"""Vozonda plugin system.

Provides typed Protocol interfaces, a deterministic registry, and
module-level singleton for pipeline plugin discovery and dispatch.

Usage::

    from vozonda_api.plugins import registry
    registry.discover()                       # scan providers/ for META
    tts_metas = registry.all_meta(PluginKind.TTS_ENGINE)
"""

from .registry import PluginRegistry
from .types import Permission, PluginKind, PluginMeta, PluginParam

registry = PluginRegistry()

__all__ = [
    "Permission",
    "PluginKind",
    "PluginMeta",
    "PluginParam",
    "PluginRegistry",
    "registry",
]
