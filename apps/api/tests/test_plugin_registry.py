"""Tests for the plugin registry and type system.

Validates:
- PluginMeta and PluginKind construction
- Registry discovery, registration, and resolution
- META constants on all provider modules import without heavy deps
- No torch/kokoro/qwen_tts in sys.modules after META import
"""

from __future__ import annotations

import sys

import pytest

from vozonda_api.plugins import PluginKind, PluginMeta, Permission, PluginRegistry, registry


# ---- Type construction ----


def test_plugin_meta_frozen():
    meta = PluginMeta(
        id="test",
        kind=PluginKind.TTS_ENGINE,
        label="Test Engine",
    )
    assert meta.id == "test"
    assert meta.kind == PluginKind.TTS_ENGINE
    with pytest.raises(AttributeError):
        meta.id = "changed"  # type: ignore[misc]


def test_plugin_meta_defaults():
    meta = PluginMeta(id="x", kind=PluginKind.AUDIO_FILTER, label="X")
    assert meta.version == "0.1.0"
    assert meta.permissions == frozenset()
    assert meta.supports_instructions is False
    assert meta.supports_emotion_instructions is False
    assert meta.supports_paralinguistic_tags is False
    assert meta.ui_badge == ""
    assert meta.ui_fix_hint == ""
    assert meta.parameters == ()


def test_plugin_kind_values():
    assert PluginKind.INGESTOR.value == "ingestor"
    assert PluginKind.SCRIPT_ENGINE.value == "script_engine"
    assert PluginKind.TTS_ENGINE.value == "tts_engine"
    assert PluginKind.AUDIO_FILTER.value == "audio_filter"
    assert PluginKind.DISTRIBUTION.value == "distribution"


def test_permission_values():
    assert Permission.NETWORK.value == "network"
    assert Permission.GPU.value == "gpu"
    assert Permission.SUBPROCESS.value == "subprocess"


def test_plugin_meta_with_permissions():
    meta = PluginMeta(
        id="gpu_engine",
        kind=PluginKind.TTS_ENGINE,
        label="GPU Engine",
        permissions=frozenset({Permission.GPU, Permission.SUBPROCESS}),
    )
    assert Permission.GPU in meta.permissions
    assert Permission.SUBPROCESS in meta.permissions
    assert Permission.NETWORK not in meta.permissions


# ---- Registry lifecycle ----


class _FakeMeta:
    """A module-like object with META for testing registration."""

    def __init__(self, meta: PluginMeta) -> None:
        self.META = meta


def test_registry_register_and_get():
    reg = PluginRegistry()
    meta = PluginMeta(id="test_a", kind=PluginKind.TTS_ENGINE, label="A")
    fake = _FakeMeta(meta)
    reg.register(fake)  # type: ignore[arg-type]
    assert reg.has("test_a")
    assert reg.get("test_a").META.id == "test_a"


def test_registry_duplicate_skip():
    reg = PluginRegistry()
    meta = PluginMeta(id="dup", kind=PluginKind.TTS_ENGINE, label="Dup")
    reg.register(_FakeMeta(meta))  # type: ignore[arg-type]
    reg.register(_FakeMeta(meta))  # type: ignore[arg-type]
    assert len(reg.chain(PluginKind.TTS_ENGINE)) == 1


def test_registry_chain_ordering():
    reg = PluginRegistry()
    for i in range(3):
        meta = PluginMeta(
            id=f"tts_{i}", kind=PluginKind.TTS_ENGINE, label=f"TTS {i}"
        )
        reg.register(_FakeMeta(meta))  # type: ignore[arg-type]
    chain = reg.chain(PluginKind.TTS_ENGINE)
    assert [p.META.id for p in chain] == ["tts_0", "tts_1", "tts_2"]


def test_registry_all_meta_filtered():
    reg = PluginRegistry()
    reg.register(  # type: ignore[arg-type]
        _FakeMeta(PluginMeta(id="t1", kind=PluginKind.TTS_ENGINE, label="T1"))
    )
    reg.register(  # type: ignore[arg-type]
        _FakeMeta(PluginMeta(id="s1", kind=PluginKind.SCRIPT_ENGINE, label="S1"))
    )
    tts_metas = reg.all_meta(PluginKind.TTS_ENGINE)
    assert len(tts_metas) == 1
    assert tts_metas[0].id == "t1"

    all_metas = reg.all_meta()
    assert len(all_metas) == 2


def test_registry_ids():
    reg = PluginRegistry()
    reg.register(  # type: ignore[arg-type]
        _FakeMeta(PluginMeta(id="a", kind=PluginKind.TTS_ENGINE, label="A"))
    )
    reg.register(  # type: ignore[arg-type]
        _FakeMeta(PluginMeta(id="b", kind=PluginKind.SCRIPT_ENGINE, label="B"))
    )
    assert reg.ids() == ["a", "b"]
    assert reg.ids(PluginKind.TTS_ENGINE) == ["a"]
    assert reg.ids(PluginKind.AUDIO_FILTER) == []


def test_registry_get_missing_raises():
    reg = PluginRegistry()
    with pytest.raises(KeyError):
        reg.get("nonexistent")


def test_registry_contains():
    reg = PluginRegistry()
    reg.register(  # type: ignore[arg-type]
        _FakeMeta(PluginMeta(id="yes", kind=PluginKind.TTS_ENGINE, label="Y"))
    )
    assert "yes" in reg
    assert "no" not in reg


def test_registry_len():
    reg = PluginRegistry()
    assert len(reg) == 0
    reg.register(  # type: ignore[arg-type]
        _FakeMeta(PluginMeta(id="one", kind=PluginKind.TTS_ENGINE, label="1"))
    )
    assert len(reg) == 1


# ---- Discovery ----


def test_discover_finds_provider_modules():
    """discover() should find META in all provider modules."""
    reg = PluginRegistry()
    count = reg.discover("vozonda_api.providers")
    # kokoro, qwen, nemo, script, piper, voxtral = 6 modules with META
    assert count >= 6, f"expected >= 6 plugins, found {count}: {reg.ids()}"
    # verify specific known plugins
    assert reg.has("kokoro")
    assert reg.has("qwen_tts")
    assert reg.has("nemo")
    assert reg.has("script_llm")
    assert reg.has("piper")
    assert reg.has("voxtral")


def test_discover_categorizes_by_kind():
    reg = PluginRegistry()
    reg.discover("vozonda_api.providers")
    tts = reg.ids(PluginKind.TTS_ENGINE)
    assert "kokoro" in tts
    assert "qwen_tts" in tts
    assert "piper" in tts
    assert "voxtral" in tts
    assert "nemo" in tts

    scripts = reg.ids(PluginKind.SCRIPT_ENGINE)
    assert "script_llm" in scripts


def test_discover_meta_attributes():
    """All discovered plugins should have valid META fields."""
    reg = PluginRegistry()
    reg.discover("vozonda_api.providers")
    for meta in reg.all_meta():
        assert isinstance(meta.id, str) and meta.id
        assert isinstance(meta.kind, PluginKind)
        assert isinstance(meta.label, str) and meta.label
        assert isinstance(meta.permissions, frozenset)


def test_kokoro_meta_matches_capabilities():
    """Kokoro META should match the existing PROVIDER_CAPABILITIES."""
    reg = PluginRegistry()
    reg.discover("vozonda_api.providers")
    meta = reg.get("kokoro").META
    assert meta.supports_instructions is False
    assert meta.supports_emotion_instructions is False
    assert meta.supports_paralinguistic_tags is False
    assert Permission.SUBPROCESS in meta.permissions


def test_qwen_meta_matches_capabilities():
    """Qwen META should match the existing PROVIDER_CAPABILITIES."""
    reg = PluginRegistry()
    reg.discover("vozonda_api.providers")
    meta = reg.get("qwen_tts").META
    assert meta.supports_instructions is True
    assert meta.supports_emotion_instructions is True
    assert meta.supports_paralinguistic_tags is False
    assert Permission.GPU in meta.permissions


def test_voxtral_meta_matches_capabilities():
    """Voxtral META should match the existing PROVIDER_CAPABILITIES."""
    reg = PluginRegistry()
    reg.discover("vozonda_api.providers")
    meta = reg.get("voxtral").META
    assert meta.supports_instructions is True
    assert meta.supports_emotion_instructions is True
    assert meta.supports_paralinguistic_tags is True
    assert Permission.NETWORK in meta.permissions


def test_piper_meta_matches_capabilities():
    """Piper META should match the existing PROVIDER_CAPABILITIES."""
    reg = PluginRegistry()
    reg.discover("vozonda_api.providers")
    meta = reg.get("piper").META
    assert meta.supports_instructions is False
    assert meta.supports_emotion_instructions is False
    assert meta.supports_paralinguistic_tags is False


def test_script_meta_has_network_permission():
    reg = PluginRegistry()
    reg.discover("vozonda_api.providers")
    meta = reg.get("script_llm").META
    assert meta.kind == PluginKind.SCRIPT_ENGINE
    assert Permission.NETWORK in meta.permissions


# ---- Heavy import guard ----


def test_no_heavy_imports_from_meta():
    """Importing provider modules for META must not pull in torch or ML libs.

    This is the fundamental lazy-loading invariant: the API process can
    list voices and capabilities without loading GPU libraries.
    """
    heavy_modules = {"torch", "kokoro", "qwen_tts", "piper", "nemo"}
    # Clear any cached imports (in case a previous test loaded them)
    before = {m for m in heavy_modules if m in sys.modules}
    # Force fresh import of all provider modules
    import importlib

    for name in ("kokoro", "qwen", "nemo", "script", "piper", "voxtral"):
        mod = importlib.import_module(f"vozonda_api.providers.{name}")
        assert hasattr(mod, "META"), f"{name} missing META"
    # Check no heavy modules were imported
    after = {m for m in heavy_modules if m in sys.modules}
    newly_imported = after - before
    assert not newly_imported, (
        f"importing provider META pulled in heavy modules: {newly_imported}"
    )


# ---- Singleton ----


def test_module_singleton_is_empty_before_discover():
    """The module-level registry singleton starts empty."""
    fresh = PluginRegistry()
    assert len(fresh) == 0


def test_discover_on_nonexistent_package():
    reg = PluginRegistry()
    count = reg.discover("nonexistent.package.path")
    assert count == 0
    assert len(reg) == 0


# ---- Probe cache ----


@pytest.mark.asyncio
async def test_probe_cache_and_clear():
    reg = PluginRegistry()
    meta = PluginMeta(id="probeable", kind=PluginKind.TTS_ENGINE, label="P")

    class _Probeable:
        META = meta
        _calls = 0

        async def probe(self) -> bool:
            self._calls += 1
            return True

    p = _Probeable()
    reg.register(p)  # type: ignore[arg-type]
    assert await reg.probe("probeable") is True
    assert p._calls == 1
    # second call should hit cache
    assert await reg.probe("probeable") is True
    assert p._calls == 1
    # clear cache and probe again
    reg.clear_cache()
    assert await reg.probe("probeable") is True
    assert p._calls == 2


@pytest.mark.asyncio
async def test_probe_missing_plugin():
    reg = PluginRegistry()
    assert await reg.probe("missing") is False


@pytest.mark.asyncio
async def test_doctor_returns_all_plugins():
    reg = PluginRegistry()
    reg.register(  # type: ignore[arg-type]
        _FakeMeta(PluginMeta(id="d1", kind=PluginKind.TTS_ENGINE, label="D1"))
    )
    reg.register(  # type: ignore[arg-type]
        _FakeMeta(PluginMeta(id="d2", kind=PluginKind.SCRIPT_ENGINE, label="D2"))
    )
    results = await reg.doctor()
    assert len(results) == 2
    ids = {r["id"] for r in results}
    assert ids == {"d1", "d2"}
    # _FakeMeta has no probe method, so all should be healthy
    assert all(r["ok"] for r in results)
