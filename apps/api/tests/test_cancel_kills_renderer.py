"""VOZONDA-CANCEL-KILLS-RENDERER: cancelling a job stops its voice renderer.

No real TTS, no GPU: the renderer is a stub script that writes its PID file
and sleeps 60 s. Cancelling the voice task must kill the renderer (and any
children it spawned) within seconds and remove partial output files, with no
manual kill call in the test. Fails on unfixed code: the tracked-subprocess
helpers it imports do not exist there, and nothing kills the child.
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from vozonda_api.jobs import JobStore, _conn
from vozonda_api.pipeline import (
    _job_subprocesses,
    _register_subprocess,
    _voice,
)

MEDIA = Path(os.environ["VOZONDA_MEDIA"])
LINES = [{"speaker": "A", "text": "Hello world"}]


@pytest.fixture(autouse=True)
def _isolate():
    _job_subprocesses.clear()
    yield
    _job_subprocesses.clear()
    with _conn() as c:
        c.execute("DELETE FROM jobs WHERE id LIKE 't-cancel-%'")


@pytest.fixture()
def stub_engine(monkeypatch, tmp_path):
    """Route the voice stage at a stub renderer run by this interpreter."""
    renderer = tmp_path / "stub_renderer.py"
    child_flag = tmp_path / "spawn_child"
    renderer.write_text(
        "import json, os, subprocess, sys, time\n"
        "from pathlib import Path\n"
        'cfg = json.loads(Path(sys.argv[sys.argv.index("--config") + 1]).read_text())\n'
        'Path(cfg["out"]).with_suffix(".pid").write_text(str(os.getpid()))\n'
        f"if Path({str(child_flag)!r}).exists():\n"
        '    kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
        '    Path(cfg["out"]).with_suffix(".child.pid").write_text(str(kid.pid))\n'
        "time.sleep(60)\n"
    )
    import vozonda_api.pipeline as pipeline
    import vozonda_api.providers as providers
    import vozonda_api.settings_store as settings_store

    monkeypatch.setattr(pipeline, "TTS_PY", sys.executable)
    monkeypatch.setattr(
        settings_store,
        "get_setting",
        lambda key: "stub_tts" if key == "tts.engine" else None,
    )
    monkeypatch.setattr(
        providers, "tts_engines", lambda refresh=False: {"stub_tts": SimpleNamespace(renderer=str(renderer))}
    )
    return renderer, child_flag


def _make_voice_job(store: JobStore, job_id: str) -> None:
    store.create(job_id, "http://example.com/test", style="balanced")
    store.set_stage_running(job_id, "script")
    store.update(job_id, script=LINES)
    store.set_stage_done(job_id, "script")
    store.set_stage_running(job_id, "voice")


def _proc_dead(pid: int) -> bool:
    """True when a PID is gone. A zombie still answers kill(pid, 0)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    try:
        with open(f"/proc/{pid}/stat") as f:
            state = f.read().rsplit(")", 1)[-1].split()[0]
        return state == "Z"
    except (FileNotFoundError, ProcessLookupError, IndexError):
        return True
    except OSError:
        return False


async def _wait_for(pred, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = pred()
        if value is not None and value is not False:
            return value
        await asyncio.sleep(0.1)
    return pred()


async def _wait_pid_file(path: Path, timeout: float = 10.0) -> int:
    def _read():
        try:
            return int(path.read_text().strip())
        except (FileNotFoundError, ValueError):
            return None

    pid = await _wait_for(_read, timeout)
    assert pid, f"renderer never wrote its PID file: {path}"
    return pid


async def _wait_dead(pid: int, timeout: float = 8.0) -> None:
    def _gone():
        return True if _proc_dead(pid) else None

    assert await _wait_for(_gone, timeout), f"process {pid} still alive after cancel"


@pytest.mark.asyncio
async def test_cancel_kills_renderer_subprocess(stub_engine):
    """Cancelling the voice task kills the renderer; the job ends failed."""
    _, _ = stub_engine
    store = JobStore()
    job_id = "t-cancel-simple"
    _make_voice_job(store, job_id)

    task = asyncio.create_task(_voice(store, job_id, LINES, MEDIA, style="balanced"))
    try:
        renderer_pid = await _wait_pid_file(MEDIA / f"{job_id}.pid")
        assert not _proc_dead(renderer_pid), "renderer died before cancellation"
        assert _job_subprocesses.get(job_id), "renderer subprocess not tracked"

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # No manual kill call: cancellation alone must have stopped the renderer.
        await _wait_dead(renderer_pid)
        assert job_id not in _job_subprocesses, "cancelled job still tracks subprocesses"
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # main._run marks the cancelled job failed; mirror that and check state.
    assert store.fail(job_id, "voice", "cancelled")["state"] == "failed"
    assert store.get(job_id)["state"] == "failed"


@pytest.mark.asyncio
async def test_cancel_kills_renderer_process_group(stub_engine):
    """Cancelling kills the renderer and the child it spawned (process group)."""
    _, child_flag = stub_engine
    child_flag.touch()
    store = JobStore()
    job_id = "t-cancel-group"
    _make_voice_job(store, job_id)

    task = asyncio.create_task(_voice(store, job_id, LINES, MEDIA, style="balanced"))
    try:
        renderer_pid = await _wait_pid_file(MEDIA / f"{job_id}.pid")
        child_pid = await _wait_pid_file(MEDIA / f"{job_id}.child.pid")
        assert not _proc_dead(renderer_pid), "renderer died before cancellation"
        assert not _proc_dead(child_pid), "renderer child died before cancellation"

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await _wait_dead(renderer_pid)
        await _wait_dead(child_pid)
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.asyncio
async def test_cancel_removes_partial_output_files(stub_engine):
    """Cancelling removes the job's partial .wav, timing and turn caches."""
    _, _ = stub_engine
    store = JobStore()
    job_id = "t-cancel-cleanup"
    _make_voice_job(store, job_id)
    wav = MEDIA / f"{job_id}.wav"
    timing = MEDIA / f"{job_id}.timing.json"
    turns = MEDIA / f".{job_id}_turns"
    wav.write_bytes(b"partial audio")
    timing.write_text("{}")
    (turns / "seg").mkdir(parents=True)
    (turns / "seg" / "0000.wav").write_bytes(b"partial turn")

    task = asyncio.create_task(_voice(store, job_id, LINES, MEDIA, style="balanced"))
    try:
        await _wait_pid_file(MEDIA / f"{job_id}.pid")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    assert not wav.exists(), "partial wav survived cancellation"
    assert not timing.exists(), "partial timing file survived cancellation"
    assert not turns.exists(), "partial turn cache survived cancellation"


@pytest.mark.asyncio
async def test_run_cancellation_kills_subprocess_and_fails_job():
    """DELETE /jobs path: main._run kills tracked procs and fails the job."""
    import vozonda_api.main as api_main

    store = api_main.store
    job_id = "t-cancel-run"
    store.create(job_id, "http://example.com/test", style="balanced")
    store.set_stage_running(job_id, "voice")
    api_main.listeners[job_id] = []
    proc_holder: dict = {}

    async def _sleepy_runner(job_store: JobStore, jid: str):
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        proc_holder["proc"] = proc
        _register_subprocess(jid, proc)
        yield {"state": "running", "current_stage": "voice"}
        await asyncio.sleep(60)

    task = asyncio.create_task(api_main._run(job_id, runner=_sleepy_runner))
    api_main.tasks[job_id] = task
    try:
        def _started():
            return True if proc_holder.get("proc") is not None else None

        assert await _wait_for(_started, 10.0), "runner never spawned its subprocess"
        pid = proc_holder["proc"].pid
        assert not _proc_dead(pid), "subprocess died before cancellation"

        # What DELETE /jobs/{id} does: cancel the job's task.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await _wait_dead(pid)
        assert store.get(job_id)["state"] == "failed"
    finally:
        api_main.listeners.pop(job_id, None)
        api_main.tasks.pop(job_id, None)
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
