"""LLM engines are generic: settings describe the user's setup, not the operator's.

The operator-era engines (nemotron_vllm, gemma_vllm, nemo_sglang) no longer
exist: writing one is rejected, a stored one reads as 'local' with a warning.
'qwen_vllm' stays accepted as an alias of 'local' on read and write. The
local probe reports what the user's own endpoint lists at /v1/models and
makes no hardware, quantization or speed claims. VOZONDA_ROOT defaults to
~/vozonda and no longer probes /data.
"""

from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vozonda_api import main
from vozonda_api import providers as providers_mod
from vozonda_api import settings_store as ss

REMOVED = ("nemotron_vllm", "gemma_vllm", "nemo_sglang")


@pytest.fixture(autouse=True)
def _restore_llm_engine_settings():
    before = {k: ss.get_setting(k) for k in ("llm.engine", "llm.backup_engine")}
    yield
    for k, v in before.items():
        if v is None:
            with ss._conn() as c:
                c.execute("DELETE FROM settings WHERE key = ?", (k,))
        else:
            ss.set_setting(k, v)


def test_removed_engines_are_rejected_on_write():
    for key in ("llm.engine", "llm.backup_engine"):
        for removed in REMOVED:
            with pytest.raises(ValueError):
                ss.set_setting(key, removed)


def test_stored_removed_engine_reads_as_local_with_a_warning(caplog):
    with ss._conn() as c:
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("llm.engine", "nemotron_vllm"),
        )
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("llm.backup_engine", "nemo_sglang"),
        )
    with caplog.at_level(logging.WARNING, logger="vozonda_api.settings_store"):
        assert ss.get_setting("llm.engine") == "local"
        assert ss.get_setting("llm.backup_engine") == "local"
    assert any("no longer exists" in r.getMessage() for r in caplog.records), (
        "expected one warning when a removed engine reads as 'local'"
    )


def test_qwen_vllm_is_an_alias_of_local_on_write_and_read():
    assert ss.set_setting("llm.engine", "qwen_vllm") == "local"
    assert ss.get_setting("llm.engine") == "local"
    assert ss.set_setting("llm.backup_engine", "qwen_vllm") == "local"
    assert ss.get_setting("llm.backup_engine") == "local"
    # the alias keeps the production backup chain working without a change
    chain = providers_mod.llm_chain()
    assert chain and chain[0]["name"] == "local"


class _FakeModelsResponse:
    status_code = 200

    def json(self):
        return {"data": [{"id": "test-model-xyz"}]}


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, headers=None):
        assert url.endswith("/models"), url
        return _FakeModelsResponse()


def test_local_probe_reports_the_endpoint_models_without_operator_claims(monkeypatch):
    monkeypatch.setattr(providers_mod, "LLM_BASE", "http://127.0.0.1:11434/v1", raising=False)
    monkeypatch.setattr(providers_mod, "LLM_MODEL", "test-model-xyz", raising=False)
    monkeypatch.setattr(main.httpx, "AsyncClient", _FakeAsyncClient)
    body = TestClient(main.app).get("/llm/probe", params={"engine": "local"}).json()
    assert body["status"] == "ok"
    assert body["model_id"] == "test-model-xyz"
    dumped = json.dumps(body)
    for claim in ("DGX Spark", "GB10", "NVFP4", "30001"):
        assert claim not in dumped, f"operator claim {claim!r} in local probe: {dumped}"
    assert body["label"] == "Local model (your endpoint)"


def test_vozonda_root_defaults_to_home_even_when_data_exists(monkeypatch):
    monkeypatch.delenv("VOZONDA_ROOT", raising=False)
    monkeypatch.delenv("VOZONDA_ROOT", raising=False)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    import vozonda_api.config as cfg

    importlib.reload(cfg)
    try:
        assert Path(cfg.VOZONDA_ROOT) == Path.home() / "vozonda"
    finally:
        importlib.reload(cfg)


def test_no_operator_machine_strings_in_src():
    roots = [
        Path(__file__).resolve().parents[1] / "src",
        Path(__file__).resolve().parents[2] / "web" / "src",
    ]
    forbidden = ("30003", "30004", "nemotron-nano", "gemma4-e2b", "DGX Spark")
    source_suffixes = {".py", ".svelte", ".ts", ".js", ".txt", ".md", ".json", ".html", ".css"}
    offenders: list[str] = []
    for root in roots:
        assert root.is_dir(), f"scan root missing: {root}"  # a wrong path must fail, not scan nothing
        for py in sorted(root.rglob("*")):
            if not py.is_file() or "__pycache__" in py.parts or py.suffix not in source_suffixes:
                continue
            text = py.read_text(encoding="utf-8", errors="ignore")
            for needle in forbidden:
                if needle in text:
                    offenders.append(f"{py}:{needle}")
    assert not offenders, "operator machine strings in src: " + "; ".join(offenders)
