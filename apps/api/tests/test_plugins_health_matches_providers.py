"""/plugins must not call an engine healthy that /providers reports as not installed.

2026-09-25: the plugins drawer showed chatterbox and higgs as enabled and
healthy although neither venv existed; the registry treats a plugin without a
probe() as always healthy, and those providers only define is_installed().
"""

from fastapi.testclient import TestClient

from vozonda_api import main


def test_plugin_health_of_tts_engines_follows_providers(monkeypatch):
    from vozonda_api import providers

    def fake_installed():
        return [{"id": "higgs", "installed": False}, {"id": "piper", "installed": True}]

    monkeypatch.setattr(providers, "_probe_installed_engines", fake_installed)
    body = TestClient(main.app).get("/plugins").json()["plugins"]
    by_id = {p["id"]: p for p in body}
    assert by_id["higgs"]["healthy"] is False
    assert by_id["piper"]["healthy"] is True


def test_tts_plugin_without_a_renderer_is_not_healthy():
    """2026-09-28: nemo (FastPitch stub, no renderer) showed healthy in the drawer
    but never appeared in the voice engine list, because it cannot render."""
    by_id = {p["id"]: p for p in TestClient(main.app).get("/plugins").json()["plugins"]}
    assert by_id["nemo"]["healthy"] is False
    assert "renderer" in by_id["nemo"]["ui_fix_hint"]
