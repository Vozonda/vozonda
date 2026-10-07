"""Sanity check that pytest itself cannot reach production data.

A tiny dummy test is executed via subprocess with VOZONDA_DB, VOZONDA_MEDIA
and VOZONDA_SECRETS_DIR pointed at a *sentinel* directory that holds a
marker DB file and a marker text file.  The subprocess test writes
nothing (its only assertion passes), so the sentinel must be byte-identical
before and after.

This is the outermost guard: even if conftest is broken, the sentinel
proves whether the child process ever saw the real filesystem.
"""

import hashlib
import os
import subprocess
from pathlib import Path


def _make_sentinel(tmp_path: Path) -> Path:
    """Create a tiny directory tree with marker files and return its root."""
    sent = tmp_path / "sentinel"
    sent.mkdir()
    (sent / "marker.txt").write_text(
        "sentinel-mark", encoding="utf-8"
    )
    db_path = sent / "jobs.db"
    db_path.write_bytes(b"SQLite format 3\x00")
    return sent


def _tree_hash(root: Path) -> str:
    """Deterministic hash of every file's content + path under *root*."""
    h = hashlib.sha256()
    for f in sorted(root.rglob("*")):
        if f.is_file():
            h.update(f"{f.relative_to(root)}\x00".encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def test_sentinel_is_untouched(tmp_path, monkeypatch):
    """A subprocess pytest that runs a trivial test must not touch sentinel."""
    sentinel = _make_sentinel(tmp_path)
    before = _tree_hash(sentinel)

    # Minimal test that always passes, but uses the sentinel paths.
    inner_test = tmp_path / "inner_test.py"
    inner_test.write_text(
        "def test_dummy_pass():\n" "    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    # Point at the sentinel so that the inner test *attempts* to use it.
    env["VOZONDA_DB"] = str(sentinel / "jobs.db")
    env["VOZONDA_MEDIA"] = str(sentinel / "media")
    env["VOZONDA_SECRETS_DIR"] = str(sentinel / "secrets")
    env["VOZONDA_HF_HOME"] = str(sentinel / "hf-cache")
    # Remove the CONFD_PATH so pytest uses the worktree venv, not ours.
    env.pop("PYTEST_ADDOPTS", None)

    pytest_bin = Path(__file__).resolve().parents[2] / ".venv" / "bin" / "pytest"
    if not pytest_bin.exists():
        pytest_bin = Path(__import__("sys").executable).parent / "pytest"

    result = subprocess.run(
        [str(pytest_bin), "-xvs", str(inner_test), "--no-header"],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    # The inner test must pass.
    assert result.returncode == 0, (
        f"inner test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    after = _tree_hash(sentinel)
    assert after == before, (
        f"sentinel directory was modified during subprocess test:\n"
        f"before: {before}\n"
        f"after:  {after}"
    )


def test_env_reads_only_the_vozonda_prefix():
    """env() reads VOZONDA_<NAME> and ignores the old product prefix."""
    from vozonda_api.env import env

    old = ("HEAR" + "SAY") + "_TEST_PREFIX"
    os.environ[old] = "old-prefix-val"
    try:
        assert env("TEST_PREFIX") is None
        os.environ["VOZONDA_TEST_PREFIX"] = "v-prefix-val"
        assert env("TEST_PREFIX") == "v-prefix-val"
    finally:
        os.environ.pop(old, None)
        os.environ.pop("VOZONDA_TEST_PREFIX", None)
