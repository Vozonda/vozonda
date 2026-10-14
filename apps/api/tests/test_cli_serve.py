"""`vozonda --help` used to start the server; flags and env must reach uvicorn as documented."""

import pytest

from vozonda_api import main


def test_help_prints_usage_and_does_not_serve(monkeypatch, capsys):
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("server started on --help"))
    with pytest.raises(SystemExit) as exc:
        main.serve(["--help"])
    assert exc.value.code == 0
    assert "usage: vozonda" in capsys.readouterr().out


def test_host_and_port_from_env_and_flags(monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, host, port: calls.append((host, port)))
    monkeypatch.setenv("VOZONDA_HOST", "127.0.0.2")
    monkeypatch.setenv("VOZONDA_PORT", "9001")
    main.serve([])
    main.serve(["--host", "127.0.0.3", "--port", "9002"])
    assert calls == [("127.0.0.2", 9001), ("127.0.0.3", 9002)]


def test_default_is_loopback(monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, host, port: calls.append((host, port)))
    monkeypatch.delenv("VOZONDA_HOST", raising=False)
    monkeypatch.delenv("VOZONDA_PORT", raising=False)
    main.serve([])
    assert calls == [("127.0.0.1", 8787)]
