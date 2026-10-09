# Architecture

> Rule zero: the UI knows providers exist, never which one answered.

## Data flow

```
web (Svelte 5)                api (FastAPI)                      backends
─────────────                 ──────────────                     ────────
POST /jobs  ────────────────> orchestrator (pipeline.run_job)
                              ├─ doctor precheck (fail fast)
                              ├─ fetch + extract (httpx, lxml)
                              ├─ _script() over llm_chain():
                              │     1. local vLLM (:30001, OpenAI-compatible)
                              │     2..n VOZONDA_LLM_FALLBACKS, in order
                              ├─ _voice():
                              │     1. qwen3_tts subprocess (TTS_PY +
                              │        render_vozonda.py)
                              │     2..n VOZONDA_TTS_FALLBACKS
                              │        (openai_tts, elevenlabs)
                              ├─ _master(): ffmpeg loudnorm -16 LUFS
                              └─ artifacts under VOZONDA_MEDIA
GET  /jobs/{id}  <─────────── SSE (/jobs/{id}/events), job JSON
GET  /audio/{id}.mp3
POST /clips  ─────────────────> creates MP3 segment from transcript selection
GET  /audio/{job_id}-clip-{turn_start}-{turn_end}.mp3
```

Jobs live in SQLite (`VOZONDA_DB`). Every stage records running/done plus its
output, so a failed job shows exactly where it stopped. There is NO automatic
resume after an api restart yet: in-flight jobs die with the process and stay
failed at their last stage. Tracked in TODO.md; do not trust any doc that
claims crash-resume.

### Audio transcription path

Audio sources (mp3, m4a, wav, ogg, opus) enter via the source tray as uploaded
files, linked URLs, or podcast enclosures. Each download is subject to its own
size cap (`VOZONDA_AUDIO_MAX_BYTES`, default 100 MB); a file exceeding the limit
is refused with an error. If the feed item already carries a
`<podcast:transcript>` tag that value is used directly instead of transcribing.
Otherwise the audio is transcribed by faster-whisper (the Docker image includes
it; a native install needs `uv sync --extra stt`). The raw output is then
punctuated by the local LLM in chunks of about 300 words with a word-for-word
validation: a chunk that changes any original word keeps its raw text; all
others keep the restored version. The resulting text becomes the transcript
source for the script stage.

## Audio Clip Slicing (DUE-020)

The `POST /clips` endpoint extracts precise MP3 segments from a finished episode
using per-turn timestamps (`script[].t0`). This enables social media highlight
clips and teasers directly from transcript line selections. The endpoint:

1. **Accepts:** `job_id`, `turn_start` (index), `turn_end` (index)
2. **Computes bounds** via `compute_clip_bounds()`:
   - Prefers per-line `t0` timestamps when available
   - Falls back to proportional character-length allocation if `t0` is missing
3. **Slices audio** via ffmpeg with 50ms in/out fades at 128k bitrate
4. **Returns:** clip metadata (URL, filename, start/end seconds, duration)

The generated clip is accessible at `/audio/{job_id}-clip-{turn_start}-{turn_end}.mp3`.
Provider-agnostic: works with all TTS engines (qwen_tts, voxtral, piper) because
slicing happens on the finished MP3, not raw voice waves.

## Plugin Architecture & Providers

Vozonda employs a decoupled, capability-based plugin system in `apps/api/src/vozonda_api/plugins/`.
Every backend engine and provider in `vozonda_api/providers/` exposes a frozen `PluginMeta` descriptor.

### Plugin Contracts (`plugins/types.py`)

- `PluginKind`: `INGESTOR`, `SCRIPT_ENGINE`, `TTS_ENGINE`, `AUDIO_FILTER`, `DISTRIBUTION`.
- `Permission`: `NETWORK`, `DISK_READ`, `DISK_WRITE`, `GPU`, `SUBPROCESS`.
- `PluginParam`: Declarative parameter schema (float, int, enum, bool) enabling dynamic UI controls in the Calm Grid frontend without custom component code.
- `PluginMeta`: Frozen descriptor declaring plugin id, kind, human label, version, permissions, capability flags (`supports_instructions`, `supports_emotion_instructions`, `supports_paralinguistic_tags`), UI badge, and install fix hint.

### Protocol Interfaces (`plugins/protocols.py`)

- `TTSPlugin`: Declares `render_audio(lines, workdir, voices, language, gap_ms) -> Path`, `probe() -> bool`, and `speakers() -> list[dict]`.
- `ScriptEnginePlugin`: Declares `generate_script(prompt, model, max_tokens, temperature, timeout) -> tuple[list[dict], str]` and `probe() -> bool`.
- `IngestorPlugin`: Declares `can_handle(url) -> bool` and `fetch(url, max_bytes) -> tuple[str, str, str | None]`.
- `AudioFilterPlugin`: Declares `process(input_path, output_path, params) -> Path` and `probe() -> bool`.

### Registry Lifecycle (`plugins/registry.py`)

`PluginRegistry` acts as the single discovery and health coordination seam:
- **Discovery:** Scans `vozonda_api.providers` at startup via `discover()`. Any module defining `META` is registered automatically.
- **Isolation:** Heavy ML frameworks (PyTorch, ONNX Runtime, NeMo) are never imported during registry discovery or metadata queries. All heavy imports stay inside execution method bodies.
- **Probing & Diagnostics:** Cached probes with a 120-second TTL prevent redundant subprocess execution. `registry.doctor()` aggregates diagnostics across all registered plugins for `/doctor`.
- **Graceful Degradation:** Malformed or broken modules are logged and skipped without blocking the API startup sequence.

Pipeline fallback execution continues to use env-configured chains (`llm_chain()` and `tts_fallbacks()`). Adding a backend means creating one file in `providers/` with a `META` constant and the relevant functions, then adding a chain entry via env.

### Script LLM chain (`llm_chain()`)

1. Local first: `{"name": "local", "base": VOZONDA_LLM_BASE,
   "model": VOZONDA_LLM_MODEL}`.
2. Then every entry of `VOZONDA_LLM_FALLBACKS` (JSON array) in listed order.

`_script()` posts the prompt to candidates until one returns output that
parses as a dialogue JSON array with at least 4 valid lines; otherwise the
next one runs. Non-Anthropic endpoints get `POST {base}/chat/completions`
with an optional `Authorization: Bearer` key. One special path exists: if an
entry's `base` contains `api.anthropic.com`, the call switches to Anthropic's
`/v1/messages` shape (`x-api-key` + `anthropic-version` headers, `content[0].text`
response).

Fallback entry shape:

```json
[
  {"name": "ppq", "base": "https://example-gw/v1", "model": "some-model", "key_env": "PPQ_API_KEY"},
  {"name": "anthropic", "base": "https://api.anthropic.com", "model": "claude-sonnet-4", "key_env": "ANTHROPIC_API_KEY"}
]
```

Entries need `base` + `model`; malformed entries are skipped. `key_env` names
an environment variable whose value is read at call time, never stored in the
DB and never sent anywhere but that provider.

### Voice Engines & Seam Capabilities (`tts_engine`)

Vozonda supports four distinct voice engines, decoupled via a strict capabilities seam (`providers/__init__.py`):

1. **`qwen_tts` (Local GPU, Studio Quality):**
   - **Architecture:** 1.7B parameter autoregressive codec transformer with Flow-Matching decoder.
   - **Execution:** Runs 100% locally on Sparki's GB10 GPU (`render_vozonda.py` subprocess).
   - **Capabilities:** `supports_instructions=True`, `supports_emotion_instructions=True`, `supports_paralinguistic_tags=False`.
   - **Profile:** Broadcast-grade 24 kHz audio fidelity, crystal-clear phonemes, zero telemetry, 100% sovereign offline inference.
2. **`voxtral` (Mistral EU Cloud API, Emotional Realism):**
   - **Architecture:** Multimodal voice foundation model (`voxtral-mini-tts-latest`).
   - **Execution:** Hosted in the EU (Paris) via `mistral_api.key`.
   - **Capabilities:** `supports_instructions=True`, `supports_emotion_instructions=True`, `supports_paralinguistic_tags=True`.
   - **Profile:** NotebookLM-level conversational acting with spontaneous laughter (`[laughs]`), sighing (`[sighs]`), natural breathing, and 30+ native European accent profiles.
3. **`piper` (Local CPU, Multi-Lingual Open Source):**
   - **Architecture:** VITS ONNX neural speech synthesis.
   - **Execution:** Runs 100% on Sparki's CPU (Python `piper-tts` package).
   - **Capabilities:** `supports_instructions=False`, `supports_emotion_instructions=False`, `supports_paralinguistic_tags=False`.
   - **Profile:** Multi-lingual open-source community catalog (Thorsten, Kerstin, Ryan, Siwis, Alan). Ultra-fast, lightweight, 0 MB GPU load.
4. **`kokoro` (Local CPU / ONNX, Expressive Lightweight):**
   - **Architecture:** 82M parameter style-diffusion and transformer speech synthesis model (~350 MB).
   - **Execution:** Runs 100% locally via ONNX Runtime on CPU (~350 MB RAM, 0 VRAM) at 15-25x realtime speed, with HTTP endpoint fallback (`VOZONDA_KOKORO_URL`).
   - **Capabilities:** `supports_instructions=False`, `supports_emotion_instructions=False`, `supports_paralinguistic_tags=False`.
   - **Profile:** Highly expressive American and British English dialogue voices (Bella, Sarah, Nicole, Sky, Adam, Michael, Eric, Emma, Isabella, George, Lewis) with 0 MB VRAM footprint.

### Central Emotion Delivery Resolver (`resolve_emotion_delivery`)

To prevent fragmented emotion logic across script generation and audio synthesis, `resolve_emotion_delivery(engine_id, emotion, style)` provides a single point of truth:
- **LLM Writing Phase:** Generates capability-matched prompt directives (allowing `[laughs]` tags only for Voxtral; strictly prose-only directives for Qwen/Piper/Kokoro to avoid speech artifacts).
- **TTS Synthesis Phase:** Attaches acoustic instructs to `voice.json` only when `supports_emotion_instructions=True`, keeping lightweight engines like Piper and Kokoro clean and deterministic.

### Master Stage: Jingle Beds & Raised-Cosine Ducking (`music.py`)

The master stage stitches synthesized turns into a cohesive podcast episode:
1. **Harmonic Progression:** Procedural Cmaj9/Fmaj7 jazz progressions with soft analog saturation, or automatic custom stems from `media/music/` (`intro.mp3`, `outro.mp3`).
2. **Raised-Cosine S-Curve:** Smooth mathematical volume transition ($0.5 \cdot (1 - \cos(\pi \cdot t))$) down to `-12 dB` ducking gain under dialogue to avoid compressor pumping.
3. **Master Limiter:** Clamped to 0.95 peak ceiling to guarantee 0.0% inter-sample clipping before loudness normalization (-16 LUFS EBU R128).

### Doctor self-heal checks (`doctor.py`)

`run_doctor()` probes the deployment and returns plain-language hints;
`GET /doctor` exposes the result.

| Check | Passes when | Blocking |
|---|---|---|
| `script_llm` | TCP connect + `GET {LLM_BASE}/models` returns 200 | no, if LLM fallbacks are configured |
| `voice_engine` | `VOZONDA_TTS_PY` exists on disk | no, if TTS fallbacks are configured |
| `master_ffmpeg` | ffmpeg binary found in PATH | yes |
| `media_dir` | `VOZONDA_MEDIA` creatable + writable | yes |
| `model_cache` | always (advisory) | never; warns the first TTS job downloads ~4 GB when `VOZONDA_HF_HOME` is missing |

`blocking_problem()` re-runs the checks and downgrades `script_llm` /
`voice_engine` failures to non-blocking "degraded" notes when fallbacks are
configured ("script_llm: local down, will try fallbacks (...)", same for
voice). Every job run starts with this check: a remaining hard problem fails
the job immediately at the fetch stage with the hint as reason, before any
work is wasted.

### Provider list endpoint

`GET /providers` returns four static stage entries (`source_http`,
`script_llm`, `qwen3_tts`, `master_ffmpeg`) each with a `healthy` flag from
`probe()`. A probe passes if the local backend answers OR any fallback is
configured, so a degraded setup still reports usable. There is no per-job
provider selection: chain order comes from env, period.

## Environment variables

Single source of truth: `apps/api/src/vozonda_api/providers/__init__.py`
(paths/chains) and `apps/api/src/vozonda_api/jobs.py` (DB).

| Var | Default | Purpose |
|---|---|---|
| `VOZONDA_NODE_V4V_ADDRESS` | empty | Sovereign host node lightning address for Podcasting 2.0 value splits (locked in UI) |
| `MISTRAL_API_KEY` | empty | API key for Voxtral TTS cloud endpoint (also reads `~/secrets/mistral_api.key`) |
| `VOZONDA_LLM_BASE` | `http://127.0.0.1:30001/v1` | local LLM endpoint, OpenAI-compatible |
| `VOZONDA_LLM_MODEL` | `qwen3.6-35b` | model id sent to the LLM |
| `VOZONDA_LLM_FALLBACKS` | empty | JSON array of LLM fallbacks, see above |
| `VOZONDA_RENDERER` | `qwen_tts` | default TTS engine ("qwen_tts", "voxtral", "piper") |
| `VOZONDA_TTS_PY` | `sys.executable` | python interpreter with active TTS dependencies |
| `VOZONDA_MEDIA` | `media` | artifact directory (WAV/MP3) |
| `VOZONDA_HF_HOME` | `~/.cache/vozonda/hf` | Hugging Face cache for TTS models |
| `VOZONDA_DB` | `data/jobs.db` | SQLite database path |
| `VOZONDA_WATCHLIST_INTERVAL` | `600` | RSS/Nostr background poller check interval in seconds |
| `VOZONDA_WATCHLIST_MAX_NEW` | `3` | Max new episodes rendered per watchlist poll cycle |

Audio routes in `main.py` (`/audio/{job_id}.mp3`, `/og-default.png`) resolve
via `MEDIA_DIR` from providers (DUE-025, fixed).

## Stage inventory (what actually ships)

| Stage | Function | Notes |
|---|---|---|
| Source | `_extract()` | httpx fetch, Nostr NIP-19 resolver (njump.me, habla.news, coracle), lxml cleanup, regex title; pasted text skips network; 60k char ceiling |
| Script | `_script()` over `llm_chain()` | dialog/narration, 17 styles (`styles.py`), engine-tailored directives, tones, languages, tunables via `script.turns_*` settings, strict JSON parse, lint meta |
| Voice | `_voice_local()` + `_voice_cloud()` | engine speaker tables live in `voices.py` (`SPEAKER_TABLES`); `/meta` serves the active engine's voices (Qwen-TTS, Voxtral, Piper, Kokoro) |
| Master | `_master()` | musical intro/outro beds with smooth -12 dB raised-cosine ducking, loudnorm -16 LUFS, TP -1.5, optional atempo, 128k MP3, proportional transcript timings |

All voice engines (Qwen-TTS, Voxtral, Piper, Kokoro) expose unified `PluginMeta` descriptors and are accessible through the plugin registry.

## Prompts and voice settings (settings store)

Editable through `GET /settings` and `PUT /settings/{key}`; values live in the
same SQLite DB. Keys are allowlisted in `settings_store.SETTING_KEYS`,
unknown keys are rejected with 404. Editable today:

- `script.balanced`, `script.narration` and one `script.style.<id>` per
  style: full prompt overrides. Factory defaults ship in code
  (`styles.py`) AND come back through `/settings` defaults, so the gear-menu
  editor always shows the effective text; a DB value wins at run time.
- Voice tuning: `voice.a.timbre`, `voice.b.timbre`, `voice.c.timbre`,
  `voice.solo.timbre`, `voice.dialog.count`, `voice.emotion`,
  `voice.speed`, `voice.gap_ms`.

All 17 style personas, their docs lines and the tunables
(`SCRIPT_PARAMS`) live in `styles.py`; per-style overrides ARE wired:
the allowlist grows with every `script.style.<id>`. A narration override
replaces the whole prompt including the mood tone line. `/meta` also
exposes app version, git rev, limits and the active engines for the FAQ
screen. Legacy jobs recorded with style "default" map to "balanced".

## Sharing & Value Splits (Podcasting 2.0)

- Real and shipped: `GET /e/{job_id}` renders a standalone share page for finished
  jobs: OG/Twitter player meta, teaser blockquote, direct MP3 download.
- Podcasting 2.0 RSS Feed (`/feed.xml`): Implements `<podcast:value>` with Boris-style
  multi-recipient Lightning value splits across `creator`, `source` (original content
  author/Nostr creator), and `app` (sovereign node). Split integer weights and LNURL/Lightning
  addresses are configured via user settings (`feed.creator.*`, `feed.source.*`, `feed.app.*`)
  and rendered cleanly with reactive presets (70/20/10, 90/0/10, 100/0/0, 34/33/33).

## Frontend

- Vite + Svelte 5 runes + TypeScript `strict`. Zero UI frameworks; design
  tokens in plain CSS custom properties (`src/lib/styles/tokens.css`).
- State: small store modules (job, player), no global state library.
  Player wraps native `<audio>`; waveform is canvas over decoded peaks.
- Live updates: SSE (`/jobs/{id}/events`); the client falls back to polling
  `GET /jobs/{id}` when the stream errors.

Stage meta carries the facts the UI shows in "making of": `script.meta.lint`
(quality numbers) and `script.meta.voices` (timbre names actually used),
`extract.meta.source_lang` (stopword heuristic, best effort) and
`extract.meta.truncated_to`, `master.meta.audio` (bytes/kbps/sample rate,
probed lazily on first GET so older jobs fill in). `GET /jobs/{id}` also
reports `write_auth` via `/meta`; when VOZONDA_TOKEN is set, POST /jobs,
DELETE /jobs/{id} and PUT /settings/{key} demand a matching Bearer token.
Audio files are served with etag + accept-ranges; seeking works out of the
box and the audit api suite guards it.
- Performance budget: LCP < 1s local, JS < 60KB gzip initial, no layout
  shift (waveform canvas has reserved aspect box).

## Robustness rules (current truth)

1. Timeouts everywhere: 30s source fetch, 600s script LLM call, 120s per
   cloud TTS turn. No retry-within-backend yet; resilience comes from
   falling down the chain to the next candidate. User-facing failures render
   as checklist items with the reason, never dead ends.
2. Job state machine: `state` in `queued/running/done/failed` plus
   `current_stage` in `fetch/extract/script/voice/master` with per-stage
   running/done markers. Illegal transitions are bugs, not edge cases.
3. DELETE `/jobs/{id}` cancels a running job (DUE-022). Startup reconciliation
   marks interrupted jobs as failed (DUE-028, `store.fail_interrupted()` in
   lifespan). An api restart orphans in-memory SSE listeners; the job row
   keeps its last recorded stage.
4. Sparki mutex applies upstream: only one inference service at a time on the
   grid; the orchestrator queues instead of switching engines mid-job.
5. Secrets come from env vars named in chain configs (`key_env`), never the
   DB, never the frontend bundle.
