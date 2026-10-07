"""bench/metrics.py - Compute rubric A (script) and B (audio) metrics."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> Any:
    """Load a YAML file."""
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def load_phrases_from_md(path: Path) -> list[str]:
    """Load phrases from a markdown table (backtick- or double-quote-wrapped)."""
    if not path.exists():
        return []
    with open(path) as f:
        content = f.read()
    phrases: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        first_cell = stripped.strip("|").split("|", 1)[0]
        matches = re.findall(r"`([^`]+)`", first_cell)
        if matches:
            if len(matches) != 1:
                continue
        else:
            matches = re.findall(r'"([^"]+)"', first_cell)
            if len(matches) != 1:
                continue
        m = matches[0].strip().strip('"').strip("'")
        if m and re.search(r"[A-Za-z]{2}", m) and not m.startswith("-"):
            phrases.append(m)
    return phrases


def _default_kb_dir() -> Path:
    env = os.environ.get("BENCH_KB_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "kb"


def _default_overuse_file() -> Path | None:
    path = os.environ.get("BENCH_OVERUSE_FILE")
    if path:
        return Path(path)
    return Path(__file__).resolve().parent / "overuse-phrases.md"


def compute_script_metrics(
    turns: list[dict[str, str]],
    kb_dir: Path | None = None,
    overuse_file: Path | None = None,
    language: str = "en",
) -> dict[str, Any]:
    """Compute rubric A metrics from a list of turns."""
    metrics: dict[str, Any] = {}
    if not turns:
        return metrics

    _stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off", "over",
        "under", "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "all", "each", "every", "both", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "s", "t", "just", "don", "now",
        "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you",
        "your", "yours", "yourself", "yourselves", "he", "him", "his",
        "himself", "she", "her", "hers", "herself", "it", "its", "itself",
        "they", "them", "their", "theirs", "themselves", "what", "which",
        "who", "whom", "this", "that", "these", "those", "am", "but", "if",
        "or", "because", "until", "while", "about", "against", "and",
    }

    all_words: list[str] = []
    for turn in turns:
        all_words.extend(turn.get("text", "").split())
    metrics["words"] = len(all_words)
    metrics["turns"] = len(turns)

    turn_lengths = [len(t.get("text", "").split()) for t in turns]
    if turn_lengths:
        mean_len = sum(turn_lengths) / len(turn_lengths)
        metrics["turn_len_mean"] = round(mean_len, 2)
        if len(turn_lengths) > 1:
            variance = sum((x - mean_len) ** 2 for x in turn_lengths) / (len(turn_lengths) - 1)
            std_dev = math.sqrt(variance)
            cv = std_dev / mean_len if mean_len else 0
            metrics["turn_len_cv"] = round(cv, 2)
        else:
            metrics["turn_len_cv"] = 0.0
    else:
        metrics["turn_len_mean"] = 0
        metrics["turn_len_cv"] = 0.0

    short_turns = sum(1 for l in turn_lengths if l <= 4)
    metrics["short_turn_share"] = round(short_turns / len(turns), 2) if turns else 0

    question_turns = sum(1 for t in turns if "?" in t.get("text", ""))
    metrics["question_share"] = round(question_turns / len(turns), 2) if turns else 0

    speaker_words: dict[str, int] = {}
    for t in turns:
        speaker = t.get("speaker", "unknown")
        speaker_words[speaker] = speaker_words.get(speaker, 0) + len(t.get("text", "").split())
    if len(speaker_words) >= 2:
        word_counts = list(speaker_words.values())
        max_words = max(word_counts)
        metrics["speaker_balance"] = round(min(word_counts) / max_words, 2) if max_words else 0
    else:
        metrics["speaker_balance"] = None

    kb = kb_dir or _default_kb_dir()
    suffix = f"-{language}" if language != "en" else ""
    bc_path = kb / f"back-channels{suffix}.md"
    if not bc_path.exists():
        warnings.warn(
            f"back-channels file not found: {bc_path}",
            stacklevel=2,
        )
        metrics["bc_distinct"] = None
        metrics["bc_repeat_violations"] = None
        metrics["bare_mhm"] = None
        bc_phrases = []
    else:
        bc_phrases = load_phrases_from_md(bc_path)
        bc_counts: dict[str, int] = {}
        bc_text = " ".join(t.get("text", "") for t in turns).lower()
        for phrase in bc_phrases:
            phrase_lower = phrase.lower()
            if phrase_lower in bc_text:
                bc_counts[phrase_lower] = bc_counts.get(phrase_lower, 0) + 1
        metrics["bc_distinct"] = len(bc_counts)

        bc_repeat_violations = 0
        prev_bc: str | None = None
        for t in turns:
            text_lower = t.get("text", "").lower()
            found_bc: str | None = None
            for phrase in bc_phrases:
                if phrase.lower() in text_lower:
                    found_bc = phrase.lower()
                    break
            if found_bc:
                if found_bc == prev_bc:
                    bc_repeat_violations += 1
                prev_bc = found_bc
        metrics["bc_repeat_violations"] = bc_repeat_violations

        bare_mhm = sum(1 for t in turns if t.get("text", "").strip().lower().rstrip(".") == "mhm")
        metrics["bare_mhm"] = bare_mhm

    repair_path = kb / f"repair-templates{suffix}.md"
    if not repair_path.exists():
        warnings.warn(
            f"repair-templates file not found: {repair_path}",
            stacklevel=2,
        )
        metrics["repair_count"] = None
    else:
        repair_patterns = load_phrases_from_md(repair_path)
        repair_count = 0
        for t in turns:
            text = t.get("text", "")
            for pattern in repair_patterns:
                if re.search(re.escape(pattern), text, re.IGNORECASE):
                    repair_count += 1
                    break
        metrics["repair_count"] = repair_count

    if overuse_file is None:
        overuse_file = _default_overuse_file()
    if overuse_file is None or not overuse_file.exists():
        if overuse_file:
            warnings.warn(
                f"overuse phrase file not found: {overuse_file}",
                stacklevel=2,
            )
        metrics["overuse_hits"] = None
        metrics["overuse_per_1k_words"] = None
    else:
        overuse_phrases = load_phrases_from_md(overuse_file)
        overuse_hits = 0
        for t in turns:
            text = t.get("text", "").lower()
            for phrase in overuse_phrases:
                overuse_hits += text.count(phrase.lower())
        metrics["overuse_hits"] = overuse_hits
        metrics["overuse_per_1k_words"] = round(overuse_hits / metrics["words"] * 1000, 2) if metrics["words"] else None

    markup_re = re.compile(
        r"\[[^\]]+\]|"  # [bracket tags]
        r"\([^\)]+\)|"  # (paren stage directions)
        r"<[A-Za-z][^>]*/?>|"  # <SSML/HTML tags>
        r"\*[^*]+\*"  # *asterisk emphasis*
        r"|[A-Z]{7,}\b",  # ALL-CAPS > 6 letters (not acronyms 2-6)
    )
    count = 0
    for t in turns:
        count += len(markup_re.findall(t.get("text", "")))
    metrics["markup_hits"] = count

    hook_words = 0
    first_claim_found = False
    for t in turns:
        words = t.get("text", "").split()
        for word in words:
            if not first_claim_found and word.lower() not in _stop_words:
                first_claim_found = True
                break
            hook_words += 1
        if first_claim_found:
            break
    metrics["hook_words"] = hook_words

    return metrics


def _parse_ffmpeg_output(output: str) -> dict[str, Any | None]:
    """Parse ffmpeg ebur128 stderr output."""
    result: dict[str, Any | None] = {}
    # ffmpeg's Summary block: "Integrated loudness:\n    I:  -24.9 LUFS" and
    # "True peak:\n    Peak:  -3.4 dBFS". Loudness is negative; the first
    # version matched "Integrated: <digits>" and never found a value.
    integrated_match = re.search(r"Integrated loudness:\s*\n\s*I:\s+(-?[\d.]+)\s+LUFS", output)
    result["lufs_i"] = round(float(integrated_match.group(1)), 2) if integrated_match else None
    true_peak_match = re.search(r"True peak:\s*\n\s*Peak:\s+(-?[\d.]+)\s+dBFS", output)
    result["true_peak"] = round(float(true_peak_match.group(1)), 2) if true_peak_match else None
    summary_match = re.search(r"Summary:.*?LRA:\s+([\d.]+)\s+LU", output, re.DOTALL)
    result["lra"] = round(float(summary_match.group(1)), 2) if summary_match else None
    return result


def compute_audio_metrics(filepath: str) -> dict[str, Any]:
    """Compute rubric B metrics from an audio file."""
    metrics: dict[str, Any] = {}

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", filepath],
            capture_output=True, text=True, check=True,
        )
        metrics["duration_s"] = round(float(result.stdout.strip()), 2)
    except (subprocess.CalledProcessError, ValueError):
        metrics["duration_s"] = None

    try:
        result = subprocess.run(
            ["ffmpeg", "-i", filepath, "-af", "ebur128=peak=true", "-f", "null", "-"],
            capture_output=True, text=True, check=False,
        )
        eb = _parse_ffmpeg_output(result.stderr)
        metrics["lufs_i"] = eb["lufs_i"]
        metrics["true_peak"] = eb["true_peak"]
        metrics["lra"] = eb["lra"]
    except subprocess.CalledProcessError:
        metrics["lufs_i"] = None
        metrics["true_peak"] = None
        metrics["lra"] = None

    try:
        result = subprocess.run(
            ["ffmpeg", "-i", filepath, "-af", "silencedetect=noise=-35dB:d=0.12", "-f", "null", "-"],
            capture_output=True, text=True, check=False,
        )
        gaps: list[float] = []
        silence_start: float | None = None
        for line in result.stderr.splitlines():
            if "silence_start" in line:
                match = re.search(r"silence_start:\s+([\d.]+)", line)
                if match:
                    silence_start = float(match.group(1))
            elif "silence_end" in line:
                match = re.search(r"silence_end:\s+([\d.]+)", line)
                if match and silence_start is not None:
                    end_time = float(match.group(1))
                    gaps.append((end_time - silence_start) * 1000)
                    silence_start = None
        if gaps:
            gaps.sort()
            metrics["gap_median_ms"] = round(gaps[len(gaps) // 2], 2)
            p90_idx = int(len(gaps) * 0.9)
            if p90_idx >= len(gaps):
                p90_idx = len(gaps) - 1
            metrics["gap_p90_ms"] = round(gaps[p90_idx], 2)
            if len(gaps) > 1:
                mean_gap = sum(gaps) / len(gaps)
                variance = sum((x - mean_gap) ** 2 for x in gaps) / (len(gaps) - 1)
                std_dev = math.sqrt(variance)
                metrics["gap_cv"] = round(std_dev / mean_gap, 2) if mean_gap else 0.0
            else:
                metrics["gap_cv"] = 0.0
        else:
            metrics["gap_median_ms"] = None
            metrics["gap_p90_ms"] = None
            metrics["gap_cv"] = 0.0
    except subprocess.CalledProcessError:
        metrics["gap_median_ms"] = None
        metrics["gap_p90_ms"] = None
        metrics["gap_cv"] = 0.0

    return metrics


# Transcription runs in a separate interpreter that has faster-whisper.
# Until 2026-09-23 this called 'python -m small ...', which is no program;
# the error was swallowed and no transcript (so no wpm, WER or reference
# script metrics) was ever produced.
_WHISPER_CODE = """
import json, sys
from faster_whisper import WhisperModel
model = WhisperModel("small", device="cpu", compute_type="int8")
segments, info = model.transcribe(sys.argv[1], word_timestamps=True)
texts, words = [], []
for seg in segments:
    texts.append(seg.text.strip())
    for w in seg.words or []:
        words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
json.dump({"text": " ".join(texts), "word_timestamps": words, "language": info.language},
          open(sys.argv[2], "w"))
"""


def compute_whisper_metrics(filepath: str, whisper_py: str | None = None) -> dict[str, Any]:
    """Transcribe with faster-whisper: {text, word_timestamps, language} (cached)."""
    if whisper_py is None:
        whisper_py = os.environ.get("BENCH_WHISPER_PY", sys.executable)
    transcript_path = filepath + ".transcript.json"
    if not Path(transcript_path).exists():
        try:
            res = subprocess.run(
                [whisper_py, "-c", _WHISPER_CODE, filepath, transcript_path],
                capture_output=True, text=True, check=False, timeout=3600,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            print(f"whisper failed for {filepath}: {exc}", file=sys.stderr)
            return {}
        if res.returncode != 0:
            print(f"whisper failed for {filepath}: {res.stderr.strip()[-400:]}", file=sys.stderr)
            return {}
    try:
        with open(transcript_path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def compute_wer(script_text: str, transcript_text: str) -> float:
    """Compute Word Error Rate using Levenshtein distance."""

    def preprocess(text: str) -> list[str]:
        text = text.lower()
        text = re.sub(r"[^\w\s]", "", text)
        return text.split()

    script_words = preprocess(script_text)
    transcript_words = preprocess(transcript_text)
    if not script_words and not transcript_words:
        return 0.0
    if not script_words or not transcript_words:
        return 1.0

    m, n = len(script_words), len(transcript_words)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if script_words[i - 1] == transcript_words[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return min(dp[m][n] / m, 1.0)


def split_transcript_into_turns(
    whisper_data: dict[str, Any], gap_ms: float = 700,
) -> list[dict[str, str]]:
    """Split a whisper transcript into turns using word timestamps and gaps."""
    if not whisper_data:
        return [{"speaker": "unknown", "text": ""}]

    word_timestamps = whisper_data.get("word_timestamps", [])
    if not word_timestamps:
        text = whisper_data.get("text", "")
        return [{"speaker": "unknown", "text": text}]

    turns: list[dict[str, str]] = []
    current_words: list[str] = []
    prev_end = 0.0

    for wt in word_timestamps:
        start = wt.get("start", 0.0)
        end = wt.get("end", 0.0)
        word = wt.get("word", wt.get("text", ""))
        if start - prev_end > gap_ms / 1000.0 and current_words:
            turns.append({"speaker": "unknown", "text": " ".join(current_words)})
            current_words = []
        current_words.append(word)
        prev_end = end

    if current_words:
        turns.append({"speaker": "unknown", "text": " ".join(current_words)})

    return turns


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Compute bench metrics")
    parser.add_argument("input", help="Path to run directory or reference file")
    parser.add_argument("--kb-dir", default=None, help="Path to KB directory")
    parser.add_argument("--overuse-file", default=None, help="Path to overuse phrases file")
    parser.add_argument("--language", default=None, help="Language code (en, de, ...); read from job.json if omitted")
    parser.add_argument("--no-wer", action="store_true",
                        help="skip whisper for a Vozonda run: wpm from the script, no WER "
                             "(WER only matters when judging a TTS engine, not a prompt change)")
    args = parser.parse_args()

    input_path = Path(args.input)
    kb_dir = Path(args.kb_dir) if args.kb_dir else None
    overuse_file = Path(args.overuse_file) if args.overuse_file else None
    language = args.language or "en"
    metrics: dict[str, Any] = {}

    if input_path.is_dir():
        script_path = input_path / "script.json"
        audio_path = input_path / "episode.mp3"
        whisper_data: dict[str, Any] = {}

        # Try reading language from job.json in the run dir
        if language == "en":
            job_path = input_path / "job.json"
            if job_path.exists():
                try:
                    with open(job_path) as f:
                        job = json.load(f)
                    if job.get("language"):
                        language = job["language"]
                except (OSError, json.JSONDecodeError):
                    pass

        if script_path.exists():
            with open(script_path) as f:
                turns = json.load(f)
            metrics["script"] = compute_script_metrics(turns, kb_dir, overuse_file, language)

        if audio_path.exists():
            metrics["audio"] = compute_audio_metrics(str(audio_path))
            duration = metrics["audio"].get("duration_s")
            # the script is what was voiced: pace needs no transcription
            if script_path.exists() and duration and duration > 0:
                words = sum(len(str(t.get("text", "")).split()) for t in turns)
                metrics["wpm"] = round(words / duration * 60, 2)
            whisper_data = {} if args.no_wer else compute_whisper_metrics(str(audio_path))
            if whisper_data and script_path.exists():
                script_text = " ".join(t.get("text", "") for t in turns)
                transcript_text = whisper_data.get("text", "")
                metrics["wer"] = compute_wer(script_text, transcript_text)

        output_path = input_path / "metrics.json"
        with open(output_path, "w") as f:
            json.dump(metrics, f, indent=2)

    elif input_path.is_file():
        audio_path = input_path
        metrics["audio"] = compute_audio_metrics(str(audio_path))
        whisper_data = compute_whisper_metrics(str(audio_path))
        if whisper_data:
            turns = split_transcript_into_turns(whisper_data)
            metrics["script"] = compute_script_metrics(turns, kb_dir, overuse_file, language)
            metrics["script"]["speaker_balance"] = None
            metrics["wer"] = None
        # Never write into the input: for a reference file the metrics go next
        # to it as <name>.metrics.json. The first version wrote the JSON over
        # the audio file itself and destroyed a NotebookLM reference.
        output_path = input_path.with_name(input_path.name + ".metrics.json")
        with open(output_path, "w") as f:
            json.dump(metrics, f, indent=2)

    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
