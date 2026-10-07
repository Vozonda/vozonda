"""Deterministic, capability-gated plugin registry.

Discovery: scans the providers/ package for modules exposing META.
Registration: validates META presence at register time.
Resolution: returns ordered plugin chains per PluginKind.
Lifecycle: lazy-load probes, graceful degradation on broken modules.
Toggle: dynamic enabled states persisted to data/config.json.
"""

from __future__ import annotations

import importlib
import json
import logging
import pkgutil
from pathlib import Path

from .protocols import HasMeta
from .types import PluginKind, PluginMeta

logger = logging.getLogger("vozonda.plugins")


def _default_config_path() -> Path:
    """Resolve the canonical config.json path.

    Spec requires data/config.json at repo root. Falls back to
    apps/data if repo data cannot be created.
    """
    here = Path(__file__).resolve()
    repo_data = here.parents[5] / "data" / "config.json"
    # Try repo root first; _save_config will create the parent dir.
    try:
        # If the repo data parent is writable or already exists, use it.
        # Existence check is best effort; _save_config handles creation.
        if repo_data.parent.exists() or repo_data.parent.parent.exists():
            return repo_data
    except Exception:
        logger.debug("repo config path check failed", exc_info=True)
    # Fallback to apps/data for environments where repo root is read-only
    fallback = here.parents[4] / "data" / "config.json"
    try:
        if fallback.parent.exists():
            return fallback
    except Exception:
        logger.debug("fallback config path check failed", exc_info=True)
    return repo_data


class PluginRegistry:
    """Central registry for all vozonda pipeline plugins.

    Plugins are discovered by scanning a Python package for modules
    that expose a module-level ``META`` attribute of type PluginMeta.
    Enabled states are persisted to data/config.json.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._plugins: dict[str, HasMeta] = {}
        self._order: dict[PluginKind, list[str]] = {
            k: [] for k in PluginKind
        }
        self._probe_cache: dict[str, tuple[float, bool]] = {}
        self._probe_ttl: float = 120.0
        self._config_path: Path = config_path or _default_config_path()
        self._enabled: dict[str, bool] = {}
        self._load_config()

    # -- Registration --

    def register(self, plugin: HasMeta) -> None:
        """Register a plugin. Validates META presence and type."""
        meta = plugin.META
        if not isinstance(meta, PluginMeta):
            logger.warning(
                "plugin META is not a PluginMeta instance, skipping: %r",
                meta,
            )
            return
        if meta.id in self._plugins:
            logger.debug("plugin %s already registered, skipping", meta.id)
            return
        self._plugins[meta.id] = plugin
        self._order[meta.kind].append(meta.id)
        logger.info("registered plugin: %s (%s)", meta.id, meta.kind.value)

    # -- Discovery --

    def discover(self, package: str = "vozonda_api.providers") -> int:
        """Import all submodules of *package* that expose META.

        Returns the number of plugins successfully registered.
        """
        try:
            pkg = importlib.import_module(package)
        except ImportError:
            logger.exception("cannot import provider package %s", package)
            return 0

        pkg_path = getattr(pkg, "__path__", None)
        if pkg_path is None:
            return 0

        count = 0
        for _importer, name, _is_pkg in pkgutil.iter_modules(pkg_path):
            if name.startswith("_"):
                continue
            fqn = f"{package}.{name}"
            try:
                mod = importlib.import_module(fqn)
            except Exception:
                logger.exception("failed to import provider module %s", fqn)
                continue
            meta = getattr(mod, "META", None)
            if meta is not None and isinstance(meta, PluginMeta):
                self.register(mod)  # type: ignore[arg-type]
                count += 1
        return count

    # -- Resolution --

    def get(self, plugin_id: str) -> HasMeta:
        """Get a registered plugin by ID. Raises KeyError if missing."""
        return self._plugins[plugin_id]

    def chain(self, kind: PluginKind) -> list[HasMeta]:
        """Return ordered plugin chain for a given kind."""
        return [
            self._plugins[pid]
            for pid in self._order[kind]
            if pid in self._plugins
        ]

    def ids(self, kind: PluginKind | None = None) -> list[str]:
        """Return registered plugin IDs, optionally filtered by kind."""
        if kind is None:
            return list(self._plugins.keys())
        return list(self._order[kind])

    def all_meta(self, kind: PluginKind | None = None) -> list[PluginMeta]:
        """Return metadata for all (or filtered) plugins. UI-safe."""
        if kind is None:
            return [p.META for p in self._plugins.values()]
        return [
            self._plugins[pid].META
            for pid in self._order[kind]
            if pid in self._plugins
        ]

    def has(self, plugin_id: str) -> bool:
        """Check whether a plugin ID is registered."""
        return plugin_id in self._plugins

    # -- Health --

    async def probe(self, plugin_id: str) -> bool:
        """Cached health probe with TTL."""
        import asyncio

        now = asyncio.get_event_loop().time()
        cached = self._probe_cache.get(plugin_id)
        if cached and now - cached[0] < self._probe_ttl:
            return cached[1]
        plugin = self._plugins.get(plugin_id)
        if plugin is None:
            return False
        probe_fn = getattr(plugin, "probe", None)
        if probe_fn is None or not callable(probe_fn):
            return True  # no probe means always healthy
        try:
            result: bool = await probe_fn()
        except Exception:
            logger.exception("probe failed for plugin %s", plugin_id)
            result = False
        self._probe_cache[plugin_id] = (now, result)
        return result

    async def doctor(self) -> list[dict[str, str | bool]]:
        """Run probe on all plugins. Returns list suitable for /doctor."""
        results: list[dict[str, str | bool]] = []
        for pid, plugin in self._plugins.items():
            ok = await self.probe(pid)
            results.append({
                "id": pid,
                "ok": ok,
                "kind": plugin.META.kind.value,
                "label": plugin.META.label,
                "hint": plugin.META.ui_fix_hint if not ok else "",
            })
        return results

    def clear_cache(self) -> None:
        """Invalidate all probe caches (e.g. after engine switch)."""
        self._probe_cache.clear()

    # -- Enabled toggle persistence --

    def _load_config(self) -> None:
        """Load enabled map from config file. Missing or invalid file means all enabled."""
        try:
            path = self._config_path
            if not path.exists():
                # Try legacy fallback at apps/data/config.json
                fallback = Path(__file__).resolve().parents[4] / "data" / "config.json"
                if fallback != path and fallback.exists():
                    path = fallback
                    self._config_path = fallback
                else:
                    self._enabled = {}
                    return
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
            plugins_cfg = data.get("plugins", {}) if isinstance(data, dict) else {}
            if isinstance(plugins_cfg, dict):
                self._enabled = {
                    str(k): bool(v) for k, v in plugins_cfg.items()
                }
            else:
                self._enabled = {}
        except Exception:
            logger.exception("failed to load plugin config %s", self._config_path)
            self._enabled = {}

    def _save_config(self) -> None:
        """Persist enabled map atomically."""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            existing: dict[str, object] = {}
            if self._config_path.exists():
                try:
                    raw = self._config_path.read_text(encoding="utf-8")
                    parsed = json.loads(raw) if raw.strip() else {}
                    if isinstance(parsed, dict):
                        existing = parsed
                except Exception:
                    existing = {}
            existing["plugins"] = dict(self._enabled)
            tmp = self._config_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
            tmp.replace(self._config_path)
        except Exception:
            logger.exception("failed to save plugin config %s", self._config_path)

    def is_enabled(self, plugin_id: str) -> bool:
        """Return enabled state. Unknown ids default to True, unregistered returns False."""
        if plugin_id not in self._plugins:
            return False
        return self._enabled.get(plugin_id, True)

    def set_enabled(self, plugin_id: str, enabled: bool) -> bool:
        """Set enabled state and persist. Raises KeyError if plugin unknown."""
        if plugin_id not in self._plugins:
            raise KeyError(plugin_id)
        self._enabled[plugin_id] = bool(enabled)
        self._save_config()
        self._probe_cache.pop(plugin_id, None)
        return self._enabled[plugin_id]

    def toggle(self, plugin_id: str) -> bool:
        """Flip enabled state and persist. Raises KeyError if unknown."""
        cur = self.is_enabled(plugin_id)
        if plugin_id not in self._plugins:
            raise KeyError(plugin_id)
        return self.set_enabled(plugin_id, not cur)

    def enabled_ids(self, kind: PluginKind | None = None) -> list[str]:
        """Return IDs of enabled plugins, optionally filtered by kind."""
        ids = self.ids(kind)
        return [pid for pid in ids if self.is_enabled(pid)]

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, plugin_id: str) -> bool:
        return plugin_id in self._plugins
