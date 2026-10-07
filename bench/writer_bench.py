"""Script-writer bench: the same Vozonda prompt through several LLMs.

Builds the exact prompt Vozonda would send (pipeline._script with the LLM call
captured), runs it through each candidate, and scores the script form the
NotebookLM comparison cares about: turn-length spread, quick reactions,
questions and contractions per 1000 words, word budget.

Candidates: "opencode/<model>" runs through the local `opencode` CLI (its
free tier is only allowed from within OpenCode); "qwen" calls the local vLLM.

    apps/api/.venv/bin/python bench/writer_bench.py OUT_DIR MODEL [MODEL ...]
"""

import asyncio
import json
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api/src"))

try:
    from vozonda_api import pipeline  # noqa: E402
    from vozonda_api.providers.script import _parse_first_json_array  # noqa: E402
except ImportError:
    from vozonda_api import pipeline  # noqa: E402
    from vozonda_api.providers.script import _parse_first_json_array  # noqa: E402

SOURCES = {
    "de-podcast": ("https://de.wikipedia.org/wiki/Podcast", "German"),
    "en-nostr": ("https://en.wikipedia.org/wiki/Nostr", "English"),
}
TARGET_MINUTES = 8
CONTRACTION = re.compile(r"\b\w+'(?:s|re|ve|ll|d|t|m|n)\b|\b(?:gibt's|geht's|hab|is'|nich|'n)\b", re.I)


async def build_prompt(url: str, language: str) -> tuple[str, int]:
    title, body, _og = await pipeline._extract(url)
    captured: dict = {}

    async def capture(*, prompt, **kw):
        captured.setdefault("prompt", prompt)
        raise ValueError("captured")

    pipeline.script_call = capture
    try:
        await pipeline._script(body, language=language, title=title, target_minutes=TARGET_MINUTES)
    except Exception:
        pass
    m = re.search(r"Write about (\d+) words", captured["prompt"])
    return captured["prompt"], int(m.group(1)) if m else 0


def run_opencode(model: str, prompt: str) -> str:
    with tempfile.TemporaryDirectory() as d:  # no repo around: the agent has nothing to touch
        p = Path(d) / "prompt.txt"
        p.write_text(prompt)
        try:
            res = subprocess.run(
                ["opencode", "run", "-m", model, "--agent", "plan",
                 "Follow the instructions in the attached file exactly. Answer with the requested output only.",
                 "-f", str(p)],
                cwd=d, capture_output=True, text=True, timeout=1500, check=False)
        except subprocess.TimeoutExpired:
            return "TIMEOUT after 1500 s"
    return re.sub(r"\x1b\[[0-9;]*m", "", res.stdout)


def score(lines: list[dict], planned: int) -> dict:
    words = [len(str(t.get("text", "")).split()) for t in lines]
    total = sum(words) or 1
    text = " ".join(str(t.get("text", "")) for t in lines)
    return {
        "turns": len(lines),
        "words": total,
        "budget_pct": round(100 * total / planned) if planned else None,
        "cv": round(statistics.pstdev(words) / statistics.mean(words), 2) if len(words) > 1 else 0,
        "quick_pct": round(100 * sum(1 for w in words if w <= 5) / len(words)),
        "q_per_1k": round(1000 * text.count("?") / total, 1),
        "contr_per_1k": round(1000 * len(CONTRACTION.findall(text)) / total, 1),
        "speakers": sorted({str(t.get("speaker")) for t in lines}),
    }


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    models = sys.argv[2:]
    prompts = {}
    for sid, (url, lang) in SOURCES.items():
        pf = out / f"{sid}.prompt.txt"
        if pf.exists():
            prompts[sid] = (pf.read_text(), json.loads((out / f"{sid}.meta.json").read_text())["planned"])
        else:
            prompt, planned = asyncio.run(build_prompt(url, lang))
            pf.write_text(prompt)
            (out / f"{sid}.meta.json").write_text(json.dumps({"planned": planned}))
            prompts[sid] = (prompt, planned)
    for model in models:
        for sid, (prompt, planned) in prompts.items():
            tag = f"{model.split('/')[-1]}.{sid}"
            t0 = time.time()
            raw = run_opencode(model, prompt)
            dt = round(time.time() - t0)
            (out / f"{tag}.raw.txt").write_text(raw)
            try:
                content = re.sub(r"<(?:think|thinking)>[\s\S]*?(?:</(?:think|thinking)>|$)", "", raw)
                lines, _ = _parse_first_json_array(content)
                result = {"ok": True, **score(lines, planned)}
                (out / f"{tag}.script.json").write_text(json.dumps(lines, ensure_ascii=False, indent=1))
            except Exception as exc:
                result = {"ok": False, "error": str(exc)[:120]}
            result.update(model=model, source=sid, seconds=dt)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            with (out / "results.jsonl").open("a") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
