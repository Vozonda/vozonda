"""TTS engines come from the plugin registry, not from hardcoded lists.

Adding an engine must need only a provider module (META with a renderer) plus
its renderer script: no edit in settings_store.py, voices.py, providers or
pipeline.py. Engines whose weights forbid commercial use are blocked while
billing is on.
"""

import sys
import types

import pytest

from vozonda_api import providers, settings_store, voices
from vozonda_api.plugins import registry
from vozonda_api.plugins.types import PluginKind, PluginMeta


@pytest.fixture
def fake_engine():
    """Register a provider module at runtime, like a newly added engine file."""
    mod = types.ModuleType("vozonda_api.providers.fake_engine")
    mod.META = PluginMeta(id="fake_engine", kind=PluginKind.TTS_ENGINE,
                          label="fake (test)", renderer="render_fake.py",
                          license="CC-BY-NC-4.0", commercial_use=False)
    mod.SPEAKERS = [{"id": "fake_v1", "label": "Fake (f)", "native": "English"}]
    mod.RENDER_PY = "/usr/bin/python3"
    sys.modules[mod.__name__] = mod
    registry.register(mod)
    providers.tts_engines(refresh=True)
    yield mod
    registry._plugins.pop("fake_engine", None)
    registry._order[PluginKind.TTS_ENGINE].remove("fake_engine")
    sys.modules.pop(mod.__name__, None)
    providers.tts_engines(refresh=True)


def test_shipped_engines_are_discovered_with_their_renderers():
    engines = providers.tts_engines(refresh=True)
    assert {"qwen_tts", "voxtral", "piper", "kokoro"} <= set(engines)
    assert engines["kokoro"].renderer == "render_kokoro.py"
    assert all(m.license for m in engines.values())


def test_a_new_provider_module_is_selectable_without_touching_shared_files(fake_engine, monkeypatch):
    monkeypatch.delenv("VOZONDA_ENABLE_BILLING", raising=False)
    assert "fake_engine" in providers.engine_ids()
    assert settings_store._validate("tts.engine", "fake_engine") == "fake_engine"
    assert voices.speakers_for("fake_engine")[0]["id"] == "fake_v1"
    assert voices.normalize_voice({"engine": "fake_engine"})["engine"] == "fake_engine"
    assert "fake_engine" in voices.all_speaker_tables()


def test_non_commercial_engine_is_blocked_only_while_billing_is_enabled(fake_engine, monkeypatch):
    monkeypatch.delenv("VOZONDA_ENABLE_BILLING", raising=False)
    assert providers.engine_blocked_reason("fake_engine") is None
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
    reason = providers.engine_blocked_reason("fake_engine")
    assert reason and "non-commercial" in reason
    with pytest.raises(ValueError):
        settings_store._validate("tts.engine", "fake_engine")
    assert providers.engine_blocked_reason("kokoro") is None      # Apache-2.0 stays usable
    listing = {e["id"]: e for e in providers._probe_installed_engines()}
    assert listing["fake_engine"]["installed"] is False and "non-commercial" in listing["fake_engine"]["fix"]


def test_unknown_engine_is_still_rejected():
    with pytest.raises(ValueError):
        settings_store._validate("tts.engine", "not_an_engine")
