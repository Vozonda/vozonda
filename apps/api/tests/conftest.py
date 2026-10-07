import os
import sys

# Ensure the editable source for this worktree is on sys.path so that
# "vozonda_api" is importable during tests (the shared venv .pth points to
# the main checkout).
_sys = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src = os.path.join(_sys, "src")
if os.path.isdir(_src) and _src not in sys.path:
    sys.path.insert(0, _src)

import socket
import tempfile

_TMP = tempfile.mkdtemp(prefix="vozonda-tests-")

# ---------------------------------------------------------------------------
# Path isolation: every production path must resolve inside the temp dir.
#
# The env() helper (vozonda_api.env) reads VOZONDA_<NAME>, else a default.
# Every path variable points into the temp dir, so a shell that exported
# VOZONDA_* (the service's values) never leaks production data into tests.
#
# These are set BEFORE any vozonda_api import so that module-level constants
# (e.g. dia2.VOICES_DIR, providers.MEDIA_DIR, config.VOZONDA_ROOT) are
# computed from the temp dir instead of ~/vozonda.
_PATH_VARS = (
    "DB",
    "MEDIA",
    "ROOT",
    "SECRETS_DIR",
    "MODELS_DIR",
    "HF_HOME",
    "ENV_FILE",
)
for _v in _PATH_VARS:
    os.environ[f"VOZONDA_{_v}"] = os.path.join(_TMP, _v.lower())
    open(os.path.join(_TMP, "env_file"), "w").close()
    os.environ["HF_HOME"] = os.path.join(_TMP, "hf_home")

    # Tests are hermetic: no real network. Before this, six connections per run
    # went to the production LLM on :30001 (one test took 28 s when it was up,
    # 0.6 s when it was down) and every fleet gate loaded it. Unix sockets
    # (asyncio internals) stay allowed.
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _guard(addr):
    if isinstance(addr, tuple):
        raise ConnectionRefusedError(f"network disabled in tests: {addr[0]}:{addr[1]}")


def _no_connect(self, addr):
    _guard(addr)
    return _real_connect(self, addr)


def _no_connect_ex(self, addr):
    _guard(addr)
    return _real_connect_ex(self, addr)


socket.socket.connect = _no_connect
socket.socket.connect_ex = _no_connect_ex


import pytest


@pytest.fixture
def jobs_db(tmp_path, monkeypatch):
    """Isolated SQLite for jobs/watchlists (F-1/F-5).

    /tmp is slow on fleet runners (~10 ms per ALTER TABLE, ~0.45 s per
    fresh DB); /dev/shm is tmpfs when available. Same SQLite semantics,
    same assertions, only the directory changes.
    """
    from pathlib import Path

    import vozonda_api.jobs as jobs_mod

    try:
        shm_base = Path("/dev/shm") / "vozonda-test-dbs"
        shm_base.mkdir(parents=True, exist_ok=True)
        db_path = shm_base / f"{tmp_path.name}-jobs.db"
        if db_path.exists():
            db_path.unlink()
    except OSError:
        db_path = tmp_path / "jobs.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", db_path)
    jobs_mod.init_db()
    yield db_path
    try:
        if str(db_path).startswith("/dev/shm") and db_path.exists():
            db_path.unlink()
    except OSError:
        pass


@pytest.fixture
def api_client(jobs_db):
    """TestClient with an isolated DB."""
    from fastapi.testclient import TestClient

    from vozonda_api.main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_llm_retry_wait(monkeypatch):
    """The blocked network above surfaces as ConnectError, which the script
    writer retries with 10 s and 30 s waits; tests skip the wait."""
    import asyncio

    from vozonda_api import pipeline

    monkeypatch.setattr(pipeline, "_llm_retry_sleep", lambda s: asyncio.sleep(0))


# ---------------------------------------------------------------------------
# After every test, re-set the isolation env vars and re-import any
# config that might have been reloaded by the test (e.g.
# test_config_paths.py re-imports config with production defaults).
# This ensures that module-level constants (dia2.VOICES_DIR, etc.)
# remain consistent for subsequent tests in the same worker.
# ---------------------------------------------------------------------------
def _rebuild_config():
    """Re-import config so its derived paths use the temp dir."""
    import importlib

    # Force config to re-read the env vars.
    import vozonda_api.config as cfg
    importlib.reload(cfg)


def _reset_env():
    """Restore the isolation env vars that a test may have monkeypatched away."""
    for _v in _PATH_VARS:
        os.environ[f"VOZONDA_{_v}"] = os.path.join(_TMP, _v.lower())


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """After each test, restore isolation env vars and reload config."""
    yield
    _reset_env()
    try:
        _rebuild_config()
    except Exception:
        # A reload might fail if some other module has already imported
        # things that depend on config. In that case, at least restore
        # the env vars so the guard sees the right paths.
        pass


def _path_guard():
    """Check that all production paths resolve inside the temp dir."""
    import tempfile as _tf
    from pathlib import Path

    import vozonda_api.config as _cfg
    import vozonda_api.jobs as _jobs

    failures: list[str] = []
    tempdir = Path(_tf.gettempdir())

    for name, value in (
        ("jobs.DB_PATH", getattr(_jobs, "DB_PATH", None)),
        ("config.VOZONDA_ROOT", getattr(_cfg, "VOZONDA_ROOT", None)),
        ("config.VOZONDA_SECRETS_DIR", getattr(_cfg, "VOZONDA_SECRETS_DIR", None)),
        ("config.VOZONDA_MEDIA", getattr(_cfg, "VOZONDA_MEDIA", None)),
        ("config.VOZONDA_MODELS_DIR", getattr(_cfg, "VOZONDA_MODELS_DIR", None)),
    ):
        if value is None:
            continue
        p = Path(value)
        try:
            resolved = p.resolve()
        except OSError:
            resolved = p  # dead link or similar
        # Allowed: under temp dir, /dev/shm, or the specific test temp dir
        if resolved.is_relative_to(tempdir) or resolved == Path(_TMP):
            continue
        failures.append(f"{name}: {p} not under {tempdir}")

    if failures:
        raise pytest.UsageError(
            "production path guard failed:\n  " + "\n  ".join(failures)
        )


def pytest_sessionstart(session):
    _path_guard()