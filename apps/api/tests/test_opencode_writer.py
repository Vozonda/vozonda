"""Cloud script writers are configured, not hardcoded.

Bench 2026-09-28 (bench/runs/20260928-writers): of the OpenCode free models
only big-pickle and mimo-v2.6-flash-free wrote full scripts in German and
English; Kimi K3 on NIM was down with 504s the same day. Model lists change
weekly, so which models run, in which order, and which engine backs up the
chosen one are settings (llm.opencode_models, llm.nim_model,
llm.backup_engine); the UI lists what the providers offer live. The OpenCode
free tier only runs from within OpenCode, so vozonda calls the local CLI.
"""

import asyncio
import stat

import pytest
from fastapi.testclient import TestClient

from vozonda_api import main, pipeline
from vozonda_api import providers as providers_mod
from vozonda_api import settings_store as ss
from vozonda_api.providers import script as script_mod

FAKE = """#!/bin/sh
# fake opencode: "models" or: run -m MODEL --agent plan MESSAGE -f FILE
if [ "$1" = models ]; then printf 'opencode/alpha-free\\nopencode/beta\\nother/gamma\\n'; exit 0; fi
model="$3"
case "$model" in *broken*) echo "boom" >&2; exit 3;; esac
printf '\\033[0m\\n> plan \\302\\267 %s\\n\\033[0m\\n' "$model"
echo '[{"speaker":"A","text":"Hi from '"$model"'"},{"speaker":"B","text":"Yes."}]'
echo 'DESCRIPTION: a test'
"""

LLM_KEYS = ("llm.engine", "llm.backup_engine", "llm.opencode_models", "llm.nim_model", "llm.nim_api_key")


@pytest.fixture(autouse=True)
def _restore_llm_settings():
    before = {k: ss.get_setting(k) for k in LLM_KEYS}
    yield
    for k, v in before.items():
        ss.set_setting(k, v if v is not None else ("local" if k == "llm.engine" else ""))


def _fake_bin(tmp_path, monkeypatch):
    b = tmp_path / "opencode"
    b.write_text(FAKE)
    b.chmod(b.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("VOZONDA_OPENCODE_BIN", str(b))
    return b


def test_opencode_runs_the_configured_models_in_order(tmp_path, monkeypatch):
    _fake_bin(tmp_path, monkeypatch)
    ss.set_setting("llm.engine", "opencode")
    ss.set_setting("llm.opencode_models", "opencode/beta, opencode/alpha-free")
    chain = providers_mod.llm_chain()
    assert [p["model"] for p in chain] == ["opencode/beta", "opencode/alpha-free"]
    assert all(p["base"] == providers_mod.OPENCODE_BASE for p in chain)


def test_no_model_names_in_code_an_empty_list_is_an_empty_chain(tmp_path, monkeypatch):
    _fake_bin(tmp_path, monkeypatch)
    monkeypatch.delenv("VOZONDA_OPENCODE_MODELS", raising=False)
    ss.set_setting("llm.engine", "opencode")
    ss.set_setting("llm.opencode_models", "")
    assert providers_mod.llm_chain() == []
    monkeypatch.setenv("VOZONDA_OPENCODE_MODELS", "opencode/from-env")
    assert [p["model"] for p in providers_mod.llm_chain()] == ["opencode/from-env"]


def test_malformed_model_ids_are_rejected():
    with pytest.raises(ValueError):
        ss.set_setting("llm.opencode_models", "big pickle")
    with pytest.raises(ValueError):
        ss.set_setting("llm.nim_model", "no model; rm -rf")


def test_backup_engine_follows_any_primary(tmp_path, monkeypatch):
    _fake_bin(tmp_path, monkeypatch)
    ss.set_setting("llm.opencode_models", "opencode/beta")
    ss.set_setting("llm.nim_model", "vendor/some-model")
    ss.set_setting("llm.nim_api_key", "nvapi-test")
    ss.set_setting("llm.engine", "kimi_nim")
    ss.set_setting("llm.backup_engine", "opencode")
    chain = providers_mod.llm_chain()
    assert [p["model"] for p in chain] == ["vendor/some-model", "opencode/beta"]
    ss.set_setting("llm.backup_engine", "none")
    assert [p["model"] for p in providers_mod.llm_chain()] == ["vendor/some-model"]
    ss.set_setting("llm.backup_engine", "kimi_nim")  # same as primary: not twice
    assert len(providers_mod.llm_chain()) == 1
    with pytest.raises(ValueError):
        ss.set_setting("llm.backup_engine", "nonsense")


def test_models_endpoint_lists_what_opencode_offers(tmp_path, monkeypatch):
    _fake_bin(tmp_path, monkeypatch)
    body = TestClient(main.app).get("/llm/models", params={"engine": "opencode"}).json()
    assert body["models"] == ["opencode/alpha-free", "opencode/beta"]


def test_script_call_runs_the_cli_and_parses_its_output(tmp_path, monkeypatch):
    _fake_bin(tmp_path, monkeypatch)
    lines, desc = asyncio.run(script_mod.script_call(
        prompt="write", model="opencode/beta", base=providers_mod.OPENCODE_BASE))
    assert lines[0] == {"speaker": "A", "text": "Hi from opencode/beta"}
    assert desc == "a test"


def test_chat_completion_returns_the_text_without_the_cli_header(tmp_path, monkeypatch):
    _fake_bin(tmp_path, monkeypatch)
    prov = {"name": "opencode", "base": providers_mod.OPENCODE_BASE, "model": "opencode/beta"}
    text = asyncio.run(pipeline._chat_completion(prov, "title please"))
    assert text.startswith("[{") and "> plan" not in text and "\x1b" not in text, repr(text)


def test_a_failing_cli_raises_so_the_chain_moves_on(tmp_path, monkeypatch):
    _fake_bin(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(script_mod.script_call(prompt="x", model="opencode/broken", base=providers_mod.OPENCODE_BASE))


def test_probe_reports_cloud_and_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("VOZONDA_OPENCODE_BIN", str(tmp_path / "missing"))
    ss.set_setting("llm.opencode_models", "opencode/beta")
    body = TestClient(main.app).get("/llm/probe", params={"engine": "opencode"}).json()
    assert body["installed"] is False and body["location"] == "cloud"
    _fake_bin(tmp_path, monkeypatch)
    body = TestClient(main.app).get("/llm/probe", params={"engine": "opencode"}).json()
    assert body["installed"] is True and body["model_id"] == "opencode/beta"
    ss.set_setting("llm.opencode_models", "")
    monkeypatch.delenv("VOZONDA_OPENCODE_MODELS", raising=False)
    body = TestClient(main.app).get("/llm/probe", params={"engine": "opencode"}).json()
    assert body["installed"] is False and "model" in body["note"]
