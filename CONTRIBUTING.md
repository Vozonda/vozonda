# Contributing to Vozonda

Thanks for your interest! Vozonda is self-hosted, privacy-first, and built for people who want their reading list to talk back.

## Quick Start for Contributors

1. **Clone and setup**
   ```bash
   git clone https://github.com/Vozonda/vozonda.git
   cd vozonda

   # Backend (the tts extra is required for the voice engine)
   cd apps/api && uv sync --extra tts && cd ../..

   # Frontend
   cd apps/web && npm ci && cd ../..
   ```

2. **Run locally**
   ```bash
   # Terminal 1: API
   cd apps/api && uv run --extra tts vozonda-api

   # Terminal 2: Web UI
   cd apps/web && npm run dev
   ```

3. **Verify before committing**
   ```bash
   ./scripts/verify.sh --full
   ```

   Runs ruff, pytest, svelte-check, build and a fresh-worktree check. `--full` adds the browser audit (55 checks, needs the services running on :8787/:4173). Every gate must be green; the pre-push hook runs it again.

## Code Style

- **Python**: ruff on `src`, mypy-clean target. No trailing whitespace.
- **TypeScript/Svelte**: svelte-check strict, zero `any`. Svelte 5 runes, plain CSS custom properties from `apps/web/src/lib/styles/tokens.css` (no UI frameworks, no Tailwind).
- **Commits**: `<scope>: <verb> <object>` (example: `web: add waveform seek`). Pathspec-scoped only (`git commit -- <paths>`), never `git add -A`. The pre-push hook runs every gate; never bypass it with `--no-verify`.
- **Providers are seams**: never import a concrete TTS/LLM backend from UI code or route handlers; go through the registry (`apps/api/src/vozonda_api/providers/`). New voice engines add one entry to `voices.py` SPEAKER_TABLES.
- **Design doc wins**: changes to tokens or screens require a matching `docs/design.md` diff in the same commit.
- **A11y is a gate**: axe violations block the audit like any failing test.

## Troubleshooting

- `voice_renderable` fails in `/doctor`: the venv is missing the voice stack. Run `uv sync --extra tts`. Plain `uv sync` or `uv run` strips it again; the verify gate already passes `--extra tts`.
- First render is slow (minutes): the qwen engine compiles Triton kernels once. Cache lives in `~/.triton/cache` (override with `TRITON_CACHE_DIR`), model weights in `HF_HOME`.
- `PermissionError` under `~/.triton`: a root run once owned the cache dir. `pkexec chown -R $USER:$USER ~/.triton/cache` or point `TRITON_CACHE_DIR` elsewhere.

## Reporting Issues

Before filing a bug report:
1. Run `./scripts/verify.sh --full` to confirm it's not a test failure
2. Check existing issues for duplicates
3. Include: steps to reproduce, expected vs actual behavior, system info (OS, GPU, browser)

## Pull Requests

- Create a branch from `main`
- Make sure `verify.sh --full` passes
- Reference the issue number in the PR description
- Keep PRs small and focused

## Architecture Overview

Vozonda has two main components:
- **API** (`apps/api/`): FastAPI backend, job store, pipeline stages (script -> voice -> master)
- **Web UI** (`apps/web/`): Svelte 5 frontend with the Calm Grid design system

See `docs/architecture.md` for system design details and `docs/design.md` for the UI contract.

## Contributors

Maintained by **cipherfox**. Built on the sovereign grid with paired AI sessions:

| Contributor | Lane |
|---|---|
| Ox Alpha | heavy lifting, audit/QA fixes, voice + feed features |
| Qwen 3.6 | coordination, pipeline and style work |
| Muse Spark 1.2 | web polish, watchlist, perf |
| Nemotron 3 Ultra | reasoning-heavy pipeline work, probes |
| MiMo V2.5 | listening/QA passes |
| Hy3 | research, docs, copy |
| Claude Opus | business plan |
| Claude Sonnet | website copy |
| Gemini 3.7 Flash | OSS hardening (Docker, docs for strangers) |

## Getting Help

- Read `docs/deployment.md` for deployment details
- Check `docs/design.md` for UI/UX specifications
