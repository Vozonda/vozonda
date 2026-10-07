# Plan: the source tray (VOZONDA-MULTI-SOURCE-TRAY)

> Reworked 2026-10-03 after a design review with the operator. It replaces the first
> draft (a UI-only reskin). Every decision below was made on purpose; do not reopen one
> without asking. Follow-up work (tray templates refilled by a watchlist) is
> VOZONDA-SOURCE-TEMPLATES in the ROADMAP, not part of this plan.

## 1. Goal

vozonda turns a stack of sources into an episode worth publishing. The main user is a show
maker (recurring episodes for listeners); listening for yourself is the fast path.
"Better than NotebookLM" means: every source is checked before you start, nothing is
silently cut, each line of the script says where it came from, and private files stay on
the machine.

## 2. Decisions

| # | Topic | Decision |
|---|---|---|
| 1 | Main user | Show maker; the fast path (one link, go) stays |
| 2 | Uploaded files | Keep only the extracted text, delete the original file right after extraction (also drops PDF/EXIF metadata). The text lives as long as the episode |
| 3 | create variant | Restores the whole tray from the saved per-job source list (saved text, not a re-fetch); each URL card offers "reload". Fixes today's bug: on a digest, variant loads the internal id or the finished transcript as a new source |
| 4 | When a source is read | On add, once. Each source becomes an object (id, kind, title, words, language, text, status). Jobs reference source ids. Unused sources are deleted after 24 h. The fast path extracts silently in the same step |
| 5 | Budget | Need-based: short sources take what they need, the rest goes to long ones. Role per card: **main** (carries the episode, default) or **context** (background, served last). The budget is derived from the active script model's context window minus prompt and output reserve; override in settings. One source of truth: no hardcoded 60_000 (today in `pipeline.py:610` and `main.py:1509`) |
| 6 | Too long | Condense, do not cut: an oversized source is summarised section by section (claims, numbers, quotes) until it fits. The card says "will be condensed, ~1 min extra" |
| 7 | Citations | Per script line: the script model tags a line with the source index(es) it draws on; transitions and interjections carry none. Shown as `[2]` in script review and transcript (hover/tap shows title + snippet). Show notes, RSS and Nostr list the sources: URLs with link, uploads with title only (never content or file name). Invalid indices are dropped, the line stays |
| 8 | Input | One smart field ("paste a link, text, or drop files") plus an upload button. A link becomes a link card; several links (one per line) become several cards; text without a link becomes a note card; files become file cards. **Enter adds, Enter on an empty field starts.** Shift+Enter is a line break. A hint line always says what Enter does next. "make it talk" also takes what is still in the field |
| 9 | Unreadable source | The card turns red with the reason, a concrete next step and "retry". Starting is allowed: the first press shows an inline line at the button ("1 source can't be read · make it talk without it / fix first"), a second Enter confirms. Blocked only when no readable **main** source is left |
| 10 | Limits | Default 10 sources per episode. Settings → sources → new block "source tray": max sources (2-50) and max source length (auto with the computed value shown, or a custom value). The tray shows "3 / 10 sources · 42k of 180k chars". The FAQ shows the real values instead of "about 60,000 characters" (`FaqScreen.svelte:370`) |
| 11 | Templates | Later (VOZONDA-SOURCE-TEMPLATES) |
| 12 | Who builds | See section 5 |
| 13 | Privacy | If the script model is a cloud provider and the tray holds an uploaded source, the tray says "uploaded files will be sent to {provider}" with "use local model for this episode" **preselected**. Condensing of uploaded sources runs on the same model |
| 14 | Done | Comparison test against NotebookLM, see section 6 |

Also settled: the old API fields (`url`, `text`, `digest_sources`) keep working and are mapped
to source objects inside (watchlist, MCP server, API clients do not break). On phones the
upload button opens the file picker; drag and drop is a bonus. Upload titles (first line or
PDF metadata) can be edited on the card before publishing.

## 3. Backend

### Source objects
- `POST /sources` with `{url}` or `{text}`; `POST /sources/upload` (multipart, one file).
  Both return the source object right away with `status: reading`, extraction runs in the
  background; `GET /sources/{id}` polls (or an SSE stream, same pattern as jobs).
- Object: `id, kind (article|pdf|image|youtube|note|file-text), title, words, chars,
  language, status (reading|ready|failed), error {code, hint}, created_at, job_ids`.
  `kind` comes from what the fetcher actually found (content type), never from the URL.
- Upload safety: type sniffed from the bytes (magic numbers), allowed PDF, JPG, PNG, WebP,
  TXT, MD; size cap = `PDF_MAX_BYTES`; pdftotext and vision with timeouts; images
  downscaled before vision; the original file is deleted after extraction, also on failure.
  Writes need `require_write_auth` like every other write.
- Error codes with hints: `paywall`, `pdf_no_text` ("upload the pages as images"),
  `no_subtitles`, `unreachable`, `too_short`, `unsupported_type`, `timeout`.
- Cleanup: sources with no job after 24 h are deleted (same scheduler as `retention.py`);
  a job's sources go when the job or its media goes.

### Jobs
- `POST /jobs` accepts `source_ids` (+ per id `role: main|context`); 1 id = single-source
  run, 2+ = combined dialogue. Script review works in both cases (today a digest without
  `combine` refuses it; that gap closes).
- The job stores its source list: `[{source_id, kind, title, origin_url|null, role, text}]`.
  `GET /jobs/{id}/sources` returns it; `/source/{id}` keeps working for old clients.
- Budget: `source_budget_chars()` = model context window (from the active LLM settings)
  minus prompt, style and output reserve, or the override setting. Need-based allocation,
  main before context. Oversized → condense step (new pipeline stage `condense`, visible
  in the job stages).
- Citations: the script contract gets an optional per-line `src: [int]`. Validation drops
  out-of-range indices. Show notes and feeds list the sources (uploads: title only).
- Privacy: a job with an uploaded source and a cloud script model needs
  `allow_cloud_for_uploads: true`, otherwise it runs on the local model.
- `/meta` exposes `max_sources` and `source_budget_chars` (effective values).

## 4. Web (`App.svelte` + new components)

- `SourceTray.svelte` (list + cards), `SourceInput.svelte` (smart field, upload button,
  drop zone, hint line). Calm Grid tokens, Lucide icons only, no emojis.
- Card: kind badge, title (editable for uploads), words/language, role toggle
  main/context, remove `[x]`, status (reading spinner, red with hint + retry).
- Footer: "3 / 10 sources · 42k of 180k chars", privacy notice when it applies, the
  make-it-talk button with the inline confirm line from decision 9.
- Tray survives a reload (draft in localStorage, ids only; a missing source shows as gone).
- create variant rebuilds the tray from `POST /jobs/{id}/sources/clone` (fresh, ready
  sources with the episode's text and roles).
- Script review and transcript show `[n]` per line.
- A11y: tray is `<ul aria-label="sources">`, every control labelled, focus lands in the
  field on load (`audit.cjs` keeps checking), Enter/Shift+Enter/Escape work as above.

## 5. Who builds what, in order

Status: step 1 landed 2026-10-03 (`sources.py`, endpoints in `main.py`, `tests/test_sources.py`).
Interim behaviour until step 2: a tray of 2+ runs through the digest path as `text:` sources
(no re-fetch); one link keeps the url path for its cover image; roles are stored but not yet
used by the pipeline; the source limit is `sources.MAX_SOURCES` (10); text sources are cut at
100k chars for the digest path. `pipeline._extract` also caps an article at 25k chars by
default: the budget task must replace that cap, not add another.

1. **Coordinator (Claude Code):** this plan; source objects, upload with safety checks,
   per-job source list, cleanup, `source_ids` on jobs with mapping of the old fields.
2. **Fleet chain** (one task each, narrow scope, tests named in the task): budget from
   the model + settings block; need-based allocation and roles; condense stage; citations
   in the script contract, show notes and feeds; privacy rule; variant from the source
   list.
3. **agy:** reviews the fleet commits, then builds the web part with real browser round
   trips (add, fail, retry, role, confirm line, reload, variant, citations).
4. **Coordinator:** final QA (section 6).

## 6. Done = the comparison test

Three reference trays from public sources only, stored as fixtures in the repo:
1. paper (PDF) + article + own note
2. YouTube video + PDF
3. two screenshots + note

The operator runs the same trays through NotebookLM; vozonda runs them too. The operator
listens to both and judges: closer to the sources, nicer to listen to, easier to use.
Measured: time to start, errors caught before start, share of script lines with a
correct citation. Result goes into `docs/archive/internal/quality-log.md`; the test is
repeatable after later changes.

Gates before every push: `cd apps/web && npx svelte-check --threshold error`,
`./scripts/verify.sh`, `node apps/web/scripts/audit.cjs`.
