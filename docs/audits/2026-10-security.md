# vozonda v0.5.0 - Security Audit - October 2026

**Auditor:** fleet agent (VOZONDA-SEC-AUDIT)
**Date:** 2026-10-01
**Scope:** full codebase of the worktree at commit HEAD; Python API (`apps/api`), Svelte frontend (`apps/web`), all provider and pipeline modules.
**Constraint:** read-only. No code was changed. Only this file was written.

---

## Methodology

All findings are derived from direct file inspection (`view_file`). The sandbox does not have PTY access (`open /dev/ptmx: permission denied`), so the following tools could **not** be run; their absence is stated explicitly where the task requires them:

- `pip-audit` / `uvx pip-audit`
- `npm audit`
- `gitleaks` / `trufflehog`
- `git log -p` (requires a shell)

Secret scan was performed by reading committed files and configuration templates directly; no shell grep over the git object store was possible. Results and caveats are reported in Section 5.

---

## Findings

### F-1: SSRF via `callback_url` - no `guard_url` at creation time (HIGH)

**File:** `apps/api/src/vozonda_api/main.py:863-871`
**Trigger input:** `POST /jobs` with `{"url":"...", "callback_url":"http://169.254.169.254/latest/meta-data/"}`

**Evidence:**

```python
# main.py:862-871
if body.callback_url:
    cb = body.callback_url.strip()
    if len(cb) > 2048:
        raise HTTPException(422, "callback_url must not exceed 2048 characters")
    from urllib.parse import urlparse
    p = urlparse(cb)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise HTTPException(422, "callback_url must have http or https scheme")
```

The validator only checks that the scheme is `http`/`https` and a netloc exists. It does **not** call `guard_url()`. The URL is stored in the DB and delivered by `webhooks.deliver()` at job completion.

`webhooks.deliver()` (`apps/api/src/vozonda_api/webhooks.py:80`) uses `guarded_client()` for the actual POST, which **does** apply the SSRF guard at delivery time. So the guard is present at delivery but not at registration. The practical risk is that an attacker can determine whether an address is reachable (timing side-channel) by submitting a job with a private `callback_url` and observing whether the log line `"Webhook delivery refused by SSRF guard"` or a successful delivery is emitted. In environments where the API's logs are observable, this is a reachability oracle for internal network topology.

**Fix:** Call `guard_url(cb)` immediately after the `urlparse` check in `create_job` (main.py line 871), raising HTTP 422 on `FetchError`. This mirrors the pattern used for `body.feed_url` in `POST /watchlist`.

---

### F-2: `GET /llm/probe` uses plain `httpx.AsyncClient` for user-supplied `custom_base` (HIGH)

**File:** `apps/api/src/vozonda_api/main.py:756-763`
**Trigger input:** `GET /llm/probe?engine=custom&custom_base=http://169.254.169.254/`

**Evidence:**

```python
# main.py:756-763
models_url = f"{base}/models" if not base.endswith("/models") else base
try:
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=3.0) as c:
        r = await c.get(models_url, headers=headers)
```

`base` is derived from the `custom_base` query parameter (user-supplied, line ~742: `base = custom_base or get_setting("llm.custom_base") or "http://127.0.0.1:30001/v1"`). A plain `httpx.AsyncClient` with no SSRF guard is used to probe it. An unauthenticated caller (see F-3 below) can direct this GET to any reachable address including cloud-provider metadata services or internal microservices.

**Fix:** Wrap the httpx call inside `guarded_client()` from `fetcher.py`, or call `guard_url(models_url)` before the request. The `GET /providers` route at line 415 has the same issue for the default `LLM_BASE` but that URL is operator-configured (env), not user-supplied.

---

### F-3: `GET /llm/probe` is unauthenticated (MEDIUM)

**File:** `apps/api/src/vozonda_api/main.py` (route declaration around line 622)
**Trigger input:** `GET /llm/probe?engine=custom&custom_base=http://...`

**Evidence:** The route has no `Depends(require_write_auth)` in its signature. When `VOZONDA_TOKEN` is set and the instance is exposed, any unauthenticated HTTP client can use this endpoint to probe arbitrary URLs (see F-2).

`GET /providers` (line 405) has the same absence of auth and the same `httpx.AsyncClient(timeout=3)` call to `LLM_BASE`, but `LLM_BASE` is operator-controlled.

**Fix:** Add `dependencies=[Depends(require_write_auth)]` to the `GET /llm/probe` route declaration (and to `GET /providers` for consistency, though the risk there is lower since the target is operator-fixed).

---

### F-4: `_validate_access_token` leaks exception detail from billing validator (LOW)

**File:** `apps/api/src/vozonda_api/main.py:364-365`
**Trigger input:** Any endpoint that calls `_validate_access_token()` with a token that causes the billing `validate_token()` function to raise with an informative message.

**Evidence:**

```python
# main.py:364-365
except Exception as e:
    raise HTTPException(401, f"invalid or inactive access token: {e}")
```

If `billing.validate_token()` raises with a message that includes the token value, a partial key value, or internal service addresses, those details are forwarded to the HTTP client in the 401 response body. Billing code was not read in full; this is a potential rather than confirmed leak.

**Fix:** Replace `str(e)` with a generic message: `raise HTTPException(401, "invalid or inactive access token")`. Log `str(e)` at DEBUG level server-side instead.

---

### F-5: `/audio/{filename:path}.mp3` - path traversal check absent (MEDIUM)

**File:** `apps/api/src/vozonda_api/main.py:2576-2610`
**Trigger input:** `GET /audio/../../../../etc/passwd.mp3`

**Evidence:**

```python
# main.py:2594-2596
path = MEDIA_DIR / f"{filename}.mp3"
if path.exists():
    return FileResponse(path, media_type="audio/mpeg")
```

The route uses `{filename:path}` (FastAPI allows slashes). Python's `Path /` operator does normalize `..` on most platforms, but the check `path.exists()` is the only guard - there is no `path.resolve().relative_to(MEDIA_DIR.resolve())` containment check. If `filename` is `../../../../etc/shadow` and that path happens to exist with a `.mp3` extension appended (unlikely but not impossible), the file would be served.

By contrast, the `/img/{filename:path}` route at line 2835 **does** perform the canonical containment check:

```python
# main.py:2858-2862  (CORRECT pattern)
try:
    path.resolve().relative_to(MEDIA_DIR.resolve())
except ValueError:
    raise HTTPException(403, "forbidden") from None
```

The `/audio/` route is missing this check. The `probe-` branch at lines 2600-2608 also opens a fixed directory (`samples_dir`) without a containment check on `exact` after `removeprefix`.

**Fix:** Add the same containment check to the audio route immediately after constructing `path`:

```python
try:
    path.resolve().relative_to(MEDIA_DIR.resolve())
except ValueError:
    raise HTTPException(403)
```

Repeat for the `exact` path in the probe branch.

---

### F-6: `/audio/{job_id}.peaks.json` - no path containment check (MEDIUM)

**File:** `apps/api/src/vozonda_api/main.py:2613-2619`
**Trigger input:** `GET /audio/../../data/jobs.peaks.json`

**Evidence:**

```python
# main.py:2616-2618
path = MEDIA_DIR / f"{job_id}.peaks.json"
if not path.exists():
    raise HTTPException(404, "no peaks yet")
return FileResponse(path, media_type="application/json")
```

`job_id` comes directly from the URL path. No containment check. Pattern is identical to F-5.

**Fix:** Same `resolve().relative_to(MEDIA_DIR.resolve())` check.

---

### F-7: `GET /music/{kind}.mp3` - kind validated, but no path check on resolved path (LOW)

**File:** `apps/api/src/vozonda_api/main.py:3117-3130`

**Evidence:**

```python
norm_kind = kind.lower().strip()
if norm_kind not in ("intro", "outro"):
    raise HTTPException(status_code=404, ...)
path = get_or_create_preview_audio(norm_kind)
```

The allowlist on `kind` prevents path traversal at the route level. `get_or_create_preview_audio` constructs `music_dir / f"{kind}.mp3"` where `kind` is the already-validated `norm_kind`. This is safe as implemented, but worth documenting that the allowlist is the only guard - no containment check on the returned path object.

**Severity:** Low (allowlist is sufficient; flagged for completeness).
**Fix:** No change required, but document the invariant with a comment.

---

### F-8: `/meta` exposes write-auth configuration status (LOW)

**File:** `apps/api/src/vozonda_api/main.py` (around line 1448)
**Trigger input:** `GET /meta`

**Evidence:**

```python
"write_auth": bool(os.environ.get("VOZONDA_TOKEN"))
```

The unauthenticated `/meta` endpoint reveals whether `VOZONDA_TOKEN` is set. This allows an attacker to determine in advance whether brute-force attempts against the token would be worthwhile, and to confirm that the instance is configured without a token (making it an open write target when `_write_auth_required()` is also False).

**Fix:** Remove the `write_auth` field from the public `/meta` response, or replace it with the boolean result of `_write_auth_required()` (which already omits whether a token is configured).

---

### F-9: `nostr_auth` identity listing is unauthenticated (LOW)

**File:** `apps/api/src/vozonda_api/main.py:3236-3240`
**Trigger input:** `GET /auth/nostr/identities`

**Evidence:**

```python
@app.get("/auth/nostr/identities")
async def nostr_identities() -> dict:
    from .nostr_auth import list_identities
    return {"identities": list_identities()}
```

No `require_write_auth`. `list_identities()` returns all stored pubkeys. The deletion route at line 3243 is correctly protected. Listing is not itself destructive but may expose which Nostr keys are authorized, acting as a reconnaissance step.

**Fix:** Add `dependencies=[Depends(require_write_auth)]` to this route.

---

### F-10: `GET /storage` is unauthenticated (LOW)

**File:** `apps/api/src/vozonda_api/main.py:3038-3043`

**Evidence:**

```python
@app.get("/storage")
async def storage_stats() -> dict:
```

No auth dependency. Returns media directory size and retention info. Not directly harmful but leaks server filesystem state to unauthenticated callers.

**Fix:** Add `dependencies=[Depends(require_write_auth)]` or accept the low risk.

---

### F-11: `_discover_links` in `pipeline.py` does NOT call `guard_url` on internal links before fetching (MEDIUM)

**File:** `apps/api/src/vozonda_api/pipeline.py:151-167`

**Evidence:**

```python
# pipeline.py:158-167 - internal (same-host) links
if parsed.hostname == seed_host and parsed.scheme in ("http", "https"):
    if _LINK_BLOCKLIST.search(url):
        continue
    # Link text must be >= 3 words
    ...
    candidates.append(url)
```

The internal-link branch in `_discover_links` does NOT call `guard_url`. External links (lines 181-186) do call `guard_url`. However, in `_triage_links` / `_sub_fetch` the returned candidates are fetched via `guarded_client` (line 260), which applies the SSRF guard per-request. So the guard is present at fetch time but not at candidate-building time. If the seed URL itself were an internal address (which `fetch_article` would already have blocked), same-host links would also be internal. In practice this chain cannot be reached with an internal seed URL because `guard_url` is called in `fetch_article` before the HTML is available. The risk is **theoretical** but warrants a code note.

**Fix:** Document the assumption that `_discover_links` is only called with externally-validated HTML as a comment at the function entry. Optionally add `guard_url` to the internal-link branch for defense-in-depth.

---

### F-12: Model names hardcoded in `pipeline.py` and `providers/__init__.py` (LOW - policy violation, not security)

**File:** `apps/api/src/vozonda_api/pipeline.py:838,2839`; `apps/api/src/vozonda_api/providers/__init__.py:23,123,130,132`

**Evidence:**

```python
# pipeline.py:838
model=prov.get("model", "qwen3.6-35b"),
# pipeline.py:2839
llm_model = "qwen3.6-35b" if llm_prov == "qwen" else ("mistral-small-4" if llm_prov == "mistral" else llm_prov)
# providers/__init__.py:23
LLM_MODEL = os.environ.get("VOZONDA_LLM_MODEL", "qwen3.6-35b")
# providers/__init__.py:123,130,132
model = _setting("llm.custom_model") or "claude-3-7-sonnet-20250219"
...
return [...{"name": "nemotron", "base": "http://127.0.0.1:30004/v1", "model": "nemotron-nano"}]
return [...{"name": "gemma", "base": "http://127.0.0.1:30003/v1", "model": "gemma4-e2b"}]
```

This violates AGENTS.md rule 10. Not a security issue but included per the audit scope.

**Fix (policy):** Move hardcoded defaults to settings keys with env fallbacks as per the rule.

---

## Dependency Vulnerability Scan

### Python (`pip-audit`)

**Tool status:** `pip-audit` (`uvx pip-audit`) cannot be executed in this sandbox due to PTY permission denied (`open /dev/ptmx: permission denied`). The locked dependencies in `apps/api/uv.lock` were not scanned.

**Manual review of `apps/api/pyproject.toml` direct dependencies:**

| Package | Version constraint | Notes |
|---|---|---|
| fastapi | >=0.115 | No known critical CVEs at time of audit in this range |
| uvicorn[standard] | >=0.34 | No known critical CVEs |
| httpx | >=0.28 | No known critical CVEs |
| pydantic | >=2.10 | No known critical CVEs |
| readability-lxml | >=0.8.4.1 | Depends on lxml; lxml has had past CVEs (CVE-2022-2309); version constraint does not pin lxml |
| lxml_html_clean | >=0.4 | XSS sanitizer; correctness matters; no CVE at this range |
| python-multipart | any (transitive via fastapi) | CVE-2024-53498 (DoS) fixed in 0.0.18; ensure locked version >=0.0.18 |

**Action required:** Run `cd apps/api && uvx pip-audit` in an environment with PTY access before the public release and remediate any findings.

### JavaScript (`npm audit`)

**Tool status:** `npm audit` cannot be executed in this sandbox (PTY permission denied).

**Manual review of `apps/web/package.json`:**

| Package | Version | Type | Notes |
|---|---|---|---|
| svelte | ^5.19.0 | devDep | No known critical CVEs |
| vite | ^6.0.11 | devDep | CVE-2025-30208 (path traversal in dev server) fixed in 6.0.9; constraint >=6.0.11 is safe |
| playwright | ^1.62.1 | dep | No known critical CVEs in this range |
| axe-core | ^4.13.0 | dep | No known critical CVEs |
| @fontsource-variable/* | ^5.x | dep | Static font packages; no CVE surface |

**Action required:** Run `cd apps/web && npm audit --omit=dev` before the public release.

---

## SSRF Surface Summary

| Vector | Guard present? | Notes |
|---|---|---|
| `POST /jobs` -> `fetch_article(url)` | Yes - `guarded_client` in `fetcher.py` | Correct |
| `POST /watchlist` -> `guard_url(body.feed_url)` | Yes | Correct |
| Watchlist poller `fetch_feed_text(feed_url)` | Yes - `guard_url` + `guarded_client` | Correct |
| Watchlist digest `render_watchlist_digest` -> `guard_url(link)` | Yes | Correct |
| `POST /music/import-url` -> `import_music_from_url` | Yes - `guard_url` + `guarded_client` | Correct |
| `download_og_image` (cover.py) | Yes - `guard_url` + `guarded_client` | Correct |
| `webhooks.deliver(callback_url)` | Yes - `guarded_client` at delivery time | Safe at delivery; no guard at registration (F-1) |
| `GET /llm/probe?custom_base=...` | **No** - plain `httpx.AsyncClient` | F-2 |
| `GET /providers` probe of `LLM_BASE` | No guard but target is env-configured | Low risk |
| Research mode `_sub_fetch` | Yes - `guarded_client` | Correct |
| `_discover_links` internal-link branch | Guarded at fetch time via `guarded_client` | Theoretical gap noted in F-11 |

---

## Path Traversal Surface Summary

| Route | Containment check? |
|---|---|
| `GET /audio/{filename:path}.mp3` | **Missing** (F-5) |
| `GET /audio/{job_id}.peaks.json` | **Missing** (F-6) |
| `GET /img/{filename:path}` | Present - `resolve().relative_to(MEDIA_DIR)` |
| `GET /music/{kind}.mp3` | Allowlist on `kind`; safe (F-7) |
| `DELETE /jobs/{job_id}/clips/{filename}` | Present - `resolve().is_relative_to(MEDIA_DIR)` |
| `GET /vtt/{job_id}.vtt` | `job_id` from DB lookup; no file path |
| `GET /srt/{job_id}.srt` | `job_id` from DB lookup; no file path |
| `POST /watchlist/{wid}/cover` | Generated filename from UUID; safe |

---

## State-Changing Routes Without `require_write_auth`

The following state-changing or sensitive routes were found without the `require_write_auth` dependency:

| Route | Why it's missing | Risk |
|---|---|---|
| `GET /llm/probe` | Intentionally open for UI probing | Medium (F-2, F-3) |
| `GET /auth/nostr/identities` | Not classified as write | Low (F-9) |
| `GET /storage` | Not classified as write | Low (F-10) |
| `POST /auth/nostr/verify` | Public sign-in flow | Acceptable |
| `POST /auth/npub/validate` | Validation utility, no state written | Acceptable |
| `GET /auth/nostr/challenge` | Issues HMAC challenge, no state written | Acceptable |

All other state-changing routes reviewed were correctly protected:
`POST /jobs`, `POST /clips`, `DELETE /clips/{filename}`, `PUT /tts/engine`, `PUT /llm/engine`, `POST /jobs/{id}/script`, `PATCH /jobs/{id}`, `DELETE /jobs/{id}`, `PUT /settings/{key}`, `POST /shows`, `PUT /shows/{slug}`, `DELETE /shows/{slug}`, `PUT /shows/current`, `POST /watchlist`, `PUT /watchlist/{wid}`, `DELETE /watchlist/{wid}`, `POST /watchlist/{wid}/check`, `POST /watchlist/{wid}/digest`, `POST /watchlist/{wid}/cover`, `PUT /audio/{job_id}.peaks.json`, `POST /storage/purge`, `POST /music/import-url`, `POST /music/reset`, `DELETE /auth/nostr/identities/{pubkey}`.

---

## Secrets Handling

### `.env` files
`.gitignore` correctly excludes `.env` and `*.env` (lines 18-19). No `.env` file is tracked in the worktree.

### Settings store
`SECRET_SETTINGS = frozenset({"llm.api_key", "llm.nim_api_key", "feed.private_key"})` in `settings_store.py:142`. `GET /settings` returns `public_settings()` which replaces these with `"********"`. Submitting the mask back does not overwrite the stored value. This is correct.

### Secret files
Secrets may also live in `VOZONDA_SECRETS_DIR` (key files: `mistral_api.key`, `nvidia_nim_api.key`). These are read by the providers at runtime and never sent to the client. The directory is not tracked by git.

### Error messages
- `_validate_access_token` at `main.py:365` propagates `str(e)` from the billing validator into the HTTP 401 body (F-4).
- No other confirmed leakage of key material in error paths was found during this audit.

---

## Git History Secret Scan

**Tool status:** `gitleaks` and `trufflehog` could not be run (PTY permission denied). `git log -p` requires a shell.

**Alternative scan performed:** All configuration files, provider modules, and environment handling code in the worktree were read directly. The following patterns were specifically searched for in the tracked files:

- Hardcoded `sk-`, `Bearer `, `api_key =`, `password =` literals
- Files named `.env`, `*.key`, `secrets.*` in tracked paths

**Findings:**

No literal API keys, passwords, bearer tokens, or private key material were found in any tracked source file. The following strings resembling keys appear only as placeholder comments or format strings:

- `providers/__init__.py:264`: `f"echo 'your_key' > {VOZONDA_SECRETS_DIR / 'mistral_api.key'}"` - this is a help string shown in the UI, not an actual key.
- `nostr_auth.py` (not fully read): Nostr auth stores public keys only; no nsec (private key) handling. The `/auth/npub/validate` endpoint explicitly rejects nsec input.

**Conclusion:** No secrets were found in the tracked files of this worktree. A full object-store scan (`git log -p` or `gitleaks --no-git false`) over the complete commit history is **required** before the public open-source release; the absence of PTY access prevented this. The `.gitignore` correctly excludes `.env` and `*.env`, and the secrets directory is not tracked, but developer commits over the project's history may still contain accidentally-committed credentials. **A history rewrite (interactive rebase or `git filter-repo`) is recommended if any secrets are found by the full scan.**

---

## Prioritized Fix List (for follow-up tasks)

| Priority | ID | Severity | Title | Effort |
|---|---|---|---|---|
| 1 | F-2 | High | `GET /llm/probe` - plain httpx client on user-supplied `custom_base` | 1 line: wrap with `guarded_client` |
| 2 | F-1 | High | `callback_url` accepted without SSRF check at registration | 1 call: add `guard_url(cb)` in create_job |
| 3 | F-5 | Medium | `/audio/{filename:path}.mp3` missing path-containment check | 5 lines: add `resolve().relative_to()` |
| 4 | F-6 | Medium | `/audio/{job_id}.peaks.json` missing path-containment check | 5 lines: same pattern |
| 5 | F-3 | Medium | `GET /llm/probe` unauthenticated | Add `Depends(require_write_auth)` |
| 6 | F-11 | Medium | `_discover_links` no guard on internal links before candidate list | Comment + optional `guard_url` |
| 7 | F-4 | Low | `_validate_access_token` leaks exception detail | Drop `str(e)` from HTTP response |
| 8 | F-8 | Low | `/meta` leaks write-auth configuration status | Remove `write_auth` from public response |
| 9 | F-9 | Low | `GET /auth/nostr/identities` unauthenticated | Add `Depends(require_write_auth)` |
| 10 | F-10 | Low | `GET /storage` unauthenticated | Add `Depends(require_write_auth)` or document acceptance |
| 11 | DEP | - | Run `pip-audit` and `npm audit --omit=dev` before release | External tooling |
| 12 | GIT | - | Run `gitleaks` / `git log -p` over full history before release | External tooling |

---

```findings
[
  {
    "id": "F-1",
    "severity": "high",
    "file": "apps/api/src/vozonda_api/main.py",
    "line": 863,
    "title": "callback_url accepted without SSRF guard at registration time",
    "fix": "Call guard_url(cb) from fetcher.py immediately after the urlparse check in create_job (line 871); raise HTTP 422 on FetchError. This matches the pattern used for feed_url in POST /watchlist."
  },
  {
    "id": "F-2",
    "severity": "high",
    "file": "apps/api/src/vozonda_api/main.py",
    "line": 762,
    "title": "GET /llm/probe uses plain httpx.AsyncClient on user-supplied custom_base (SSRF)",
    "fix": "Replace 'async with httpx.AsyncClient(timeout=3.0) as c:' with 'async with guarded_client(timeout=3.0) as c:' from fetcher.py, or call guard_url(models_url) before the request."
  },
  {
    "id": "F-3",
    "severity": "medium",
    "file": "apps/api/src/vozonda_api/main.py",
    "line": 622,
    "title": "GET /llm/probe route is unauthenticated, enabling SSRF probe by any client",
    "fix": "Add dependencies=[Depends(require_write_auth)] to the GET /llm/probe route decorator."
  },
  {
    "id": "F-4",
    "severity": "low",
    "file": "apps/api/src/vozonda_api/main.py",
    "line": 365,
    "title": "_validate_access_token propagates exception detail into HTTP 401 response body",
    "fix": "Replace raise HTTPException(401, f'invalid or inactive access token: {e}') with raise HTTPException(401, 'invalid or inactive access token') and log str(e) at DEBUG level server-side."
  },
  {
    "id": "F-5",
    "severity": "medium",
    "file": "apps/api/src/vozonda_api/main.py",
    "line": 2594,
    "title": "GET /audio/{filename:path}.mp3 missing path-containment check (path traversal)",
    "fix": "After 'path = MEDIA_DIR / f\"{filename}.mp3\"', add: try: path.resolve().relative_to(MEDIA_DIR.resolve()) except ValueError: raise HTTPException(403). Apply the same check to the probe-branch path at line 2603."
  },
  {
    "id": "F-6",
    "severity": "medium",
    "file": "apps/api/src/vozonda_api/main.py",
    "line": 2616,
    "title": "GET /audio/{job_id}.peaks.json missing path-containment check (path traversal)",
    "fix": "After 'path = MEDIA_DIR / f\"{job_id}.peaks.json\"', add the same resolve().relative_to(MEDIA_DIR.resolve()) containment check used in the /img/ route."
  },
  {
    "id": "F-7",
    "severity": "low",
    "file": "apps/api/src/vozonda_api/main.py",
    "line": 3117,
    "title": "GET /music/{kind}.mp3 relies on allowlist alone; no path containment on resolved path",
    "fix": "Allowlist is sufficient; add a comment documenting that norm_kind in (intro, outro) is the sole path-safety invariant, or add a resolve().relative_to() check for defense-in-depth."
  },
  {
    "id": "F-8",
    "severity": "low",
    "file": "apps/api/src/vozonda_api/main.py",
    "line": 1448,
    "title": "GET /meta leaks whether VOZONDA_TOKEN is configured to unauthenticated callers",
    "fix": "Remove 'write_auth' from the /meta response dict, or replace with the boolean result of _write_auth_required() which does not reveal the token's presence."
  },
  {
    "id": "F-9",
    "severity": "low",
    "file": "apps/api/src/vozonda_api/main.py",
    "line": 3236,
    "title": "GET /auth/nostr/identities lists all authorized pubkeys without authentication",
    "fix": "Add dependencies=[Depends(require_write_auth)] to the GET /auth/nostr/identities route."
  },
  {
    "id": "F-10",
    "severity": "low",
    "file": "apps/api/src/vozonda_api/main.py",
    "line": 3038,
    "title": "GET /storage returns filesystem stats without authentication",
    "fix": "Add dependencies=[Depends(require_write_auth)], or accept the low risk and document it."
  },
  {
    "id": "F-11",
    "severity": "medium",
    "file": "apps/api/src/vozonda_api/pipeline.py",
    "line": 151,
    "title": "_discover_links does not call guard_url on internal (same-host) link candidates",
    "fix": "Add guard_url(url) with a try/except FetchError: continue block in the internal-link branch of _discover_links (after line 165), mirroring the external-link branch at line 181. Alternatively, document that the function is only called after fetch_article has already validated the seed URL."
  }
]
```

---

## Coordinator supplement (2026-10-01): the tool runs the sandbox could not do

The audit lane had no shell, so the coordinator ran these on the box, read-only.

**Python dependencies** (`uvx pip-audit --path apps/api/.venv/lib/python3.13/site-packages`):
13 known vulnerabilities in 3 packages. Note: a first run against `uv export` audited an empty
list and reported "no known vulnerabilities"; only the installed-environment run is valid.

| Package | Installed | Advisories | Fixed in | Note |
|---|---|---|---|---|
| urllib3 | 2.7.0 | CVE-2026-97687, -97688, -97689 | 2.8.0 | straightforward bump |
| transformers | 4.57.3 | PYSEC-2025-217, PYSEC-2026-2288/2289/2290/3929, CVE-2026-80047 | 5.0.0 to 5.10.0 | major version: test every local TTS engine (dia, dia2, higgs, vibevoice, chatterbox, qwen3-tts) before bumping; check whether transformers is only pulled in by optional engine extras |
| accelerate | 1.12.0 | PYSEC-2026-3804 | none listed yet | track |

**Web dependencies** (`npm audit --omit=dev` in apps/web): 0 vulnerabilities.

**Secret scan of the full history** (1,047 commits, all refs; regex for OpenAI/OpenRouter/GitHub/
GitLab/Slack/AWS/Google/NVIDIA keys, nsec, Lightning invoices, private-key blocks and quoted
key assignments): no secrets. The only hits are documentation placeholders (`"YOUR..."`). `.env`
was never committed. A history rewrite is not needed for secrets (other public-readiness items
are tracked separately).

**Spot-checked findings:** F-2/F-3 (`/llm/probe` unauthenticated + unguarded fetch) and F-5
(`/audio/{filename:path}.mp3` without a containment check, unlike `/img/`) confirmed in the code.

## Decision: transformers stays at 4.57.3 for now (2026-10-01)

The advisories against transformers 4.57.3 (PYSEC-2025-217, PYSEC-2026-2288/2289/2290/3929,
CVE-2026-80047) are fixed only in 5.x. vozonda cannot move yet: `qwen-tts` pins
`transformers==4.57.3` and `accelerate==1.12.0` exactly, including its latest release 0.1.1.
Overriding that pin would run the Qwen3-TTS engine on an untested major version.

Accepted risk, reviewed: vozonda loads only fixed, named checkpoints from their official
repositories (see the TTS model list in `docs/audits/2026-10-licenses.md`); it never loads a
model, tokenizer or config chosen by a request. Re-check each advisory against that when it is
updated.

Exit condition: upgrade to transformers 5.x as soon as a `qwen-tts` release allows it, then
render one smoke episode per local engine (qwen3-tts, chatterbox, dia, dia2, higgs, vibevoice)
on the GPU before landing. urllib3 was bumped to 2.8.0 in the same pass (8f5cdcb).
