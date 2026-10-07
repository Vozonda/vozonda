<p align="center">
  <img src="brand/vozonda-lockup-dark.svg#gh-dark-mode-only" alt="Vozonda" width="360">
  <img src="brand/vozonda-lockup.svg#gh-light-mode-only" alt="Vozonda" width="360">
</p>

<h3 align="center">Turn sources into your podcast</h3>

<p align="center">
  <em>Vozonda reads them, voices make waves, you listen.</em>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> •
  <a href="#the-name--brand-story">Brand Story</a> •
  <a href="#use-it-from-your-agent">Agent MCP</a> •
  <a href="#how-it-works">How It Works</a> •
  <a href="#self-hosting">Self-Hosting</a>
</p>

---

### The Name & Brand Story

**Vozonda** unites two concepts: **voz** (*voice*) and **onda** (*wave*).

Written sources become spoken dialogues: voices creating sound waves. You provide articles, PDFs, or research notes; Vozonda reads, structures, and synthesizes them into an engaging two-voice dialogue, published directly to your private RSS podcast feed or Nostr.

- **Self-hosted:** Runs on your own hardware with Docker. Voice generation runs on CPU by default with Kokoro, so no GPU is required.
- **Your own RSS feed:** Episodes publish to a personal podcast feed with chapters and transcripts, compatible with any podcast player.
- **No accounts:** No cloud logins, no telemetry, and no subscriptions. You keep full control of your data and model endpoints.

Ready to try it? Follow the [Docker Quickstart](docs/quickstart.md) to generate your first episode in under 10 minutes.

## Use it from your agent

An agent can create episodes and set up watchlists with schedules, so the feed fills itself.

### Claude Code (CLI)

```bash
claude mcp add vozonda -e VOZONDA_API=http://127.0.0.1:8787 -- /path/to/vozonda/apps/api/.venv/bin/python -m vozonda_api.mcp_server
```

### Other MCP hosts (Hermes Agent, VS Code, Claude Desktop)

```json
{
  "mcpServers": {
    "vozonda": {
      "command": "/path/to/vozonda/apps/api/.venv/bin/python",
      "args": [
        "-m",
        "vozonda_api.mcp_server"
      ],
      "env": {
        "VOZONDA_API": "http://127.0.0.1:8787",
        "VOZONDA_TOKEN": ""
      }
    }
  }
}
```

### HTTP transport

```bash
python -m vozonda_api.mcp_server --http --port 8790 --host 127.0.0.1
```

### Example prompts

- `make a 10-minute episode from https://example.com/article`
- `combine these three links into one episode: https://example.com/part1, https://example.com/part2, https://example.com/part3`
- `watch https://example.com/feed.xml and give me one digest episode every morning at 7, Berlin time`

### Tools

- `create_episode`: create a new podcast episode from sources or pasted text
- `get_episode`: get episode status, metadata and audio URL when done
- `list_episodes`: list recent episodes with id, title, state and created_at
- `list_styles`: list available dialogue styles with a one-line description each
- `get_feed_url`: get the RSS feed URL for all done episodes
- `list_watchlists`: list all watched feeds with their schedule and status
- `create_watchlist`: watch an RSS/Atom feed so new articles become episodes by themselves
- `set_watchlist_schedule`: set or clear when a watched feed renders its digest episode
- `check_watchlist`: poll a watched feed right now and render new entries
- `render_digest`: bundle the newest fresh entries of a watched feed into one episode
- `delete_watchlist`: stop watching a feed

## How it works

```
input            script stage (LLM)                 voice stage (TTS)            output
------           -------------------                -----------------            ------
URL / PDF   -->  extract + ground in the source --> engine per episode      -->  episode (mp3 + opus)
image (OCR)      20 styles (balanced, debate,        (Qwen3-TTS, Kokoro,         chapters, karaoke transcript
YouTube          eli5, true crime, ...)              Piper, Voxtral, ...)        VTT / SRT, share clips
Nostr / text     hook, arc, host personas            music bed + loudness        RSS feed (Podcasting 2.0:
RSS watchlist    digest: N articles -> 1 episode                                 transcript, value / Lightning)
```

## Why Vozonda

NotebookLM made "two AI hosts discuss your sources" a category, and there are
good tools in it (NotebookLM, ElevenLabs GenFM, Wondercraft, Jellypod, Open
Notebook). Vozonda does not claim the idea. It claims the intersection nobody
else covers: **self-hosted and source-grounded, with a real podcast feed as the
output** (RSS with transcripts, chapters and Lightning value splits), fed by
the things you actually follow (RSS watchlists, Nostr) and not only by
uploaded documents.

## Status

Version 0.5.0. Built and used as a **single-user, local-first** app.

- **Exposing it:** bind to localhost (default) or set `VOZONDA_TOKEN`; the
  hosted multi-user mode (Nostr login, per-user data, private feeds) is
  designed but not built yet.
- **Quality:** a benchmark against NotebookLM on five fixed sources is being
  set up in [bench/](bench/README.md); script prompts and TTS settings get
  tuned against it, not against impressions.
- **Voices:** dialogue-native engines (VibeVoice, then Dia and Higgs Audio)
  are being added because turn-by-turn synthesis with fixed pauses is the
  most audible gap to NotebookLM.

<a id="quickstart"></a>
<a id="quickstart-docker"></a>
## Quickstart (Docker)

Before you start, you need an LLM running on your machine. The easiest option is Ollama:

```bash
ollama pull qwen2.5:latest
```

The container reaches your host LLM via `host.docker.internal:11434` (`host.docker.internal` is Docker's hostname for reaching services on the host machine).

Then launch the stack:

```bash
git clone https://github.com/Vozonda/vozonda.git vozonda
cd vozonda
cp .env.example .env
docker compose up -d
```

The first build downloads PyTorch and takes several minutes; subsequent starts take only seconds.

If ports 8787 or 4173 are already in use, edit `.env` and change `VOZONDA_PORT` and `VOZONDA_WEB_PORT` to unused values (e.g. 9787 and 5173).

Open **http://localhost:4173**, paste an article URL or text, and click
**make waves**. Check readiness anytime with `curl http://localhost:8787/doctor`.
For full walkthrough and troubleshooting, see [docs/quickstart.md](docs/quickstart.md).

## Backends (mix and match)

### Script stage (LLM)

Your own OpenAI-compatible endpoint (`VOZONDA_LLM_BASE` / `VOZONDA_LLM_MODEL`):
[Ollama](https://ollama.com/) (`http://127.0.0.1:11434/v1`),
[vLLM](https://github.com/vllm-project/vllm),
[LM Studio](https://lmstudio.ai/) or
[llama.cpp server](https://github.com/ggerganov/llama.cpp). Pick it in
settings as `local`. Cloud fallbacks
(OpenAI, Anthropic, OpenRouter) via `VOZONDA_LLM_FALLBACKS`.

### Voice stage (TTS)

| Engine | Runs on | Speakers | License | Notes |
|---|---|---|---|---|
| Kokoro-82M | local CPU (ONNX) | turn by turn | Apache-2.0 | default; natural voices, English and 7 more languages, 15-25x realtime, no VRAM |
| Piper | local CPU | turn by turn | GPL-3.0 (voices vary) | fallback for German and other languages kokoro lacks (no GPU required) |
| Qwen3-TTS | local GPU | turn by turn | Apache-2.0 | optional GPU engine; 9 voices |
| Voxtral (hosted) | Mistral EU API | turn by turn | Mistral API terms (commercial use allowed) | the engine vozonda uses: 30+ European voices; emotion comes from the reference voice (voice cloning), not from tags |
| Voxtral 4B (open weights) | local GPU | turn by turn | CC BY-NC 4.0 | not used: the public weights omit the reference-audio encoder, so no cloning and none of the hosted emotion; preset voices only, non-commercial |
| VibeVoice-1.5B | local GPU | up to 4 in one pass | MIT | renderer verified, plugin in progress |
| Dia, Higgs Audio v2, Chatterbox | local GPU | 2 / up to 4 / turn by turn | Apache-2.0 / community license / MIT | planned |

Engines are plugins (`apps/api/src/vozonda_api/providers/`). Engines whose
license forbids commercial use are blocked while billing is enabled. Cloud TTS
fallbacks (OpenAI `gpt-4o-mini-tts`, ElevenLabs) via `VOZONDA_TTS_FALLBACKS`.

## Local Development (Without Docker)

### Prerequisites
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Node.js 20+ with npm
- `ffmpeg` in PATH (`sudo apt install ffmpeg` on Ubuntu/Debian)

### Starting the Stack

```bash
# Terminal 1: Backend API (serves http://127.0.0.1:8787)
cd apps/api
uv run vozonda-api

# Terminal 2: Frontend Web UI (serves http://localhost:5173)
cd apps/web
npm install
npm run dev
```

Open **http://localhost:5173**. Vite automatically proxies API requests to the backend.

The production preview (served via `vozonda-web` systemd unit) runs on **:4173**.

## Configuration

All configuration is managed via environment variables or a `.env` file at the
repository root. See [.env.example](.env.example) for the full list with
documentation.

Key variables:

| Variable | Default | Description |
|---|---|---|
| `VOZONDA_LLM_BASE` | `http://127.0.0.1:30001/v1` | Your OpenAI-compatible LLM endpoint (Ollama, vLLM, LM Studio, llama.cpp) |
| `VOZONDA_LLM_MODEL` | `qwen3.6-35b` | Model ID your endpoint serves for script generation |
| `VOZONDA_LLM_FALLBACKS` | `[]` | JSON fallback chain for LLM calls |
| `VOZONDA_TTS_FALLBACKS` | `[]` | JSON fallback chain for cloud TTS |
| `VOZONDA_MEDIA` | `VOZONDA_ROOT/media/vozonda` | Directory for rendered audio and wave peaks |
| `VOZONDA_DB` | `./apps/data/jobs.db` | SQLite database file path |
| `VOZONDA_HOST` | `127.0.0.1` | Bind address of the API; anything but loopback makes `VOZONDA_TOKEN` mandatory |
| `VOZONDA_HF_HOME` | `~/.cache/vozonda/hf` | Hugging Face model cache directory |
| `VOZONDA_TOKEN` | *(empty)* | Bearer token for write API routes. Optional only for the local default; required (503 without it) when `VOZONDA_ENABLE_BILLING=true` or `VOZONDA_HOST` is not a loopback address |
| `VOZONDA_ROOT` | `~/vozonda` | Root directory for vozonda data (set `VOZONDA_ROOT=/data` in production) |
| `VOZONDA_SECRETS_DIR` | `VOZONDA_ROOT/secrets` | Directory for secret files (e.g. `mistral_api.key`) |
| `VOZONDA_MODELS_DIR` | `VOZONDA_ROOT/models` | Directory for model files |


## Repository Structure

```
vozonda/
├── apps/
│   ├── api/        # Python / FastAPI backend: pipeline stages, providers (plugins), job store
│   └── web/        # Svelte 5 (runes) + TypeScript frontend (Calm Grid design)
├── bench/          # quality benchmark against NotebookLM (sources, rubric, runner)
├── docs/           # architecture, design system, deployment, plans, research (index: docs/README.md)
├── scripts/
│   └── verify.sh   # every gate: ruff, pytest, svelte-check, build, fresh-worktree check
├── Dockerfile / Dockerfile.web / docker-compose.yml
└── .env.example
```

## Documentation

The index of every document, marked current or historical: [docs/README.md](docs/README.md).

## Verification & Testing

```bash
./scripts/verify.sh          # ruff, pytest (290+ tests), svelte-check, build, fresh-worktree check
./scripts/verify.sh --full   # plus the browser audit (45+ checks)
```

A pre-push hook runs `verify.sh`; a red gate blocks the push.

## Built with an agent fleet

Much of Vozonda is written by coding agents working in parallel under a
coordinator. The contract they follow is [AGENTS.md](AGENTS.md): hard design
rules, domain boundaries, git discipline and the gates above. Tasks are sized
so an agent can finish one with a clear scope (allowed paths) and a test that
proves it.

<a id="self-hosting"></a>
<a id="production-deployment"></a>
## Self-Hosting & Production Deployment

See [docs/deployment.md](docs/deployment.md) for Ubuntu 24.04+ with a reverse
proxy, TLS and systemd units. Before exposing vozonda beyond localhost, set
`VOZONDA_TOKEN` and read the Status section above.

## Non-Goals

- No telemetry, analytics, or tracking.
- No mandatory third-party accounts or paywalled services.
- Not a generic DAW or audio editor. Vozonda creates structured dialogue episodes.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for reporting issues, submitting PRs and
setting up your dev environment, and [AGENTS.md](AGENTS.md) for the repo
contract. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

MIT License. See [LICENSE](LICENSE).
