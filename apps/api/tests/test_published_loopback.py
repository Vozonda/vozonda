"""Docker quickstart: 0.0.0.0 inside the container, published on host loopback only."""

from vozonda_api import doctor
from vozonda_api import main


def test_container_bind_needs_a_token_unless_published_on_loopback(monkeypatch):
    monkeypatch.delenv("VOZONDA_ENABLE_BILLING", raising=False)
    monkeypatch.setenv("VOZONDA_HOST", "0.0.0.0")
    monkeypatch.delenv("VOZONDA_PUBLISHED_ON", raising=False)
    assert main._write_auth_required() is True
    monkeypatch.setenv("VOZONDA_PUBLISHED_ON", "loopback")
    assert main._write_auth_required() is False


def test_billing_still_needs_a_token_on_loopback(monkeypatch):
    monkeypatch.setenv("VOZONDA_HOST", "0.0.0.0")
    monkeypatch.setenv("VOZONDA_PUBLISHED_ON", "loopback")
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
    assert main._write_auth_required() is True


def test_missing_optional_engine_does_not_fail_the_doctor(monkeypatch):
    core = ["_llm_ok", "_tts_python_ok", "_tts_renderable", "_ffmpeg_ok", "_media_writable", "_model_cache_hint"]
    for fn in core:
        monkeypatch.setattr(doctor, fn, lambda: (True, ""))
    import vozonda_api.providers as providers
    monkeypatch.setattr(providers, "_probe_installed_engines",
                        lambda: [{"id": "piper", "label": "piper", "installed": True, "fix": ""},
                                 {"id": "dia", "label": "dia", "installed": False, "fix": "x"}])
    out = doctor.run_doctor()
    assert out["ok"] is True
    monkeypatch.setattr(doctor, "_ffmpeg_ok", lambda: (False, "no ffmpeg"))
    assert doctor.run_doctor()["ok"] is False
