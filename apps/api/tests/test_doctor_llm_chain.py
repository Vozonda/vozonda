"""The LLM preflight checks the configured engine chain, not VOZONDA_LLM_BASE alone.

2026-10-01: with llm.engine=custom pointing at :30005 and nothing on the default :30001,
every job failed 'no LLM server on http://127.0.0.1:30001/v1' before the script stage ran.
The same blocked anyone on a cloud writer (kimi_nim, claude, opencode) without a local LLM."""
from vozonda_api import doctor


class _Resp:
    status_code = 200


def _wire(monkeypatch, chain, open_ports):
    monkeypatch.setattr(doctor, "llm_chain", lambda: chain, raising=False)
    monkeypatch.setattr(doctor, "_port_open", lambda url, timeout=2.0: any(p in url for p in open_ports))
    monkeypatch.setattr(doctor.httpx, "get", lambda url, timeout=5, **kw: _Resp())


def test_custom_endpoint_up_while_default_base_is_down(monkeypatch):
    _wire(monkeypatch, [{"name": "custom", "base": "http://127.0.0.1:30005/v1", "model": "m"}], ["30005"])
    ok, msg = doctor._llm_ok()
    assert ok, msg


def test_cloud_writer_without_any_local_llm(monkeypatch):
    _wire(monkeypatch, [{"name": "kimi_nim", "base": "https://integrate.api.nvidia.com/v1", "model": "m", "key": "k"}], [])
    ok, msg = doctor._llm_ok()
    assert ok, msg


def test_backup_engine_counts_when_primary_is_down(monkeypatch):
    chain = [{"name": "custom", "base": "http://127.0.0.1:30005/v1", "model": "m"},
             {"name": "local", "base": "http://127.0.0.1:30001/v1", "model": "m"}]
    _wire(monkeypatch, chain, ["30001"])
    ok, msg = doctor._llm_ok()
    assert ok, msg


def test_nothing_reachable_names_every_tried_endpoint(monkeypatch):
    chain = [{"name": "custom", "base": "http://127.0.0.1:30005/v1", "model": "m"},
             {"name": "local", "base": "http://127.0.0.1:30001/v1", "model": "m"}]
    _wire(monkeypatch, chain, [])
    ok, msg = doctor._llm_ok()
    assert not ok
    assert "30005" in msg and "30001" in msg


def test_empty_chain_is_not_ok(monkeypatch):
    _wire(monkeypatch, [], [])
    ok, msg = doctor._llm_ok()
    assert not ok and msg


def test_cli_backed_writer_is_not_port_probed(monkeypatch):
    """opencode's base is the pseudo URL 'opencode:' (a CLI, only in the chain when installed)."""
    _wire(monkeypatch, [{"name": "opencode", "base": "opencode:", "model": "opencode/big-pickle"}], [])
    ok, msg = doctor._llm_ok()
    assert ok, msg
