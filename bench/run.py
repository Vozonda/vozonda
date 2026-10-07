"""BENCH-1: benchmark runner (sources -> Vozonda jobs -> runs/)."""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx
import yaml

BENCH_DIR = Path(__file__).resolve().parent
SOURCES_PATH = BENCH_DIR / "sources.yaml"
RUNS_DIR = BENCH_DIR / "runs"


def load_sources(path: str | Path = SOURCES_PATH) -> list[dict]:
    with open(path) as f:
        data = yaml.safe_load(f)
    return data["sources"]


def build_run_id(style: str) -> str:
    now = datetime.datetime.now(datetime.UTC)
    ts = now.strftime("%Y%m%dT%H%MZ")
    return f"{ts}-{style}"


def reference_minutes(source_id: str) -> float | None:
    """Length of the NotebookLM reference for a source, from its metrics file."""
    for f in (BENCH_DIR / "references").glob(f"{source_id}.*.metrics.json"):
        try:
            return round(json.loads(f.read_text())["audio"]["duration_s"] / 60, 1)
        except (OSError, KeyError, ValueError):
            return None
    return None


def build_job_body(source: dict, args: argparse.Namespace) -> dict:
    body = {
        "url": source["url"],
        "style": args.style,
        "hosts": args.hosts,
        "language": source.get("language", "en"),
        "format": "dialog",
        "tone": "neutral",
    }
    # round 3 on: compare at the reference's own length, not Vozonda's default
    minutes = reference_minutes(source["id"]) if getattr(args, "match_reference", False) else None
    if minutes is None:
        minutes = getattr(args, "minutes", None)
    if minutes:
        body["target_minutes"] = minutes
    return body


async def post_job(
    client: httpx.AsyncClient,
    api_url: str,
    token: str,
    body: dict,
) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = await client.post(
        urljoin(api_url, "/jobs"), json=body, headers=headers, timeout=120
    )
    resp.raise_for_status()
    return resp.json()


async def wait_for_job(
    client: httpx.AsyncClient,
    api_url: str,
    token: str,
    job_id: str,
    timeout: int = 45 * 60,
    interval: int = 10,
) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = await client.get(
            urljoin(api_url, f"/jobs/{job_id}"), headers=headers, timeout=30
        )
        resp.raise_for_status()
        job = resp.json()
        if job["state"] in ("done", "failed", "cancelled"):
            return job
        await asyncio.sleep(interval)
    raise TimeoutError(f"job {job_id} timed out after {timeout}s")


async def download_episode(
    client: httpx.AsyncClient,
    api_url: str,
    token: str,
    job_id: str,
    dest: Path,
) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = await client.get(
        urljoin(api_url, f"/audio/{job_id}.mp3"),
        headers=headers, timeout=120, follow_redirects=True,
    )
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)


async def process_source(
    client: httpx.AsyncClient,
    api_url: str,
    token: str,
    source: dict,
    run_id: str,
    args: argparse.Namespace,
) -> dict[str, str]:
    source_id = source["id"]
    out_dir = RUNS_DIR / run_id / source_id
    out_dir.mkdir(parents=True, exist_ok=True)

    body = build_job_body(source, args)
    job = await post_job(client, api_url, token, body)
    job_id = job["id"]

    result: dict[str, str] = {"source_id": source_id, "job_id": job_id}

    try:
        final_job = await wait_for_job(client, api_url, token, job_id,
                                       timeout=int(getattr(args, "job_timeout_min", 45)) * 60)
    except TimeoutError as exc:
        final_job = await client.get(
            urljoin(api_url, f"/jobs/{job_id}"),
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=30,
        )
        final_job = final_job.json()
        final_job["error"] = str(exc)
        final_job["state"] = "failed"

    result["state"] = final_job["state"]
    result["error"] = final_job.get("error", "")

    (out_dir / "job.json").write_text(json.dumps(final_job, indent=2))
    script = final_job.get("script")
    if script:
        (out_dir / "script.json").write_text(json.dumps(script, indent=2))

    if final_job["state"] == "done":
        await download_episode(client, api_url, token, job_id, out_dir / "episode.mp3")

    return result


async def run(args: argparse.Namespace) -> None:
    sources = load_sources()
    if args.sources:
        wanted = set(args.sources.split(","))
        sources = [s for s in sources if s["id"] in wanted]

    run_id = build_run_id(args.style)
    results: list[dict] = []

    for source in sources:
        async with httpx.AsyncClient() as client:
            r = await process_source(client, args.api, args.token, source, run_id, args)
        results.append(r)
        err = f" ({r['error']})" if r.get("error") else ""
        print(f"{r['source_id']}: {r['state']}{err}")

    ok = sum(1 for r in results if r["state"] == "done")
    fail = sum(1 for r in results if r["state"] != "done")
    print(f"run {run_id}: {ok} done, {fail} failed")


def main() -> None:
    parser = argparse.ArgumentParser(description="BENCH-1 benchmark runner")
    parser.add_argument("--style", default="balanced")
    parser.add_argument("--hosts", type=int, default=2)
    parser.add_argument("--sources", default="")
    parser.add_argument("--api", default="http://127.0.0.1:8787")
    parser.add_argument("--token", default=os.environ.get("VOZONDA_TOKEN") or os.environ.get("VOZONDA_TOKEN", ""))
    parser.add_argument("--minutes", type=float, default=None, help="target length for every source")
    parser.add_argument("--match-reference", action="store_true",
                        help="target each source at its NotebookLM reference length (overrides --minutes)")
    parser.add_argument("--job-timeout-min", type=int, default=45, help="how long to wait for one job")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
