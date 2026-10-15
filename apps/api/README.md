<p align="center">
  <img src="https://raw.githubusercontent.com/Vozonda/vozonda/main/brand/vozonda-lockup-dark.svg#gh-dark-mode-only" alt="Vozonda" width="360">
  <img src="https://raw.githubusercontent.com/Vozonda/vozonda/main/brand/vozonda-lockup.svg#gh-light-mode-only" alt="Vozonda" width="360">
</p>

<h3 align="center">Turn sources into your podcast</h3>

<p align="center">
  <em>Vozonda reads them, voices make waves, you listen.</em>
</p>

<p align="center">
  <a href="https://pypi.org/project/vozonda/"><img src="https://img.shields.io/pypi/v/vozonda.svg" alt="PyPI"></a>
  <a href="https://www.npmjs.com/package/vozonda"><img src="https://img.shields.io/npm/v/vozonda.svg" alt="npm"></a>
  <a href="https://github.com/Vozonda/vozonda/pkgs/container/vozonda"><img src="https://img.shields.io/badge/docker-ghcr.io-238636?logo=docker&logoColor=white" alt="GHCR"></a>
  <a href="https://github.com/Vozonda/vozonda/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-4a7300" alt="MIT licence"></a>
  <a href="https://vozonda.com"><img src="https://img.shields.io/badge/website-vozonda.com-1a1815" alt="Website"></a>
</p>

---

## What is Vozonda?

Give Vozonda articles, papers, PDFs, audio files, podcast episodes, screenshots, YouTube videos, RSS feeds or your own notes, and it turns them into the show you want. Audio sources are transcribed locally.

- **Fourteen show formats:** deep dive, quick brief, debate, critique, morning dispatch of your feeds, feature story, explainer, three-voice roundtable, and more.
- **One to three voices, or a single narrator:** in ten languages; translates sources into the language you want to hear.
- **Watchlists:** turn RSS feeds into a daily or weekly digest that fills your feed automatically.
- **Every episode comes with:** chapters, transcripts, takeaways, highlights, and shareable clips; read and fix the script before it is voiced.
- **Self-hosted & private:** runs on your hardware with Docker. Voice generation runs on CPU by default with Kokoro (no GPU required). No cloud logins, no telemetry, and no subscriptions.
- **Personal RSS feed:** publishes episodes to your private podcast feed with chapters and transcripts, compatible with any podcast player, and optionally to Nostr.

---

## Which install do you want?

| You want | Use |
| :--- | :--- |
| **The app** (web UI, feeds, voices, everything) | [Docker](#docker-quickstart) |
| The orchestrator API and pipeline without the web UI, e.g. to drive it from scripts or an agent | this package |

This package is the Python orchestrator only. It does **not** contain the web UI. You talk to it
over its HTTP API (`/docs` lists the routes) or through the MCP server.

## Installation

Needs Python 3.11+, `ffmpeg` on the `PATH`, and an LLM endpoint (a local Ollama or vLLM, or any
OpenAI-compatible API).

```bash
pip install "vozonda[tts-kokoro]"       # orchestrator + Kokoro voices on CPU
# or: uv tool install "vozonda[tts-kokoro]"
```

### Optional extras

| Extra | Adds |
| :--- | :--- |
| `tts-kokoro` | Kokoro voices, CPU-friendly |
| `tts-piper` | Piper voices |
| `stt` | Local transcription of audio sources (faster-whisper) |
| `tts` | All of the above plus Qwen3-TTS (needs torch) |
| `mcp` | MCP server for agents |

Without a TTS extra the server starts, but it cannot voice an episode.

## Usage

```bash
export VOZONDA_LLM_BASE=http://127.0.0.1:11434/v1   # your LLM endpoint
export VOZONDA_LLM_MODEL=qwen2.5:latest
vozonda                                            # or: vozonda-api
```

The API listens on `http://127.0.0.1:8787` (`VOZONDA_HOST`, `VOZONDA_PORT` change it); open
`http://127.0.0.1:8787/docs` for the routes. Every setting is in
[`.env.example`](https://github.com/Vozonda/vozonda/blob/main/.env.example). Before you expose
it beyond this computer, read the
[deployment guide](https://github.com/Vozonda/vozonda/blob/main/docs/deployment.md): remote
requests need the `VOZONDA_TOKEN`.

---

## Docker Quickstart

The full app, with the web UI and all dependencies:

```bash
git clone https://github.com/Vozonda/vozonda.git
cd vozonda
docker compose up -d
```

Prebuilt multi-architecture containers are available from GitHub Container Registry:

```bash
docker pull ghcr.io/vozonda/vozonda:latest
```

---

## Links & Community

- **Website & Audio Samples:** [https://vozonda.com](https://vozonda.com)
- **GitHub Repository:** [https://github.com/Vozonda/vozonda](https://github.com/Vozonda/vozonda)
- **Bug Tracker:** [https://github.com/Vozonda/vozonda/issues](https://github.com/Vozonda/vozonda/issues)
- **License:** [MIT](https://github.com/Vozonda/vozonda/blob/main/LICENSE)
