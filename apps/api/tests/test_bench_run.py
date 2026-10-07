"""Tests for bench/run.py - BENCH-1 benchmark runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "bench"))
from run import (
    build_job_body,
    build_run_id,
    download_episode,
    load_sources,
    process_source,
    wait_for_job,
)

SOURCES_YAML = """\
sources:
  - id: s1-fabrication-gate
    url: https://sovgrid.org/blog/the-quality-gate-that-rewards-fabrication
    kind: narrative blog post
    stresses: story arc
  - id: s2-lightning-network
    url: https://en.wikipedia.org/wiki/Lightning_Network
    kind: encyclopedic
"""


@pytest.fixture
def sources_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "sources.yaml"
    p.write_text(SOURCES_YAML)
    return p


@pytest.fixture
def sample_source():
    return {
        "id": "s1-fabrication-gate",
        "url": "https://sovgrid.org/blog/the-quality-gate-that-rewards-fabrication",
        "kind": "narrative blog post",
        "stresses": "story arc",
    }


@pytest.fixture
def args():
    return MagicMock(
        style="balanced",
        hosts=2,
        sources="",
        api="http://127.0.0.1:8787",
        token="",
    )


# ---------------------------------------------------------------------------
# build_job_body
# ---------------------------------------------------------------------------


def test_build_job_body_has_url_and_style(sample_source, args) -> None:
    body = build_job_body(sample_source, args)
    assert body["url"] == sample_source["url"]
    assert body["style"] == "balanced"
    assert body["hosts"] == 2
    assert body["language"] == "en"
    assert body["format"] == "dialog"
    assert body["tone"] == "neutral"


def test_build_job_body_language_default(sample_source, args) -> None:
    body = build_job_body(sample_source, args)
    assert body["language"] == "en"


def test_build_job_body_language_from_source(sample_source, args) -> None:
    source = dict(sample_source, language="de")
    body = build_job_body(source, args)
    assert body["language"] == "de"


# ---------------------------------------------------------------------------
# build_run_id
# ---------------------------------------------------------------------------


def test_build_run_id_format() -> None:
    rid = build_run_id("balanced")
    assert rid.endswith("-balanced")
    assert len(rid) == len("20260922T1530Z-balanced")
    assert "T" in rid and "Z" in rid


# ---------------------------------------------------------------------------
# load_sources
# ---------------------------------------------------------------------------


def test_load_sources(sources_yaml: Path) -> None:
    sources = load_sources(sources_yaml)
    assert len(sources) == 2
    assert sources[0]["id"] == "s1-fabrication-gate"
    assert sources[1]["id"] == "s2-lightning-network"


# ---------------------------------------------------------------------------
# wait_for_job - done
# ---------------------------------------------------------------------------


def _make_mock_response(job_data: dict) -> AsyncMock:
    """Create a mock httpx response with sync json() and raise_for_status()."""
    mock_resp = AsyncMock()
    mock_resp.json = Mock(return_value=job_data)
    mock_resp.raise_for_status = Mock()
    return mock_resp


@pytest.mark.asyncio
async def test_wait_for_job_stops_on_done(args) -> None:
    done_job = {"id": "job-1", "state": "done", "script": []}
    mock_resp = _make_mock_response(done_job)

    client = AsyncMock()
    client.get = AsyncMock(return_value=mock_resp)

    with patch("run.asyncio.sleep", new=AsyncMock()):
        result = await wait_for_job(client, "http://api", "", "job-1", timeout=30, interval=1)

    assert result["state"] == "done"
    assert client.get.call_count == 1


@pytest.mark.asyncio
async def test_wait_for_job_stops_on_failed(args) -> None:
    failed_job = {"id": "job-2", "state": "failed", "error": "boom"}
    mock_resp = _make_mock_response(failed_job)

    client = AsyncMock()
    client.get = AsyncMock(return_value=mock_resp)

    with patch("run.asyncio.sleep", new=AsyncMock()):
        result = await wait_for_job(client, "http://api", "", "job-2", timeout=30, interval=1)

    assert result["state"] == "failed"


@pytest.mark.asyncio
async def test_wait_for_job_stops_on_cancelled(args) -> None:
    cancelled_job = {"id": "job-3", "state": "cancelled"}
    mock_resp = _make_mock_response(cancelled_job)

    client = AsyncMock()
    client.get = AsyncMock(return_value=mock_resp)

    with patch("run.asyncio.sleep", new=AsyncMock()):
        result = await wait_for_job(client, "http://api", "", "job-3", timeout=30, interval=1)

    assert result["state"] == "cancelled"


@pytest.mark.asyncio
async def test_wait_for_job_times_out(args, monkeypatch) -> None:
    import run as run_mod

    running_job = {"id": "job-4", "state": "running"}
    mock_resp = _make_mock_response(running_job)

    client = AsyncMock()
    client.get = AsyncMock(return_value=mock_resp)

    # F-1: fake clock. The real loop spins on time.monotonic() until the
    # 2 s deadline; with sleep mocked it busy-loops for 2 real seconds.
    # The fake sleep advances the fake clock, so TimeoutError still fires
    # after timeout seconds with no real wait.
    now = [1000.0]
    monkeypatch.setattr(run_mod.time, "monotonic", lambda: now[0])

    async def _fake_sleep(s):
        now[0] += s

    monkeypatch.setattr(run_mod.asyncio, "sleep", _fake_sleep)
    with pytest.raises(TimeoutError):
        await wait_for_job(
            client, "http://api", "", "job-4", timeout=2, interval=1
        )
    assert client.get.call_count >= 2


# ---------------------------------------------------------------------------
# process_source - outputs land in expected paths
# ---------------------------------------------------------------------------


def _make_job_resp(job_data: dict) -> AsyncMock:
    """Create a mock httpx response for /jobs endpoint."""
    mock = AsyncMock()
    mock.json = Mock(return_value=job_data)
    mock.raise_for_status = Mock()
    return mock


def _make_audio_resp(content: bytes = b"FAKE_MP3_DATA") -> AsyncMock:
    """Create a mock httpx response for /audio endpoint."""
    mock = AsyncMock()
    mock.content = content
    mock.raise_for_status = Mock()
    return mock


@pytest.mark.asyncio
async def test_process_source_done_outputs(tmp_path: Path, sample_source, args) -> None:
    run_id = build_run_id("balanced")
    job_id = "s1-fabrication-gate-abc1"

    done_job = {
        "id": job_id,
        "state": "done",
        "url": sample_source["url"],
        "script": [
            {"speaker": "host1", "text": "Hello there"},
            {"speaker": "host2", "text": "Hi back"},
        ],
        "error": "",
    }

    audio_resp = _make_audio_resp()

    async def mock_get(url, **kwargs):
        if "/jobs/" in url:
            return _make_job_resp(done_job)
        elif "/audio/" in url:
            return audio_resp
        return AsyncMock()

    async def mock_post(url, **kwargs):
        return _make_job_resp({"id": job_id, "state": "queued"})

    client = AsyncMock()
    client.post = AsyncMock(side_effect=mock_post)
    client.get = AsyncMock(side_effect=mock_get)

    with patch("run.RUNS_DIR", tmp_path / "runs"):
        result = await process_source(
            client, "http://api", "", sample_source, run_id, args
        )

    assert result["state"] == "done"
    run_dir = tmp_path / "runs" / run_id / sample_source["id"]
    assert (run_dir / "job.json").exists()
    assert (run_dir / "script.json").exists()
    assert (run_dir / "episode.mp3").exists()

    loaded_job = json.loads((run_dir / "job.json").read_text())
    assert loaded_job["state"] == "done"
    loaded_script = json.loads((run_dir / "script.json").read_text())
    assert len(loaded_script) == 2


@pytest.mark.asyncio
async def test_process_source_failed_records_error(tmp_path: Path, sample_source, args) -> None:
    run_id = build_run_id("balanced")
    job_id = "s1-fabrication-gate-abc1"

    failed_job = {
        "id": job_id,
        "state": "failed",
        "url": sample_source["url"],
        "script": None,
        "error": "pipeline crashed",
    }

    async def mock_get(url, **kwargs):
        return _make_job_resp(failed_job)

    async def mock_post(url, **kwargs):
        return _make_job_resp({"id": job_id, "state": "queued"})

    client = AsyncMock()
    client.post = AsyncMock(side_effect=mock_post)
    client.get = AsyncMock(side_effect=mock_get)

    with patch("run.RUNS_DIR", tmp_path / "runs"):
        result = await process_source(
            client, "http://api", "", sample_source, run_id, args
        )

    assert result["state"] == "failed"
    assert result["error"] == "pipeline crashed"
    run_dir = tmp_path / "runs" / run_id / sample_source["id"]
    assert (run_dir / "job.json").exists()
    loaded_job = json.loads((run_dir / "job.json").read_text())
    assert loaded_job["error"] == "pipeline crashed"
    assert not (run_dir / "episode.mp3").exists()


@pytest.mark.asyncio
async def test_process_source_continues_on_failure(tmp_path: Path, args) -> None:
    run_id = build_run_id("balanced")
    job_id = "job-1"

    done_job = {
        "id": job_id,
        "state": "done",
        "url": "https://example.com",
        "script": [{"speaker": "h", "text": "x"}],
        "error": "",
    }

    audio_resp = _make_audio_resp()

    async def mock_get(url, **kwargs):
        if "/audio/" in url:
            return audio_resp
        return _make_job_resp(done_job)

    async def mock_post(url, **kwargs):
        return _make_job_resp({"id": job_id, "state": "queued"})

    client = AsyncMock()
    client.post = AsyncMock(side_effect=mock_post)
    client.get = AsyncMock(side_effect=mock_get)

    with patch("run.RUNS_DIR", tmp_path / "runs"):
        result = await process_source(
            client, "http://api", "",
            {"id": "s1", "url": "https://example.com"},
            run_id, args
        )

    assert result["state"] == "done"
    assert (tmp_path / "runs" / run_id / "s1" / "job.json").exists()
    assert (tmp_path / "runs" / run_id / "s1" / "episode.mp3").exists()


# ---------------------------------------------------------------------------
# download_episode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_episode_writes_file(tmp_path: Path) -> None:
    audio_resp = _make_audio_resp(b"MP3_BYTES")

    client = AsyncMock()
    client.get = AsyncMock(return_value=audio_resp)

    dest = tmp_path / "episode.mp3"
    await download_episode(client, "http://api", "", "job-1", dest)
    assert dest.exists()
    assert dest.read_bytes() == b"MP3_BYTES"


@pytest.mark.asyncio
async def test_download_episode_creates_parent(tmp_path: Path) -> None:
    audio_resp = _make_audio_resp(b"MP3_BYTES")

    client = AsyncMock()
    client.get = AsyncMock(return_value=audio_resp)

    dest = tmp_path / "nested" / "dir" / "episode.mp3"
    await download_episode(client, "http://api", "", "job-1", dest)
    assert dest.exists()