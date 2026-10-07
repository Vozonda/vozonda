"""The voice preflight checks the CONFIGURED engine's package, and not on every job.

2026-10-01: _tts_renderable always ran `import qwen_tts`; with tts.engine=kokoro on
an install without the tts-qwen extra (the new CPU default) every job was refused
('voice_renderable: qwen_tts does not import'). It also spawned that import (~4 s
of torch) for every job, which made several tests take 5-15 s."""
import subprocess
import time

import pytest

from vozonda_api import doctor


@pytest.fixture
def calls(monkeypatch, tmp_path):
    py = tmp_path / "python"
    py.write_text("")
    monkeypatch.setattr(doctor, "TTS_PY", str(py))
    doctor._RENDERABLE_CACHE.clear()
    seen: list[list[str]] = []
    missing: set[str] = set()

    def fake_run(cmd, **kw):
        seen.append(cmd)
        module = cmd[-1].split()[-1]
        rc = 1 if module in missing else 0
        return subprocess.CompletedProcess(cmd, rc, b"", f"No module named '{module}'".encode() if rc else b"")

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)
    return seen, missing, monkeypatch


def _engine(monkeypatch, name):
    monkeypatch.setattr("vozonda_api.settings_store.get_setting", lambda k: name if k == "tts.engine" else None)


def test_kokoro_install_without_qwen_is_not_blocked(calls):
    seen, missing, mp = calls
    missing.add("qwen_tts")
    _engine(mp, "kokoro")
    ok, hint = doctor._tts_renderable()
    assert ok, hint
    assert seen and seen[0][-1] == "import kokoro_onnx"


def test_missing_package_of_the_configured_engine_blocks(calls):
    _seen, missing, mp = calls
    missing.add("kokoro_onnx")
    _engine(mp, "kokoro")
    ok, hint = doctor._tts_renderable()
    assert not ok and "kokoro_onnx" in hint and "tts-kokoro" in hint


@pytest.mark.parametrize(("engine", "module"), [("qwen_tts", "qwen_tts"), ("piper", "piper")])
def test_each_local_engine_checks_its_own_package(calls, engine, module):
    seen, _missing, mp = calls
    _engine(mp, engine)
    assert doctor._tts_renderable()[0]
    assert seen[0][-1] == f"import {module}"


def test_engine_without_a_known_package_is_not_blocked_by_qwen(calls):
    seen, missing, mp = calls
    missing.add("qwen_tts")
    _engine(mp, "voxtral")
    assert doctor._tts_renderable()[0]
    assert seen == []


def test_a_successful_check_is_cached_a_failure_is_not(calls):
    seen, missing, mp = calls
    _engine(mp, "kokoro")
    doctor._tts_renderable()
    doctor._tts_renderable()
    assert len(seen) == 1, "the import must not be spawned for every job"
    missing.add("piper")
    _engine(mp, "piper")
    doctor._tts_renderable()
    doctor._tts_renderable()
    assert len(seen) == 3, "a failure is checked again next time (the user may have fixed it)"


def test_the_cache_expires(calls):
    seen, _missing, mp = calls
    _engine(mp, "kokoro")
    doctor._tts_renderable()
    key = next(iter(doctor._RENDERABLE_CACHE))
    doctor._RENDERABLE_CACHE[key] = time.monotonic() - doctor._RENDERABLE_TTL - 1
    doctor._tts_renderable()
    assert len(seen) == 2


@pytest.mark.parametrize("value", ["", "   "])
def test_an_empty_tts_python_setting_does_not_crash_the_preflight(monkeypatch, value):
    """VOZONDA_TTS_PY='' made Path('') ('.') look like an interpreter and subprocess raised."""
    monkeypatch.setattr(doctor, "TTS_PY", value)
    assert doctor._tts_renderable() == (True, "")  # _tts_python_ok reports it with a hint
