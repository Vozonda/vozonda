"""Kimi K3 via NVIDIA NIM as an optional cloud script writer (2026-09-25).

Script-only bench on the same prompt and sources: the local qwen3.6-35b-a3b
kept uniform 15-30 word turns without quick reactions or contractions, Kimi
K3 met the form in English and German. It is opt-in: the source text leaves
the machine, so the engine is grouped under cloud in the UI.
"""

import pytest
from fastapi.testclient import TestClient

from vozonda_api import main
from vozonda_api import providers as providers_mod
from vozonda_api import settings_store as ss


@pytest.fixture(autouse=True)
def _nim_model(monkeypatch):
    # the model id is configuration (llm.nim_model or VOZONDA_NIM_MODEL), not code
    monkeypatch.setenv("VOZONDA_NIM_MODEL", "moonshotai/kimi-k3")


def test_kimi_nim_is_a_valid_engine_with_its_own_secret_key():
    ss.set_setting("llm.engine", "kimi_nim")
    ss.set_setting("llm.nim_api_key", "nvapi-test")
    try:
        chain = providers_mod.llm_chain()
        assert chain == [{"name": "kimi_nim", "base": "https://integrate.api.nvidia.com/v1",
                          "model": "moonshotai/kimi-k3", "key": "nvapi-test"}]
        shown = TestClient(main.app).get("/settings").json()["settings"]
        assert shown["llm.nim_api_key"] != "nvapi-test"  # masked like llm.api_key
    finally:
        ss.set_setting("llm.nim_api_key", "")
        ss.set_setting("llm.engine", "local")


def test_kimi_nim_key_falls_back_to_env_then_key_file(tmp_path, monkeypatch):
    ss.set_setting("llm.engine", "kimi_nim")
    ss.set_setting("llm.nim_api_key", "")
    try:
        monkeypatch.setattr(providers_mod, "VOZONDA_SECRETS_DIR", tmp_path, raising=False)
        monkeypatch.setenv("VOZONDA_NIM_API_KEY", "from-env")
        assert providers_mod.llm_chain()[0]["key"] == "from-env"
        monkeypatch.delenv("VOZONDA_NIM_API_KEY")
        (tmp_path / "nvidia_nim_api.key").write_text("from-file\n")
        assert providers_mod.llm_chain()[0]["key"] == "from-file"
    finally:
        ss.set_setting("llm.engine", "local")


def test_kimi_nim_probe_reports_cloud_without_leaking_the_key(tmp_path, monkeypatch):
    monkeypatch.setattr(providers_mod, "VOZONDA_SECRETS_DIR", tmp_path, raising=False)
    monkeypatch.delenv("VOZONDA_NIM_API_KEY", raising=False)
    ss.set_setting("llm.nim_api_key", "")
    body = TestClient(main.app).get("/llm/probe", params={"engine": "kimi_nim"}).json()
    assert body["status"] == "unconfigured" and body["installed"] is False
    ss.set_setting("llm.nim_api_key", "nvapi-secret")
    try:
        body = TestClient(main.app).get("/llm/probe", params={"engine": "kimi_nim"}).json()
        assert body["installed"] is True and body["location"] == "cloud"
        assert "nvapi-secret" not in str(body)
    finally:
        ss.set_setting("llm.nim_api_key", "")


def test_tts_engines_say_whether_they_run_local_or_in_the_cloud():
    engines = {e["id"]: e for e in TestClient(main.app).get("/providers").json()["providers"]}
    assert engines["voxtral"]["location"] == "cloud"
    assert engines["piper"]["location"] == "local"
    assert engines["qwen_tts"]["location"] == "local"
