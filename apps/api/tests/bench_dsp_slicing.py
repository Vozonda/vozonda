"""Benchmark für Audio-Slicing-Performance (DUE-XXX).

Akzeptanzkriterien:
- FFmpeg Audio Slicing Latenz < 200ms
- SQLite Queue Locking stabil unter 50 gleichzeitigen SSE-Subscribern
- Keine Speicherlecks bei kontinuierlicher Audio-Mastering-Last
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

import psutil
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from vozonda_api.clips import compute_clip_bounds, slice_audio
from vozonda_api.jobs import JobStore

process = psutil.Process()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MP3_FILENAME = "bench-audio.mp3"


@pytest.fixture(scope="session")
def test_mp3(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a 10-second test MP3 via ffmpeg once per session."""
    mp3 = tmp_path_factory.mktemp("bench") / MP3_FILENAME
    if not mp3.exists():
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i",
                "sine=frequency=440:duration=10",
                "-c:a", "libmp3lame", "-b:a", "128k",
                str(mp3),
            ],
            capture_output=True, check=True, timeout=60,
        )
    assert mp3.exists() and mp3.stat().st_size > 512
    return mp3


@pytest.fixture()
def tmp_store(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    monkeypatch.setenv("VOZONDA_DB", str(db))
    monkeypatch.setenv("VOZONDA_MEDIA", str(tmp_path / "media"))
    import vozonda_api.jobs as jobs_mod
    importlib_reload = __import__("importlib").reload
    importlib_reload(jobs_mod)
    from vozonda_api.jobs import JobStore as JS
    return JS()


def _make_clip_source(mp3: Path, workdir: Path) -> tuple[Path, Path]:
    """Copy MP3 into workdir so the benchmark does not mutate the fixture."""
    src = workdir / MP3_FILENAME
    src.write_bytes(mp3.read_bytes())
    clip = workdir / "clip.mp3"
    return src, clip


# ---------------------------------------------------------------------------
# 1) FFmpeg Audio Slicing Latenz < 200ms
# ---------------------------------------------------------------------------

class TestSlicingLatency:
    """Measure end-to-end ffmpeg clip latency."""

    @pytest.mark.asyncio
    async def test_single_slice_latency_under_200ms(
        self, tmp_path: Path, test_mp3: Path
    ) -> None:
        """Single slice must complete in under 200ms."""
        workdir = tmp_path / "latency"
        workdir.mkdir(parents=True)
        src, clip = _make_clip_source(test_mp3, workdir)

        start = time.perf_counter()
        await slice_audio(src, clip, 0.0, 5.0)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert clip.exists(), "clip file was not created"
        assert clip.stat().st_size > 512, "clip file is empty"
        assert elapsed_ms < 200, (
            f"Slice latency {elapsed_ms:.1f}ms exceeds 200ms budget"
        )

    @pytest.mark.asyncio
    async def test_slice_latency_warmup_average(
        self, tmp_path, test_mp3: Path
    ) -> None:
        """Average latency across 5 warmup + 5 measured slices must be < 200ms."""
        workdir = tmp_path / "latency_avg"
        workdir.mkdir(parents=True)
        src, _ = _make_clip_source(test_mp3, workdir)

        times: list[float] = []
        for i in range(10):
            clip = workdir / f"clip_{i}.mp3"
            t0 = time.perf_counter()
            await slice_audio(src, clip, 1.0, 4.0)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            times.append(elapsed_ms)
            if i < 5:
                continue  # skip warmup

        measured = times[5:]
        avg_ms = sum(measured) / len(measured)
        assert avg_ms < 200, (
            f"Average slice latency {avg_ms:.1f}ms exceeds 200ms "
            f"(samples: {[f'{t:.1f}' for t in measured]})"
        )

    @pytest.mark.asyncio
    async def test_parallel_slices_latency(
        self, tmp_path, test_mp3: Path
    ) -> None:
        """Concurrent slices remain under 200ms each."""
        workdir = tmp_path / "latency_parallel"
        workdir.mkdir(parents=True)
        src, _ = _make_clip_source(test_mp3, workdir)

        async def _slice(i: int) -> tuple[int, float]:
            clip = workdir / f"clip_{i}.mp3"
            t0 = time.perf_counter()
            await slice_audio(src, clip, 0.0, 3.0)
            return i, (time.perf_counter() - t0) * 1000

        results = await asyncio.gather(*[_slice(i) for i in range(10)])
        for idx, elapsed_ms in results:
            assert (
                elapsed_ms < 200
            ), f"Parallel slice {idx} took {elapsed_ms:.1f}ms > 200ms"


# ---------------------------------------------------------------------------
# 2) SQLite Queue Locking unter 50 SSE-Subscribern
# ---------------------------------------------------------------------------

class TestSQLiteConcurrency:
    """Verify SQLite handles 50 concurrent SSE-like readers/writers."""

    @pytest.mark.asyncio
    async def test_50_concurrent_readers(
        self, tmp_path, monkeypatch, tmp_store
    ) -> None:
        """50 simultaneous reads must not block or deadlock."""
        # Seed a job
        tmp_store.create("job-001", "http://example.com/test")
        tmp_store.set_stage_running("job-001", "fetch")
        tmp_store.set_stage_done("job-001", "fetch")

        n = 50
        errors: list[Exception] = []

        async def _read_job() -> None:
            try:
                store = JobStore()
                job = store.get("job-001")
                assert job["id"] == "job-001"
            except Exception as exc:
                errors.append(exc)

        await asyncio.gather(*[_read_job() for _ in range(n)])

        assert not errors, f"{len(errors)} read failures: {errors}"

    @pytest.mark.asyncio
    async def test_50_concurrent_mixed读写(
        self, tmp_path, monkeypatch, tmp_store
    ) -> None:
        """50 concurrent mixed reads/writes must stay stable."""
        tmp_store.create("job-mx-001", "http://example.com/mx")
        tmp_store.create("job-mx-002", "http://example.com/mx2")

        n = 50
        errors: list[Exception] = []
        latencies: list[float] = []

        async def _access_job(idx: int) -> None:
            try:
                store = JobStore()
                t0 = time.perf_counter()
                if idx % 3 == 0:
                    store.get(f"job-mx-00{idx % 2 + 1}")
                else:
                    store.create(
                        f"job-mx-{idx:04d}",
                        f"http://example.com/{idx}",
                    )
                latencies.append((time.perf_counter() - t0) * 1000)
            except Exception as exc:
                errors.append(exc)

        await asyncio.gather(*[_access_job(i) for i in range(n)])

        assert not errors, f"{len(errors)} concurrent failures: {errors}"
        if latencies:
            avg = sum(latencies) / len(latencies)
            assert (
                avg < 500
            ), f"Average DB latency {avg:.1f}ms too high under 50 concurrent ops"

    @pytest.mark.asyncio
    async def test_sqlite_lock_contention_under_load(
        self, tmp_path, monkeypatch, tmp_store
    ) -> None:
        """Sustained 50-concurrent load must not raise OperationalError."""
        for i in range(5):
            tmp_store.create(f"seed-{i}", f"http://example.com/{i}")

        errors: list[Exception] = []
        rounds = 5

        async def _round(round_id: int) -> None:
            try:
                store = JobStore()
                for i in range(10):
                    job_id = f"load-{round_id}-{i}"
                    store.create(job_id, f"http://example.com/{job_id}")
                    store.set_stage_running(job_id, "fetch")
                    store.set_stage_done(job_id, "fetch")
                    store.get(job_id)
            except Exception as exc:
                errors.append(exc)

        await asyncio.gather(*[_round(r) for r in range(rounds)])

        operational_errors = [
            e for e in errors if "OperationalError" in type(e).__name__
        ]
        assert (
            not operational_errors
        ), f"SQLite lock contention errors: {operational_errors}"


# ---------------------------------------------------------------------------
# 3) Keine Speicherlecks bei kontinuierlicher Audio-Mastering-Last
# ---------------------------------------------------------------------------

class TestMemoryStability:
    """Detect memory leaks under sustained slicing load."""

    @pytest.mark.asyncio
    async def test_no_memory_leak_sustained_slicing(
        self, tmp_path, test_mp3: Path
    ) -> None:
        """RSS memory must not grow unboundedly over 100 slicing iterations."""
        workdir = tmp_path / "memtest"
        workdir.mkdir(parents=True)
        src, _ = _make_clip_source(test_mp3, workdir)

        tracemalloc.start()
        baseline_snapshot = tracemalloc.take_snapshot()
        baseline_rss = process.memory_info().rss

        n_iterations = 100
        for i in range(n_iterations):
            clip = workdir / f"memclip_{i}.mp3"
            await slice_audio(src, clip, 0.0, 2.0)
            # ensure file is cleaned up to simulate real workflow
            clip.unlink(missing_ok=True)

        current_rss = process.memory_info().rss
        current_snapshot = tracemalloc.take_snapshot()
        tracemalloc.stop()

        rss_growth_kb = (current_rss - baseline_rss) / 1024
        # Allow some variance but no unbounded growth
        assert (
            rss_growth_kb < 50_000
        ), f"RSS grew by {rss_growth_kb:.0f}KB over {n_iterations} iterations - possible leak"

        # tracemalloc top-10 comparison
        top_stats = current_snapshot.compare_to(baseline_snapshot, "lineno")
        top_total = sum(stat.size_diff for stat in top_stats[:10])
        assert (
            top_total < 5 * 1024 * 1024
        ), f"Top-10 tracemalloc allocations grew by {top_total / 1024:.0f}KB"

    @pytest.mark.asyncio
    async def test_memory_growth_per_iteration_bounded(
        self, tmp_path, test_mp3: Path
    ) -> None:
        """Per-iteration memory growth must be bounded (no leak)."""
        workdir = tmp_path / "memgrowth"
        workdir.mkdir(parents=True)
        src, _ = _make_clip_source(test_mp3, workdir)

        samples: list[int] = []
        for i in range(20):
            clip = workdir / f"growth_{i}.mp3"
            before = process.memory_info().rss
            await slice_audio(src, clip, 0.0, 1.0)
            after = process.memory_info().rss
            samples.append(after - before)
            clip.unlink(missing_ok=True)

        avg_growth = sum(samples) / len(samples)
        max_growth = max(samples)
        # Per-iteration RSS delta should average near zero
        assert (
            avg_growth < 100_000
        ), f"Average per-iteration RSS growth {avg_growth / 1024:.1f}KB is too high"
        assert (
            max_growth < 500_000
        ), f"Peak per-iteration RSS growth {max_growth / 1024:.1f}KB is too high"

    @pytest.mark.asyncio
    async def test_tracemalloc_no_duplicate_peaks(
        self, tmp_path, test_mp3: Path
    ) -> None:
        """tracemalloc must not show growing allocation peaks across runs."""
        workdir = tmp_path / "mempeaks"
        workdir.mkdir(parents=True)
        src, _ = _make_clip_source(test_mp3, workdir)

        tracemalloc.start()
        snapshots: list[tracemalloc.Snapshot] = []

        for _ in range(5):
            for i in range(10):
                clip = workdir / f"peak_{i}.mp3"
                await slice_audio(src, clip, 0.0, 0.5)
                clip.unlink(missing_ok=True)
            snapshots.append(tracemalloc.take_snapshot())

        tracemalloc.stop()

        # Compare every snapshot to the first - growth must be bounded
        for idx, snap in enumerate(snapshots[1:], start=1):
            stats = snap.compare_to(snapshots[0], "traceback")
            total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
            assert (
                total_growth < 2 * 1024 * 1024
            ), f"Snapshot {idx} grew {total_growth / 1024:.0f}KB vs snapshot 0"


# ---------------------------------------------------------------------------
# 4) End-to-end pipeline benchmark
# ---------------------------------------------------------------------------

class TestEndToEndBenchmark:
    """Full pipeline benchmarks: compute bounds + slice + store."""

    @pytest.mark.asyncio
    async def test_full_pipeline_under_500ms(
        self, tmp_path, test_mp3: Path, tmp_store
    ) -> None:
        """End-to-end (compute bounds + slice + DB store) < 500ms."""
        workdir = tmp_path / "e2e"
        workdir.mkdir(parents=True)
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("VOZONDA_MEDIA", str(workdir / "media"))
        monkeypatch.setenv("VOZONDA_DB", str(workdir / "jobs.db"))
        src, _ = _make_clip_source(test_mp3, workdir)

        script = [
            {"text": "Hello world", "t0": 0.0},
            {"text": "Second line here", "t0": 2.0},
            {"text": "Third line now", "t0": 4.0},
        ]
        start_sec, end_sec = compute_clip_bounds(script, 0, 1)

        clip_path = workdir / "e2e_clip.mp3"

        t0 = time.perf_counter()
        await slice_audio(src, clip_path, start_sec, end_sec)
        await asyncio.to_thread(
            tmp_store.create, "e2e-job", "http://example.com/e2e"
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert clip_path.exists()
        assert elapsed_ms < 500, (
            f"End-to-end pipeline took {elapsed_ms:.1f}ms > 500ms"
        )


# ---------------------------------------------------------------------------
# 4b) Benchmark marker helpers (run manually with: python -m pytest -v)
# ---------------------------------------------------------------------------

def benchmark_ffmpeg_slicing() -> dict[str, Any]:
    """Standalone benchmark: returns timing dict for FFmpeg slicing."""
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="bench-"))
    mp3 = tmp / "bench.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=10",
         "-c:a", "libmp3lame", "-b:a", "128k", str(mp3)],
        capture_output=True, check=True, timeout=60,
    )
    src = tmp / "src.mp3"
    src.write_bytes(mp3.read_bytes())

    times: list[float] = []
    for i in range(10):
        clip = tmp / f"clip_{i}.mp3"
        t0 = time.perf_counter()
        asyncio.run(slice_audio(src, clip, 0.0, 5.0))
        times.append((time.perf_counter() - t0) * 1000)
        clip.unlink()

    result = {
        "min_ms": min(times),
        "max_ms": max(times),
        "avg_ms": sum(times) / len(times),
        "p95_ms": sorted(times)[int(len(times) * 0.95)],
        "samples": times,
    }
    # Cleanup
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return result


def benchmark_sqlite_throughput() -> dict[str, Any]:
    """Standalone benchmark: concurrent SQLite operations throughput."""
    import importlib
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="bench-sql-"))
    db = tmp / "jobs.db"
    os.environ["VOZONDA_DB"] = str(db)
    import vozonda_api.jobs as jobs_mod
    importlib.reload(jobs_mod)
    from vozonda_api.jobs import JobStore

    store = JobStore()
    # Seed
    for i in range(5):
        store.create(f"seed-{i}", f"http://example.com/{i}")

    async def _run() -> None:
        errors = []
        latencies: list[float] = []

        async def _op(idx: int) -> None:
            try:
                s = JobStore()
                t0 = time.perf_counter()
                s.get(f"seed-{idx % 5}")
                s.create(f"bench-{idx}", f"http://example.com/{idx}")
                latencies.append((time.perf_counter() - t0) * 1000)
            except Exception as e:
                errors.append(e)

        await asyncio.gather(*[_op(i) for i in range(50)])
        return errors, latencies

    errors, latencies = asyncio.run(_run())
    result = {
        "total_ops": len(latencies),
        "errors": len(errors),
        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
        "max_latency_ms": max(latencies) if latencies else 0,
        "errors_detail": errors[:5],
    }
    shutil.rmtree(tmp, ignore_errors=True)
    return result


if __name__ == "__main__":
    print("=== FFmpeg Slicing Benchmark ===")
    r1 = benchmark_ffmpeg_slicing()
    print(f"  avg: {r1['avg_ms']:.1f}ms  min: {r1['min_ms']:.1f}ms  "
          f"max: {r1['max_ms']:.1f}ms  p95: {r1['p95_ms']:.1f}ms")
    print("  PASS" if r1["avg_ms"] < 200 else "  FAIL (>200ms)")

    print("\n=== SQLite Concurrency Benchmark ===")
    r2 = benchmark_sqlite_throughput()
    print(f"  ops: {r2['total_ops']}  errors: {r2['errors']}  "
          f"avg: {r2['avg_latency_ms']:.1f}ms  max: {r2['max_latency_ms']:.1f}ms")
    print("  PASS" if r2["errors"] == 0 else f"  FAIL ({r2['errors']} errors)")