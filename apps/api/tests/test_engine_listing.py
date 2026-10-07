"""Engine listing exposes license and commercial_use for every TTS engine.

GET /providers and _probe_installed_engines must include license and
commercial_use so the UI can show a non-commercial marker and disabled
state for not-installed engines.
"""

from fastapi.testclient import TestClient

from vozonda_api import providers
from vozonda_api.main import app


def test_probe_engines_have_license_and_commercial_use():
    listing = providers._probe_installed_engines()
    #filter to TTS: exclude the LLM entry if present (local, alias qwen_vllm)
    tts = [e for e in listing if e["id"] not in ("qwen_vllm", "local")]
    assert tts, "no TTS engines in probe listing"
    for eng in tts:
        assert "license" in eng, f"missing license for {eng['id']}"
        assert "commercial_use" in eng, f"missing commercial_use for {eng['id']}"
        assert isinstance(eng["license"], str) and eng["license"].strip(), f"empty license for {eng['id']}"
        assert isinstance(eng["commercial_use"], bool), f"commercial_use not bool for {eng['id']}"
        #also ensure ui_badge and installed are present for UI rendering
        assert "ui_badge" in eng, f"missing ui_badge for {eng['id']}"
        assert "installed" in eng, f"missing installed for {eng['id']}"
        assert "fix" in eng or "ui_fix_hint" in eng, f"missing fix hint for {eng['id']}"


def test_probe_listing_covers_discovered_tts_engines():
    metas = providers.tts_engines(refresh=True)
    listing = {e["id"]: e for e in providers._probe_installed_engines()}
    for eid, meta in metas.items():
        assert eid in listing, f"discovered engine {eid} missing from probe listing"
        entry = listing[eid]
        assert entry["license"] == meta.license
        assert entry["commercial_use"] == meta.commercial_use
        assert entry["ui_badge"] == meta.ui_badge


def test_providers_endpoint_returns_license_fields():
    client = TestClient(app)
    resp = client.get("/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    tts = [p for p in data["providers"] if p["id"] not in ("qwen_vllm", "local")]
    assert tts, "providers endpoint returned no TTS engines"
    for eng in tts:
        assert "license" in eng, f"missing license in /providers for {eng['id']}"
        assert "commercial_use" in eng, f"missing commercial_use in /providers for {eng['id']}"
        assert isinstance(eng["license"], str) and eng["license"].strip()
        assert isinstance(eng["commercial_use"], bool)


def test_non_commercial_marker_present_when_commercial_use_false(monkeypatch):
    #use the fake_engine fixture idea: ensure non-commercial logic still gates
    import sys
    import types

    from vozonda_api.plugins import registry
    from vozonda_api.plugins.types import PluginKind, PluginMeta

    mod = types.ModuleType("vozonda_api.providers.fake_nc_listing")
    mod.META = PluginMeta(
        id="fake_nc_listing",
        kind=PluginKind.TTS_ENGINE,
        label="fake nc (test)",
        renderer="render_fake_nc.py",
        license="CC-BY-NC-4.0",
        commercial_use=False,
        ui_badge="test",
        ui_fix_hint="install fake",
    )
    mod.is_installed = lambda: True
    sys.modules[mod.__name__] = mod
    registry.register(mod)
    providers.tts_engines(refresh=True)
    try:
        listing = {e["id"]: e for e in providers._probe_installed_engines()}
        assert "fake_nc_listing" in listing
        entry = listing["fake_nc_listing"]
        assert entry["commercial_use"] is False
        assert "non-commercial" in entry["license"].lower() or entry["commercial_use"] is False
        assert entry["license"] == "CC-BY-NC-4.0"
    finally:
        registry._plugins.pop("fake_nc_listing", None)
        if "fake_nc_listing" in registry._order.get(PluginKind.TTS_ENGINE, []):
            registry._order[PluginKind.TTS_ENGINE].remove("fake_nc_listing")
        sys.modules.pop(mod.__name__, None)
        providers.tts_engines(refresh=True)
