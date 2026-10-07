#!/usr/bin/env python3
"""Re-run last two failed voice accent probes."""

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api" / "src"))

from vozonda_api.pipeline import _script, _voice_local, _master
from vozonda_api.jobs import JobStore

MEDIA_DIR = Path("/data/media/vozonda")
PROBE_TEXT = """Neue Forschung zeigt, dass KI-Modelle auf lokaler Hardware wie dem NVIDIA DGX Spark effizient laufen können. Dies ermöglicht Privatsphäre und Unabhängigkeit von Cloud-Anbietern. Der Blackwell-Chip mit 121 Gigabyte Unified Memory erlaubt auch große Modelle wie Qwen3-35B lokal zu betreiben. Die Latenz liegt bei unter 125 Millisekunden nach dem Warmup, was echte Interaktivität erlaubt. Das System nutzt vLLM für schnelle Inferenz mit PagedAttention und Continuous Batching. Die Quantisierung auf NVFP4 reduziert den Speicherbedarf auf 50 Gigabyte bei 75 bis 115 Tokens pro Sekunde. Ein Page-Cache-Hijack-Pattern verhindert OOM-Crashes nach längeren Läufen. Die Architektur folgt dem Prinzip: kein Cloud, keine Accounts, die Clanker machen die Arbeit."""


async def run_probe(timbre: str) -> dict:
    probe_id = f"probe-{timbre}"
    workdir = MEDIA_DIR / f".{probe_id}_work"
    workdir.mkdir(parents=True, exist_ok=True)
    os.environ["VOZONDA_VOICE_SOLO_TIMBRE"] = timbre
    try:
        lines, _ = await _script(PROBE_TEXT, "balanced", "narration", "neutral", "de", 1)
        for ln in lines:
            ln["speaker"] = "Narrator"
        while len(lines) < 4:
            lines.append({"speaker": "Narrator", "text": "Weiter geht es mit den Details."})
        wav = await _voice_local(JobStore(), probe_id, lines, workdir, fmt="narration", language="de", style="balanced")
        mp3_path = MEDIA_DIR / f"probe-{timbre}.mp3"
        await _master(wav, probe_id, 1.0)
        final_mp3 = MEDIA_DIR / f"{probe_id}.mp3"
        if mp3_path != final_mp3 and mp3_path.exists():
            mp3_path.rename(final_mp3)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final_mp3)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        duration = float(probe.stdout.strip() or 0)
        return {"timbre": timbre, "duration": round(duration, 1), "status": "ok"}
    except Exception as e:
        return {"timbre": timbre, "duration": 0, "status": f"error: {e}"}
    finally:
        os.environ.pop("VOZONDA_VOICE_SOLO_TIMBRE", None)
        shutil.rmtree(workdir, ignore_errors=True)


async def main():
    for t in ["dylan", "eric"]:
        print(f"Testing {t}...")
        r = await run_probe(t)
        print(f"  -> {r['status']} ({r['duration']}s)")

asyncio.run(main())