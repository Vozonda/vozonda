---
type: repo-contract
scope: vozonda
created: 2026-08-21
updated: 2026-10-07
---

# AGENTS.md - vozonda

> Read this before editing anything in this repo.

## What this is

`vozonda`: self-hosted audio-overview app (article, PDF, image, YouTube, Nostr,
text or RSS -> grounded multi-voice podcast episode -> own RSS feed).
Tagline: *Turn sources into your podcast*.
UI/UX is the product; backends are swappable providers. Design source of
truth: `docs/design.md` ("Calm Grid"). Architecture: `docs/architecture.md`.
Current release milestone: v0.7.2 (dynamic continuous dev build v0.7.2-dev.NNNN;
`apps/api/pyproject.toml`, `apps/web/package.json`, `vozonda_api/version.py`;
`/meta` reports it).

## Repo layout (quick reference)

| Path | Purpose |
|---|---|
| `apps/api/` | Python API (FastAPI), package `vozonda_api` |
| `apps/web/` | Svelte 5 frontend (runes, no framework) |
| `bench/` | Quality benchmark against NotebookLM |
| `docs/` | Design and architecture docs (public) |
| `scripts/` | Tooling: verify.sh, public_scan.py, export_public.sh |
| `.fleet-generated/` | Fleet-generated cache (excluded from public export) |
| `opencode.json` | Per-worktree agent config (excluded from public export) |

## Before you finish (every task, every agent)

- **Stay inside the task's `allowed_paths`.** Any other changed or untracked file fails the task.
- **Create the test file the task names**, at exactly that path (API tests live in `apps/api/tests/`).
- **Run tests the way the gate does:** `cd apps/api && uv run --no-sync --extra tts pytest -q <file>`.
  Plain `python3 -m pytest` from the repo root lacks the API's dependencies.
- **ruff clean:** `cd apps/api && uv run --no-sync --extra tts ruff check src`. Imports isort-sorted
  (`ruff check --select I --fix <file>`), `subprocess.run(...)` with explicit `check=`, no unused imports.
- **No GPU, no model downloads, no network in tests:** mock subprocesses and HTTP; heavy imports
  (torch, transformers, engine packages) only inside `main()` of renderer scripts.
- **Svelte:** `cd apps/web && npx svelte-check --threshold error` clean.

## Hard rules

1. **Design doc wins.** If code and `docs/design.md` disagree, fix the code. Changing tokens or
   screens means updating the doc in the same commit.
2. **No UI framework.** Svelte 5 runes (`$state`, `$derived`, `$props`) + plain CSS custom
   properties. No component libraries, no Tailwind, no icon fonts.
3. **Calm Grid tokens only** (`apps/web/src/lib/styles/tokens.css`): radius strictly 2px
   (`var(--radius)`), never pill buttons; mode toggles use the `.seg` pattern
   (`color-mix(in srgb, var(--green) 12%, var(--paper))`), never solid white/ink blocks on dark
   paper; lowercase UI labels (`podcast`, `key takeaways`, `stream: off`).
4. **No raw emoji** in UI templates or components: `<Icon name="..." />` from
   `apps/web/src/lib/components/Icon.svelte`. The emoji guard in `verify.sh` blocks them.
5. **No em-dashes** in UI copy, docs or commits: periods, commas or hyphens.
6. **Providers are seams.** UI code and route handlers never import a concrete TTS/LLM backend;
   they go through the registry (`providers/`). A new TTS engine is a self-contained provider
   module (`providers/<id>.py` with `META`) plus its renderer script; follow
   `providers/kokoro.py` / `render_kokoro.py`.
   The renderer runs as a plain file (not a module) under the engine's own venv (`RENDER_PY`),
   where httpx does not exist: no relative imports, nothing from `vozonda_api.providers`. Only the
   stdlib-only `vozonda_api.config` may be imported, via sys.path (see `render_chatterbox.py`,
   `render_voxtral.py`). Add a test that runs the script as a file with httpx blocked
   (`test_chatterbox_provider.py`).
7. **TypeScript strict, zero `any`. Python mypy clean** on `apps/api/src`.
8. **A11y is a gate.** axe violations block; the keyboard reaches every action.
9. **Performance budget:** initial JS < 60KB gzip, LCP < 1s local; busting it needs a reason in
   the commit message.
10. **No model names in code (owner rule, 2026-09-28).** Which LLM writes, which model a cloud
    provider runs, and what backs it up change weekly: they are settings (`llm.engine`,
    `llm.nim_model`, `llm.opencode_models`, `llm.backup_engine`) with an env fallback, and the UI
    lists what a provider offers live (`GET /llm/models`). A benchmark result goes into a doc or
    a setting's help text, never into a constant.

## Domain boundaries

| Surface | Notes |
|---|---|
| `apps/web/src/lib/styles/tokens.css` | design tokens; changing them = design.md diff too. One UI mono size: `--ui-size` |
| `apps/web/src/lib/components/*` | one concern per file, runes |
| `apps/api/src/vozonda_api/styles.py` | product vocabulary: 20 styles, docs lines, SCRIPT_PARAMS tunables |
| `apps/api/src/vozonda_api/voices.py` | per-engine speaker tables as plain data; listing voices never imports torch |
| `apps/api/src/vozonda_api/plugins/*` | plugin types, protocols, registry; META imports with zero heavy deps |
| `apps/api/src/vozonda_api/providers/*` | one provider per file + META |
| `apps/api/src/vozonda_api/fetcher.py` | hardened fetching: UA, size cap, retries, SSRF guard on every redirect hop (`guarded_client`) |
| `apps/api/src/vozonda_api/script_lint.py` | deterministic script quality metrics on the job stage meta |
| `apps/web/scripts/audit.cjs` | 45+ check QA suite; must stay green |
| `bench/` | quality benchmark against NotebookLM (see `bench/README.md`) |
| `docs/*` | updated in the same commit as the change they describe |

## Gates and commits

```bash
./scripts/verify.sh          # ruff, pytest, svelte-check, build, fresh-worktree check (CI truth)
./scripts/verify.sh --full   # plus the browser audit
```

A pre-push hook runs `verify.sh`; never bypass it (`--no-verify`) without saying why in the
message. Commit style `<scope>: <verb> <object>` (e.g. `web: add waveform seek`), pathspec-scoped
(`git commit -- <paths>`), never `git add -A`. No Co-Authored-By trailers for GitHub-bound work.

## Cloud agents and GitHub

GitHub `Vozonda/vozonda` is the main repo. Cloud agents and routines follow these rules on top of
everything above:

- **Commit identity:** before the first commit run
  `git config user.name cipherfoxie && git config user.email 271347478+cipherfoxie@users.noreply.github.com`.
  No trailers that name a tool or a session (no `Co-Authored-By`, no `*-Session:` lines).
- **Never push to `main`.** Work on a branch `agent/<short-topic>` and open a pull request. The
  maintainer decides every merge.
- **One topic per PR**, small enough to review in ten minutes. Link the issue (`Closes #N`).
- **Prove it:** run before opening the PR and paste the result lines into the PR body:
  `cd apps/api && uv sync --frozen --extra tts-kokoro --extra tts-piper --extra mcp && uv run ruff check src && uv run pytest -q`
  and `cd apps/web && npm ci && npx svelte-check --threshold error && npm run build`.
- **No GPU here.** Voice engines, local LLMs and real end-to-end runs happen on the maintainer's
  machine. Mock them in tests; say in the PR what could not be checked in the cloud.
- **Public repo hygiene:** `python3 scripts/public_scan.py` must pass. No private hosts, paths, names
  or secrets; no AI attribution lines in commits or PRs (the tool settings in `.claude/settings.json` turn them off).
- Routine prompts live in `.agents/routines/`. Internal planning docs (`docs/archive/`) exist only on
  the maintainer machine; do not recreate them.

## Shared checkout (humans and non-fleet agents)

Fleet agents work in their own git worktree and land through the runner; these rules are for
anyone editing the checkout directly.

1. `git pull --ff-only origin main` before editing; fetch right before every push; on rejection
   retry, never force.
2. Small pathspec-scoped commits; `git status` first; never sweep another agent's files in.
3. Broken WIP blocks everyone's pre-push hook: fix to green or announce it in
   the coordination notes (maintainer machine only).
4. Claim hot files in the coordination notes before touching them (maintainer machine only).
5. Never stash others' files, `--force`, rewrite pushed history.
6. Status flips need evidence (commit hash plus check output).

Services: systemd user units `vozonda-api` (:8787) and `vozonda-web` (:4173, serves `dist/`);
`systemctl --user restart vozonda-api vozonda-web`, then `curl -s http://127.0.0.1:8787/meta`.

## Backlog

Tactical items -> `TODO.md` with stable ids `DUE-NNN`. Strategic -> `docs/archive/internal/plan.md`. No parallel
roadmap files.