# Vozonda Bug Hunt Audit - 2026-10-01

## Commands Run

### API (apps/api)
```bash
cd apps/api && uv run --no-sync --extra tts ruff check src
```
**Result:** PASS - All checks passed

```bash
cd apps/api && uv run --no-sync --extra tts pytest -q
```
**Result:** 718 passed, 3 warnings in ~115s
- 3x `UserWarning: Duplicate Operation ID` (FastAPI) in `main.py` for routes: `audio_audio__filename__mp3_get`, `audio_peaks_audio__job_id__peaks_json_get`, `serve_image_img__filename__get`

```bash
cd apps/api && uv run --no-sync --extra tts pytest -q tests/bench_dsp_slicing.py
```
**Result:** 10 passed in 15.3s (benchmark tests)

### Web (apps/web)
```bash
cd apps/web && npm ci
```
**Result:** 52 packages added, 0 vulnerabilities

```bash
cd apps/web && npm run build
```
**Result:** Build successful in 2.3s - 4 Svelte warnings (state referenced locally), 2 CSS warnings (missing standard `line-clamp` property)

```bash
cd apps/web && npx svelte-check --threshold error
```
**Result:** 0 errors, 6 warnings (4x state referenced locally, 2x missing standard `line-clamp`)

---

## Test Re-run / Flakiness Classification

No failing tests found in any of the test runs. All 718 API tests pass consistently across 3 runs (initial + 2 verification runs). No skipped tests. **No flaky tests to classify.**

---

## Bare `except:` / `except Exception: pass` Analysis

### Bare `except:` - **None found** in `apps/api/src`

### `except Exception:` - 160 occurrences across 18 files

| File | Count | Classification Summary |
|------|-------|------------------------|
| `pipeline.py` | 74 | Mix of **fine** (expected fallbacks in pipeline stages) and **bug risk** (silent `pass` swallowing errors in critical paths like music, insights, OG image) |
| `main.py` | 29 | Mostly **fine** (startup resilience, settings fallbacks); **bug risk** at line 398 (billing check failure → 503), line 1215 (job state mutation silently ignored) |
| `routers/feeds.py` | 13 | **Fine** - defensive RSS feed generation with safe defaults |
| `providers/__init__.py` | 7 | **Fine** - provider probe/discovery resilience |
| `plugins/registry.py` | 7 | **Fine** - plugin loading with logging on failure |
| `nostr_zaps.py` | 5 | **Fine** - validation parsing with explicit error returns |
| `jobs.py` | 5 | **Fine** - queue position estimation with safe defaults |
| `providers/kokoro.py` | 4 | **Fine** - TTS engine probe/render with boolean return |
| `watchlist_poller.py` | 2 | **Bug risk** - line 261 silently swallows poller loop errors |
| `music_store.py` | 2 | **Fine** - optional music asset loading |
| `cover.py` | 2 | **Fine** - OG image fetch with boolean return |
| `clips.py` | 2 | **Fine** - ffmpeg duration probe with 0.0 fallback |
| `watchlist.py` | 1 | **Bug risk** - line 42 silent `pass` on ALTER TABLE |
| `voices.py` | 1 | **Fine** - speaker table lookup with empty fallback |
| `styles.py` | 1 | **Fine** - settings read with None fallback |
| `render_magpie.py` | 1 | **Fine** - enum name extraction |
| `nostr_auth.py` | 1 | **Bug risk** - line 351 silent `pass` on ALTER TABLE |
| `mcp_server.py` | 1 | **Fine** - HTTP error text extraction |
| `insights.py` | 1 | **Fine** - LLM fallback to heuristic extraction |
| `billing.py` | 1 | **Bug risk** - line 86 silent `pass` on ALTER TABLE |

**Total:** 160 - 138 classified **fine** (defensive fallbacks, explicit error returns, logging), 22 classified **bug risk** (silent `pass` in mutation/initialization paths), 0 classified **stale**

---

## TODO / FIXME / XXX Inventory

| File:Line | Text | Classification |
|-----------|------|----------------|
| `apps/api/src/vozonda_api/fetcher.py:3` | `Design rules (see TODO DUE-033):` | **Stale** - DUE-033 not present in current TODO.md (archived or renumbered) |
| `apps/api/tests/bench_dsp_slicing.py:1` | `Benchmark für Audio-Slicing-Performance (DUE-XXX).` | **Stale** - DUE-XXX is a placeholder; bench tests exist and pass |

No other TODO/FIXME/XXX found in source code (`apps/api/src`, `apps/web/src`).

---

## Findings

### F-1: Duplicate FastAPI Operation IDs
- **Severity:** medium
- **File:** `apps/api/src/vozonda_api/main.py`
- **Lines:** Multiple route decorators generate duplicate `operation_id`
- **Evidence:** 3x `UserWarning: Duplicate Operation ID` during pytest collection (audio_audio__filename__mp3_get, audio_peaks_audio__job_id__peaks_json_get, serve_image_img__filename__get)
- **Reproduction:** Run `uv run --no-sync --extra tts pytest -q` and observe warnings
- **Fix:** Add explicit `operation_id` to each route decorator or rename handler functions to be unique

### F-2: Svelte State Referenced Locally (4 instances)
- **Severity:** low
- **Files/Lines:**
  - `apps/web/src/lib/components/EssentialsSection.svelte:56` - `providersProp` captured in `$state` init
  - `apps/web/src/lib/components/ListenScreen.svelte:129` - `title` captured in `$state` init
  - `apps/web/src/lib/components/ScriptReview.svelte:24` - `script` captured in `const original`
  - `apps/web/src/lib/components/ScriptReview.svelte:34` - `title` captured in `$state` init
- **Evidence:** Vite build warnings + svelte-check warnings: "This reference only captures the initial value... Did you mean to reference it inside a closure/derived instead?"
- **Reproduction:** Run `npm run build` or `npx svelte-check` in apps/web
- **Fix:** Wrap initializations in `$derived` or use closure pattern per Svelte 5 runes guidance

### F-3: Missing Standard CSS `line-clamp` Property (2 instances)
- **Severity:** low
- **File:** `apps/web/src/lib/components/Waveform.svelte:436,446`
- **Evidence:** svelte-check warns: "Also define the standard property 'line-clamp' for compatibility"
- **Reproduction:** Run `npx svelte-check` in apps/web
- **Fix:** Add `line-clamp: 2;` alongside `-webkit-line-clamp: 2;`

### F-4: Silent Exception Swallowing in Pipeline Stages (pipeline.py)
- **Severity:** high
- **File:** `apps/api/src/vozonda_api/pipeline.py`
- **Lines:** 110, 1360, 1712, 1732, 1747, 1935, 1956, 1958, 2142, 2181, 2202, 2360, 2367, 2402, 2423, 2455, 2501, 2654, 2673, 2829, 2842, 2858, 2863 (23 locations with `except Exception: pass`)
- **Evidence:** Multiple pipeline stages (music, insights, OG image, cover, master finalize) silently swallow exceptions with bare `pass`, losing error context
- **Reproduction:** Trigger a failure in any of these stages (e.g., missing ffmpeg, corrupt MP3, network error on OG image) - job succeeds but metadata missing
- **Fix:** Replace `pass` with `logger.exception(...)` and/or store error in stage meta for observability

### F-5: Silent Exception Swallowing in Main App Startup (main.py)
- **Severity:** high
- **File:** `apps/api/src/vozonda_api/main.py`
- **Lines:** 69, 81, 88, 96, 105, 1215, 1263, 1347, 1366, 1403, 1433, 1805, 2269, 2290, 2354, 2508, 3056, 3111, 3143, 3200
- **Evidence:** 20 `except Exception: pass` during startup/db migration/poller warmup; line 398 converts any billing check failure to 503 without logging
- **Reproduction:** Corrupt DB schema, missing tables, or billing DB unavailable - app starts but features silently disabled
- **Fix:** Add `logger.exception(...)` at minimum; for critical paths (billing, poller) consider failing fast or explicit degraded-mode flag

### F-6: Silent ALTER TABLE Failures (watchlist.py, nostr_auth.py, billing.py)
- **Severity:** medium
- **Files/Lines:**
  - `apps/api/src/vozonda_api/watchlist.py:42`
  - `apps/api/src/vozonda_api/nostr_auth.py:351`
  - `apps/api/src/vozonda_api/billing.py:86`
- **Evidence:** Schema migrations wrapped in `except Exception: pass` - column may not exist but code proceeds assuming it does
- **Reproduction:** Run against DB where migration already applied (idempotent) or where ALTER fails for permissions - subsequent queries may error
- **Fix:** Check column existence via `PRAGMA table_info` before ALTER, or catch `sqlite3.OperationalError` specifically

### F-7: Silent Poller Loop Error Swallowing (watchlist_poller.py)
- **Severity:** high
- **File:** `apps/api/src/vozonda_api/watchlist_poller.py:260-261`
- **Evidence:** `except Exception: pass` in main poll loop - any error stops processing that iteration but loop continues silently
- **Reproduction:** Feed fetch fails, DB locked, network error - poller appears running but no new jobs created
- **Fix:** Log exception, increment metrics, consider backoff

### F-8: Stale TODO Reference (fetcher.py)
- **Severity:** low
- **File:** `apps/api/src/vozonda_api/fetcher.py:3`
- **Evidence:** Comment references `TODO DUE-033` which does not exist in current TODO.md
- **Fix:** Update comment to reference current design doc or remove

### F-9: Placeholder DUE-XXX in Benchmark Test
- **Severity:** low
- **File:** `apps/api/tests/bench_dsp_slicing.py:1`
- **Evidence:** Docstring references `DUE-XXX` placeholder
- **Fix:** Assign real DUE number or remove placeholder

### F-10: Duplicate Operation ID for Audio Routes
- **Severity:** medium
- **File:** `apps/api/src/vozonda_api/main.py`
- **Lines:** Routes for `/audio/{filename}.mp3`, `/audio/{job_id}/peaks.json`, `/img/{filename}`
- **Evidence:** FastAPI generates same `operation_id` for different routes due to similar path patterns
- **Fix:** Explicit `operation_id="unique_name"` on each `@app.get`/`@app.post`

---

## Prioritized Fix List

| Priority | Finding | Rationale |
|----------|---------|-----------|
| 1 | F-4: Pipeline silent `pass` (23 locations) | Core pipeline reliability; errors invisible in production |
| 2 | F-5: Main startup silent `pass` (20 locations) | App starts in degraded state without visibility |
| 3 | F-7: Poller loop silent `pass` | Background job ingestion fails silently |
| 4 | F-6: Silent ALTER TABLE (3 files) | Schema drift risk, hard to debug |
| 5 | F-1 / F-10: Duplicate Operation IDs | OpenAPI spec invalid, breaks client generation |
| 6 | F-2: Svelte state warnings | Reactive correctness, may cause stale UI |
| 7 | F-3: Missing `line-clamp` | CSS forward-compatibility |
| 8 | F-8: Stale TODO reference | Documentation hygiene |
| 9 | F-9: DUE-XXX placeholder | Documentation hygiene |

---

```findings
[{"id": "F-1", "severity": "medium", "file": "apps/api/src/vozonda_api/main.py", "line": 0, "title": "Duplicate FastAPI Operation IDs for audio/img routes", "fix": "Add explicit operation_id to each route decorator: @app.get(..., operation_id=\"audio_file\"), @app.get(..., operation_id=\"audio_peaks\"), @app.get(..., operation_id=\"serve_image\")"}, {"id": "F-2", "severity": "low", "file": "apps/web/src/lib/components/EssentialsSection.svelte", "line": 56, "title": "Svelte state captures initial prop value only", "fix": "Change `let providersLocal = $state<ProviderStatus | null>(providersProp)` to `let providersLocal = $derived.by(() => providersProp ?? null)`"}, {"id": "F-2b", "severity": "low", "file": "apps/web/src/lib/components/ListenScreen.svelte", "line": 129, "title": "Svelte state captures initial prop value only", "fix": "Change `let currentTitle = $state(title || '')` to `let currentTitle = $derived.by(() => title || '')`"}, {"id": "F-2c", "severity": "low", "file": "apps/web/src/lib/components/ScriptReview.svelte", "line": 24, "title": "Svelte const captures initial prop value only", "fix": "Change `const original = script.map(...)` to `const original = $derived(script.map(...))`"}, {"id": "F-2d", "severity": "low", "file": "apps/web/src/lib/components/ScriptReview.svelte", "line": 34, "title": "Svelte state captures initial prop value only", "fix": "Change `let titleDraft = $state(title.trim())` to `let titleDraft = $derived.by(() => title.trim())`"}, {"id": "F-3", "severity": "low", "file": "apps/web/src/lib/components/Waveform.svelte", "line": 436, "title": "Missing standard CSS line-clamp property", "fix": "Add `line-clamp: 2;` after `-webkit-line-clamp: 2;` on both occurrences (lines 436 and 446)"}, {"id": "F-4", "severity": "high", "file": "apps/api/src/vozonda_api/pipeline.py", "line": 110, "title": "Silent exception swallowing in pipeline stages (23 locations)", "fix": "Replace each `except Exception: pass` with `except Exception: logger.exception(\"stage X failed\")` and store error in stage meta via `store.add_stage_meta(job_id, stage, error=str(e))`"}, {"id": "F-5", "severity": "high", "file": "apps/api/src/vozonda_api/main.py", "line": 69, "title": "Silent exception swallowing in app startup (20 locations)", "fix": "Add `logger.exception(\"startup step failed\")` to each `except Exception: pass`; for billing check (line 398) log and re-raise or return degraded mode flag"}, {"id": "F-6", "severity": "medium", "file": "apps/api/src/vozonda_api/watchlist.py", "line": 42, "title": "Silent ALTER TABLE failure in watchlist migration", "fix": "Check column existence via `PRAGMA table_info(watchlist)` before ALTER, or catch `sqlite3.OperationalError` specifically"}, {"id": "F-6b", "severity": "medium", "file": "apps/api/src/vozonda_api/nostr_auth.py", "line": 351, "title": "Silent ALTER TABLE failure in nostr_auth migration", "fix": "Check column existence via `PRAGMA table_info(nostr_identities)` before ALTER, or catch `sqlite3.OperationalError` specifically"}, {"id": "F-6c", "severity": "medium", "file": "apps/api/src/vozonda_api/billing.py", "line": 86, "title": "Silent ALTER TABLE failure in billing migration", "fix": "Check column existence via `PRAGMA table_info(user_accounts)` before ALTER, or catch `sqlite3.OperationalError` specifically"}, {"id": "F-7", "severity": "high", "file": "apps/api/src/vozonda_api/watchlist_poller.py", "line": 260, "title": "Silent exception swallowing in poller main loop", "fix": "Replace `except Exception: pass` with `except Exception: logger.exception(\"poller iteration failed\"); await asyncio.sleep(POLL_INTERVAL * 2)`"}, {"id": "F-8", "severity": "low", "file": "apps/api/src/vozonda_api/fetcher.py", "line": 3, "title": "Stale TODO reference to DUE-033", "fix": "Update comment to reference docs/design.md or remove the TODO reference"}, {"id": "F-9", "severity": "low", "file": "apps/api/tests/bench_dsp_slicing.py", "line": 1, "title": "Placeholder DUE-XXX in benchmark test docstring", "fix": "Assign real DUE number from TODO.md or remove placeholder"}, {"id": "F-10", "severity": "medium", "file": "apps/api/src/vozonda_api/main.py", "line": 0, "title": "Duplicate Operation ID for audio/routes (same as F-1)", "fix": "See F-1 fix"}]
```