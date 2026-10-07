"""bench/report.py - build report.html and judge_pack.json from metrics.json."""

from __future__ import annotations

import json
import operator
import random
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent

# Rubric targets: (operator_name, value)
# value is a number for simple ops, a (lo,hi) tuple for range checks.
_RUBRIC: dict[str, tuple[str, float | tuple[float, float]]] = {
    "turn_len_cv": ("gte", 0.8),
    "short_turn_share": ("range", (0.15, 0.35)),
    "question_share": ("range", (0.12, 0.25)),
    "speaker_balance": ("range", (0.4, 1.0)),
    "bc_distinct": ("gte", 3),
    "repair_count": ("range", (1, 3)),
    "overuse_hits": ("eq", 0),
    "overuse_per_1k_words": ("lte", 1),
    "markup_hits": ("eq", 0),
    "hook_words": ("lte", 40),
    "lufs_i": ("range", (-17, -15)),
    "true_peak": ("lte", -1.5),
    "lra": ("lte", 11),
    "wpm": ("range", (150, 185)),
    "gap_median_ms": ("range", (150, 400)),
    "gap_p90_ms": ("lte", 900),
    "gap_cv": ("gte", 0.5),
    "wer": ("lt", 0.08),
}

# Report-only metrics: never checked, always dash.
_REPORT_ONLY: set[str] = {"words", "turns", "duration_s", "questions_per_1k"}

# Target human labels (from rubric.md)
_LABELS: dict[str, str] = {
    "turn_len_cv": "CV >= 0.8",
    "short_turn_share": "0.15 - 0.35",
    "question_share": "0.12 - 0.25",
    "speaker_balance": "0.4 - 1.0",
    "bc_distinct": ">= 3",
    "repair_count": "1 - 3",
    "overuse_hits": "0",
    "overuse_per_1k_words": "<= 1",
    "markup_hits": "0",
    "hook_words": "<= 40",
    "lufs_i": "-16 LUFS +- 1",
    "true_peak": "<= -1.5 dBFS",
    "lra": "<= 11",
    "wpm": "150 - 185",
    "gap_median_ms": "150 - 400",
    "gap_p90_ms": "< 900",
    "gap_cv": ">= 0.5",
    "wer": "< 0.08",
}


def _style_targets(style: str | None) -> dict[str, tuple[str, float | tuple[float, float]] | None]:
    """Rubric overrides for a style, derived from its rhythm profile (2026-10-02).

    The rubric is written for a balanced two-host talk; judged by it socrates fails for
    A asking only questions and storyteller for A narrating. Each style is measured
    against its own profile instead. Unknown style or no app import: no overrides."""
    if not style:
        return {}
    try:
        try:
            from vozonda_api.rhythm import PROFILES, rhythm_profile_for
        except ImportError:
            from vozonda_api.rhythm import PROFILES, rhythm_profile_for
    except Exception:
        return {}
    p = PROFILES.get(style)
    if p is None and style.startswith("custom_"):
        # custom runs are judged by their rhythm type; a deleted custom
        # style renders with balanced, so it is judged as balanced too
        try:
            try:
                from vozonda_api.custom_styles import get_custom_style
            except ImportError:
                from vozonda_api.custom_styles import get_custom_style

            p = rhythm_profile_for(get_custom_style(style)["rhythm_type"])
        except Exception:
            p = PROFILES.get("balanced")
    if p is None:
        return {}
    main = [sp for h, sp in p.speakers.items() if h != p.rare_third]
    small, large = sorted(main, key=lambda sp: sum(sp.share))[0], sorted(main, key=lambda sp: sum(sp.share))[-1]
    lo = round(max(0.05, (small.share[0] - 0.03) / (large.share[1] + 0.03)), 2)
    out: dict[str, tuple[str, float | tuple[float, float]] | None] = {
        "speaker_balance": ("range", (lo, 1.0)),
        "question_share": ("range", (max(0.0, p.questions[0] - 0.03), p.questions[1] + 0.03)),
        "short_turn_share": ("range", p.quick_share) if p.quick_share is not None else None,
    }
    if p.hard_max is not None and p.hard_max <= 25:  # calm styles: low variation is the point
        out["turn_len_cv"] = None
        out["bc_distinct"] = None
    if "Nobody corrects themselves" in p.rules:
        out["repair_count"] = ("eq", 0)
    if style == "socrates":
        out["bc_distinct"] = None  # A only asks; back-channels are not part of the form
    return out


def _check(metric: str, value: float | None, style: str | None = None) -> bool | None:
    """Return True if within target, False if outside, None for report-only."""
    if value is None or metric in _REPORT_ONLY:
        return None
    overrides = _style_targets(style)
    if metric in overrides:
        entry = overrides[metric]
        if entry is None:
            return None
    else:
        entry = _RUBRIC.get(metric)
    if entry is None:
        return None
    op_name, op_val = entry
    ops = {
        "eq": operator.eq, "lt": operator.lt, "lte": operator.le,
        "gt": operator.gt, "gte": operator.ge, "range": None,
    }
    fn = ops.get(op_name)
    if fn is not None:
        return fn(value, op_val)
    if op_name == "range" and isinstance(op_val, tuple):
        return op_val[0] <= value <= op_val[1]
    return None


def _cell_cls(passed: bool | None, value: float | None) -> str:
    if value is None or passed is None:
        return "c"
    return "r" if passed else "b"


def _mk(passed: bool | None, value: float | None) -> str:
    if value is None or passed is None:
        return "\u2014"
    return "\u2713" if passed else "\u2717"


def read_sources(yaml_path: Path | None = None) -> list[dict[str, str]]:
    path = yaml_path or HERE / "sources.yaml"
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("sources", [])


def _load(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Per-turn metrics need speaker turns; NotebookLM references are transcribed
# without diarization (whisper splits them at pauses into ~30 chunks of ~120
# words), so these numbers are not comparable there and are left out.
_NEEDS_SPEAKERS = {"question_share", "short_turn_share", "speaker_balance",
                   "turn_len_mean", "turn_len_cv", "turns"}


def _flatten(d: dict[str, Any]) -> dict[str, Any]:
    """Metrics as one flat dict; accepts the nested format metrics.py writes."""
    if isinstance(d.get("metrics"), dict):
        return dict(d["metrics"])
    out: dict[str, Any] = {}
    for part in ("script", "audio"):
        out.update({k: v for k, v in (d.get(part) or {}).items() if v is not None})
    for k, v in d.items():
        if k not in ("script", "audio", "source_id", "transcript") and v is not None \
                and not isinstance(v, (dict, list)):
            out[k] = v
    return out


def _questions_per_1k(text: str) -> float | None:
    words = len(text.split())
    return round(text.count("?") / words * 1000, 1) if words else None


def _script_lines(path: Path) -> list[dict[str, Any]]:
    try:
        d = _load(path)
    except (OSError, ValueError):
        return []
    lines = d if isinstance(d, list) else d.get("lines") or d.get("script") or []
    return [ln for ln in lines if isinstance(ln, dict)]


def _group_metrics(runs_dir: Path, refs_dir: Path) -> dict[str, dict[str, Any]]:
    """Return {source_id: {ref_metrics, run_metrics: {run_id: {...}}}}."""
    groups: dict[str, dict[str, Any]] = {}

    def group(sid: str) -> dict[str, Any]:
        return groups.setdefault(sid, {"ref_metrics": {}, "run_metrics": {}})

    for jf in sorted(refs_dir.glob("*.json")) if refs_dir.is_dir() else []:
        if jf.name.endswith(".transcript.json"):
            continue  # read next to its metrics file
        d = _load(jf)
        sid = d.get("source_id") or jf.name.split(".")[0]
        g = group(sid)
        metrics = _flatten(d)
        if "transcript" in d:
            g["ref_transcript"] = d["transcript"]
        if jf.name.endswith(".metrics.json"):
            metrics = {k: v for k, v in metrics.items() if k not in _NEEDS_SPEAKERS}
            tf = jf.with_name(jf.name[: -len(".metrics.json")] + ".transcript.json")
            if tf.is_file():
                text = str(_load(tf).get("text", ""))
                g["ref_transcript"] = text
                metrics["questions_per_1k"] = _questions_per_1k(text)
            if metrics.get("wpm") is None and metrics.get("words") and metrics.get("duration_s"):
                metrics["wpm"] = round(metrics["words"] / metrics["duration_s"] * 60, 1)
        g["ref_metrics"] = metrics

    if runs_dir.is_dir():
        for rd in sorted(runs_dir.iterdir()):
            if not rd.is_dir():
                continue
            for sd in sorted(rd.iterdir()):
                if not sd.is_dir():
                    continue
                mj = sd / "metrics.json"
                if not mj.is_file():
                    continue
                d = _load(mj)
                sid = d.get("source_id", sd.name)
                g = group(sid)
                metrics = _flatten(d)
                transcript = d.get("transcript")
                lines = _script_lines(sd / "script.json")
                if lines:
                    metrics["questions_per_1k"] = _questions_per_1k(" ".join(str(ln.get("text", "")) for ln in lines))
                    transcript = transcript or lines
                g["run_metrics"][rd.name] = metrics
                if transcript:
                    g.setdefault("run_transcripts", {})[rd.name] = transcript
    return groups


def _style_of(run_name: str) -> str | None:
    """Run ids end in the style: 20261002T0636Z-balanced, 20261002T1000Z-true_crime."""
    tail = run_name.rsplit("-", 1)[-1] if "-" in run_name else ""
    return tail or None


def _summary(metrics: dict[str, Any] | None, style: str | None = None) -> str:
    if not metrics:
        return "n/a"
    checkable = [m for m in metrics if _check(m, metrics[m], style) is not None]
    if not checkable:
        return "n/a"
    ok = sum(1 for m in checkable if _check(m, metrics[m], style))
    return f"{ok}/{len(checkable)}"


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def generate_html(
    sources: list[dict[str, str]],
    groups: dict[str, dict[str, Any]],
    run_dirs: list[Path],
    out_dir: Path,
) -> str:
    out = []
    a = out.append

    a("<!DOCTYPE html>")
    a('<html lang="en">')
    a("<head>")
    a('<meta charset="utf-8">')
    a('<meta name="viewport" content="width=390,initial-scale=1">')
    a("<title>Benchmark Report</title>")
    a("<style>")
    a("""*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--paper:#f4f2ed;--ink:#2a2a2a;--grn:#227a39;--amb:#9e6a00;
--grey:#8a8a8a;--brd:#d6d3cd;--rad:2px}
@media(prefers-color-scheme:dark){:root{--paper:#1a1a1e;--ink:#d6d3cd;
--grn:#4caf50;--amb:#ffb300;--grey:#6b6b6b;--brd:#3a3a40}}
html{font-size:14px}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:var(--paper);color:var(--ink);padding:0.75rem;max-width:100%;line-height:1.5}
h1{font-size:1.4rem;margin:0.5rem 0 1rem}
h2{font-size:1.1rem;margin:1.5rem 0 0.5rem}
.sum{display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:1rem}
.badge{display:inline-block;padding:0.25rem 0.6rem;border:1px solid var(--brd);
border-radius:var(--rad);font-size:0.85rem;white-space:nowrap}
table{width:100%;border-collapse:collapse;font-size:0.9rem;margin-bottom:1.5rem;min-width:320px}
thead th{background:color-mix(in srgb,var(--ink) 8%,var(--paper));
text-align:left;padding:0.4rem 0.5rem;border:1px solid var(--brd);
font-weight:600;position:sticky;top:0}
tbody td,.body th{padding:0.3rem 0.5rem;border:1px solid var(--brd);vertical-align:top}
tbody tr:nth-child(even){background:color-mix(in srgb,var(--ink) 3%,var(--paper))}
.r{color:var(--grn)}.b{color:var(--amb)}.c{color:var(--grey)}
.meta{font-size:0.8rem;color:var(--grey);margin-bottom:0.5rem}
audio{max-width:100%;margin-top:0.25rem}
""")
    a("</style></head><body>")
    a("<h1>Benchmark Report</h1>")

    # Summary row
    a('<div class="sum">')
    for rd in run_dirs:
        run_id = rd.name
        all_s = []
        for src in sources:
            sid = src["id"]
            g = groups.get(sid, {})
            rm = g.get("run_metrics", {})
            all_s.append(_summary(rm.get(run_id), _style_of(run_id)))
        a(f'<div class="badge"><strong>{run_id}</strong>: '
          f'{", ".join(all_s)}</div>')
    a("</div>")

    # Per-source tables
    for src in sources:
        sid = src["id"]
        g = groups.get(sid, {})
        ref_m = g.get("ref_metrics", {})
        run_m = g.get("run_metrics", {})

        a(f'<h2 id="src-{sid}">{sid}</h2>')
        if src.get("url"):
            a(f'<p class="meta">Source: <a href="{src["url"]}">{src["url"]}</a></p>')

        # Audio
        ref_audio = next((f for ext in ("mp3", "m4a", "wav", "opus")
                          for f in (out_dir / "references" / f"{sid}.{ext}",) if f.exists()), None)
        if ref_audio is not None:  # NotebookLM downloads are .m4a
            a(f'<p class="meta">Reference audio:</p>'
              f'<audio controls src="references/{ref_audio.name}"></audio>')
        for rd in run_dirs:
            a(f'<p class="meta"><strong>{rd.name}</strong> episode:</p>'
              f'<audio controls src="runs/{rd.name}/{sid}/episode.mp3"></audio>')

        a("<table>")
        a("<thead><tr><th scope=\"col\">Metric</th>")
        if ref_m:
            a('<th scope="col">reference</th>')
        for rd in run_dirs:
            a(f'<th scope="col">{rd.name}</th>')
        a("</tr></thead>")
        a("<tbody>")

        # All metrics from targets plus any seen in data
        seen: set[str] = set(_RUBRIC)
        if ref_m:
            seen.update(ref_m)
        for rm in run_m.values():
            seen.update(rm)

        for metric in sorted(seen):
            lbl = _LABELS.get(metric, "")
            a(f'<tr><th scope="row">{metric}')
            if lbl:
                a(f"<br><small>{lbl}</small>")
            a("</th>")

            # Reference cell
            if ref_m:
                rv = ref_m.get(metric)
                rp = _check(metric, rv)
                a(f'<td class="{_cell_cls(rp, rv)}" '
                  f'aria-label="{_mk(rp, rv)} {metric}={rv}">'
                  f"{_mk(rp, rv)} {rv if rv is not None else ''}"
                  "</td>")

            # Run cells
            for rd in run_dirs:
                rm = run_m.get(rd.name, {})
                val = rm.get(metric)
                p = _check(metric, val, _style_of(rd.name))
                a(f'<td class="{_cell_cls(p, val)}" '
                  f'aria-label="{_mk(p, val)} {metric}={val}">'
                  f"{_mk(p, val)} {val if val is not None else ''}"
                  "</td>")
            a("</tr>")

        a("</tbody></table>")

    a("</body></html>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Judge pack generation
# ---------------------------------------------------------------------------

def generate_judge_pack(
    sources: list[dict[str, str]],
    groups: dict[str, dict[str, Any]],
    run_dirs: list[Path],
    seed: int = 42,
) -> dict[str, Any]:
    """Return {pack, key}. Pack has anonymized labels; key maps label -> identity."""
    rng = random.Random(seed)
    pack: dict[str, Any] = {"sources": []}
    key: dict[str, Any] = {}

    for src in sources:
        sid = src["id"]
        g = groups.get(sid, {})
        run_m = g.get("run_metrics", {})
        ref_m = g.get("ref_metrics", {})
        ref_tr = g.get("ref_transcript", [])
        run_trs = g.get("run_transcripts", {})

        # Build candidate list: (label_source, transcript_or_none)
        candidates: list[dict[str, Any]] = []
        if ref_m:
            candidates.append({"type": "ref", "transcript": ref_tr})
        for rd in run_dirs:
            rid = rd.name
            if rid in run_m:
                candidates.append({"type": "run", "id": rid,
                                   "transcript": run_trs.get(rid, [])})

        rng.shuffle(candidates)

        src_pack: dict[str, Any] = {"source_id": sid}
        if src.get("url"):
            src_pack["url"] = src["url"]
        src_pack["candidates"] = []

        for i, c in enumerate(candidates):
            label = chr(65 + i)  # A, B, C...
            tr = c["transcript"]
            # Flatten transcript to text lines
            if isinstance(tr, list):
                lines: list[str] = []
                for line in tr:
                    if isinstance(line, dict):
                        lines.append(f"{line.get('speaker','')}: {line.get('text','')}")
                    else:
                        lines.append(str(line))
                flat = "\n".join(lines)
            else:
                flat = str(tr)

            src_pack["candidates"].append({
                "label": label,
                "transcript": flat,
            })
            key[label] = {"type": c["type"]}
            if c["type"] == "run":
                key[label]["run_id"] = c["id"]
            key[label]["source_id"] = sid

        pack["sources"].append(src_pack)

    # Sort key for determinism
    packed_key: dict[str, Any] = {}
    for ck in sorted(key.keys()):
        packed_key[ck] = key[ck]

    return {"pack": pack, "key": packed_key}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_report(
    sources: list[dict[str, str]] | None = None,
    runs_dir: Path | None = None,
    refs_dir: Path | None = None,
    out_dir: Path | None = None,
) -> None:
    """Generate report.html and judge_pack.json + judge_key.json."""
    sd = sources or read_sources()
    runs_d = runs_dir or HERE / "runs"
    refs_d = refs_dir or HERE / "references"
    out_d = out_dir or HERE

    groups = _group_metrics(runs_d, refs_d)
    run_dirs: list[Path] = sorted(
        [d for d in runs_d.iterdir() if d.is_dir()] if runs_d.is_dir() else [],  # no runs yet: references only
    )

    html = generate_html(sd, groups, run_dirs, out_d)
    (out_d / "report.html").write_text(html, encoding="utf-8")

    result = generate_judge_pack(sd, groups, run_dirs)
    (out_d / "judge_pack.json").write_text(
        json.dumps(result["pack"], indent=2, ensure_ascii=False),
        encoding="utf-8")
    (out_d / "judge_key.json").write_text(
        json.dumps(result["key"], indent=2, ensure_ascii=False),
        encoding="utf-8")


def main() -> None:  # pragma: no cover
    build_report()


if __name__ == "__main__":  # pragma: no cover
    main()