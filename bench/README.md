# Vozonda quality benchmark

Measures how close Vozonda gets to the NotebookLM Audio Overview on the same
sources, so prompt and TTS changes are judged by numbers and ears instead of
impressions.

- `sources.yaml`: the five fixed sources and what each one stresses.
- `rubric.md`: every metric, its target, and the judged score.
- `references/`: NotebookLM audio for each source (you add these, see below).
- `runs/<run-id>/<source-id>/`: Vozonda output per run (script.json, episode.mp3, metrics.json). Git-ignored.
- `report.html`: the latest comparison, one row per source, Vozonda runs next to the reference.

## Adding the NotebookLM references (manual, once)

For each source in `sources.yaml`:

1. notebooklm.google.com, new notebook, add only this source URL (for `s3-attention-paper` upload the PDF).
2. Audio Overview > Customize: format **Deep Dive** (compared against Vozonda's `balanced` style), length
   **Default**, language **English** (German only for `s4-podcast-de`), sources **1**, and leave the
   focus field **empty** (Vozonda gets no focus instruction either; no suggestion chips).
3. Download the audio and save it as `references/<source-id>.<ext>` (mp3, m4a or wav), e.g. `references/s1-fabrication-gate.m4a`.

The benchmark transcribes references with faster-whisper and scores them with
the same rubric as Vozonda's output.

## Running

    python3 bench/run.py --style balanced          # render all sources through the local Vozonda API
    for d in bench/runs/<run-id>/*/; do python3 bench/metrics.py "$d" --no-wer; done   # per source: script + audio metrics, seconds
    # drop --no-wer when judging a TTS engine: whisper then checks what the voice really said (WER), minutes per episode
    for f in bench/references/*.m4a; do python3 bench/metrics.py "$f"; done   # NotebookLM references (once)
    python3 bench/report.py                        # report.html across runs and references

Whisper runs under `BENCH_WHISPER_PY` (default `python3`, which must have
`faster-whisper` installed).  For a development machine that ships with a local
venv set `BENCH_WHISPER_PY` to that venv's python; in a public checkout the env
var should point at a venv inside the repository or an installed system Python.
