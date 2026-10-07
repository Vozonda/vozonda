# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- the in-app dev page is replaced by the public changelog at vozonda.com/changelog/

### Fixed

- digest: hosts no longer call themselves "Host A", chapter and fallback titles drop site suffixes (" - NASA Science", " | Site"), and the episode title is written from the script like for single episodes (#7)
- script: surprise reactions ("Wait, really?", "Huh.") no longer follow a summary, a turn without a reason, another surprise, or land in the last two turns; the rhythm layer swaps them for a neutral back-channel (#3)
- script: a combined episode's script prompt no longer gets the joined source titles (or note text) as a title to say in the outro (#6)
- script: multi-source episodes cite every content turn (`src` is required in the prompt and repaired once when missing), stored scripts keep `src`, and the script review keeps it and drops values outside 1..n (#5)

## [0.6.0] - 2026-10-04

### Changed
- Complete brand rebrand to Vozonda (Voz = Voice, Onda = Wave; VOZONDA-REBRAND) with zero breaking changes for existing installs, feeds, or local storage.
- VOZONDA_* env vars, automatic browser settings migration, podcast feeds keep their GUIDs.

### Added
- Source objects for the coming source tray: a link, note or uploaded file (PDF, JPG, PNG,
  WebP, TXT, MD) is read once when it is added and shows its real kind (from what the server
  sent, not the link), title, size and language, or an error with a next step (paywall, PDF
  without text layer, no subtitles, ...). Uploads keep only their extracted text; images are
  re-encoded (no EXIF) before the local vision model reads them; unused sources expire after
  24 h. `POST /sources`, `POST /sources/upload`, `GET|PATCH|DELETE /sources/{id}`,
  `POST /sources/{id}/retry`; `POST /jobs` takes `sources` (ids with role main/context), and
  every episode keeps a copy of its sources: `GET /jobs/{id}/sources` (public: uploads by title
  only) and `POST /jobs/{id}/sources/clone` for create variant (same text, no re-fetch)
- Distribution per show: each show picks its reach (private, podcast apps via RSS, Nostr only,
  or both); "Nostr only" turns the show's RSS feed off. `GET /distribution`,
  `PUT /shows/{slug}/rss`, user guide in `docs/distribution.md`
- Nostr publishing endpoints: per-show switch with an explicit public confirmation, key backup
  (nsec export), publish status and retry per episode, best-effort deletion (NIP-09 + BUD-02)
  that also runs when a published episode is deleted
- Settings follow how an episode is made: sources, script (the writing model first), voice,
  shows & distribution (each show with its identity, reach, feed URL and Nostr key), player,
  system. One page width for every screen
- Script contract per style: the style's role split and rhythm in numbers open the prompt and
  a one-line reminder closes it; a targeted role repair rewrites only the few turns where one
  host talks too much (code picks the turns and the speakers, the model writes two parts); a
  deterministic rhythm layer splits monologues at sentence ends and adds varied back-channels
  (English and German) and never removes an interjection the model wrote
- Style registry (`style_registry.py`): one place per style for order, docs, hook brief, script
  params, template, TTS speaker instructs, UI group and icon; `GET /meta` serves `style_meta`;
  guide in `docs/adding-a-style.md`
- Nostr publishing backend, opt-in per show: a keypair per show, NIP-F4 show and episode events,
  Blossom upload with mirrors, relay client per NIP-01/42 (endpoints and UI still to come)
- MCP tools to set up a watchlist that becomes a podcast
- Terminal-style progress indicator and a cancel button for running episodes
- Scheduled watchlist digests: `daily@HH:MM` / `weekly@<day>@HH:MM` per watchlist with timezone,
  one digest per slot, a missed slot caught up once, retry on the next poll after a feed failure,
  manual check forces a digest
- Cross-watchlist dedupe: canonical URLs (tracking params, AMP, www) and near-duplicate titles
  across all feeds for 72 h; titles that differ in a number count as different stories
- Kokoro-82M is the CPU quickstart engine (Docker default) with Piper rendering the languages
  Kokoro lacks (German and others); model files download on first use
- SECURITY.md, GitHub CI workflow, THIRD_PARTY_NOTICES.md, security/license/bug-hunt audits
  under docs/audits/
- Player ambient blur aura & cover art: dynamic backdrop aura reflecting episode cover colors (blur 52px, saturate 140%, brightness 0.35), 1:1 artwork thumbnail, and on-demand Pillow cover fallback on API
- Interactive chapter navigation: structured chapter list for digest episodes with index numbers, active state markers, timestamp offsets, and seek interaction
- Library management & bulk deletion: quiet 'manage' mode toggle, select-all checkbox, row checkboxes, bulk 'delete selected' / 'delete all' with safe inline confirmation, and hover quick-delete per episode; server unlinks media files on deletion
- Watchlist UI polish: harmonized action toolbar (.action-btn), repositioned feed link creation form to top with benefit-focused copy, and 5-item recent auto-episodes shelf
- Research mode (#135): discover/triage/sub-fetch stages between fetch
  and extract - link discovery, llm triage and synthesis pass on top of
  the digest plumbing
- Episode images (#155): og:image extraction with download, pillow
  template fallback cover, feed.xml itunes:image + per-item images,
  /img serving, upload endpoint, storage section in settings
- Media retention: GET /storage stats + POST /storage/purge (manual,
  write-auth, 360-day default threshold)
- GET /jobs filter, sort and search (#152/#153): style, language,
  format, full-text on title/url/description, sort by created_at/
  duration/title
- Per-language per-role default timbres (DUE-041): german uses the
  rating-5 accent-probe cast (dylan/sohee/uncle_fu), web applies
  defaults on language change until the user picks a voice
- Listen-view upgrades (#161-#164): mediasession api for
  lockscreen/smartwatch controls, playback resume, sleep timer with
  fade-out, turn deep-links
- Watchlist tune expander: voices + settings merged into one fold
  point, freshness dot, episode count, template picker with pacing
  presets, digest controls only in digest mode
- Template pacing presets visible on the compose tiles, template
  applied line + go button pulse signal on pick
- MP3 chapter embedding (DUE-011): id3/chapters tags so podcast apps
  show digest chapters natively

### Fixed
- Episode covers were never stored (since 0.5.0 every store call raised and was only logged);
  the library and the player show them, and the library shows the audio length, not the render
  time
- A truncated LLM answer no longer ends a script mid-sentence: the half-written turn is dropped
- An emptied custom prompt falls back to that style's built-in prompt, not to balanced
- Show numbers are never reused (a new show could publish under a deleted show's Nostr key);
  deleting a show no longer hides the others
- Nostr: the Blossom preflight is signed (every upload was refused before), uploads run off the
  event loop, delete tokens carry the BUD-11 expiration and a server tag, no invalid `p` tag,
  show metadata is not republished after a restart, default Blossom servers accept long episodes
- A show from before the RSS switch keeps its feed
- Pillow is a declared dependency and the Docker image has `pdftotext` (PDF sources)
- Episodes no longer fail with "no JSON array in output": the per-turn JSON plan skeleton made
  the local model return no JSON in 6 of 9 live runs and broke the length correction
- Nostr: no episode event is sent without an uploaded audio blob (a signed event on public
  relays cannot be taken back); only a show's own switch publishes, the global preset applies to
  new shows only and re-saving a show keeps its switch; only `show.<n>.nostr` keys are accepted
- AI disclosure is on by default as the settings page already showed: an unset
  `disclosure.ai_label` wrote no AI_GENERATED tag (EU AI Act Art. 50); '0' still turns it off
- Share pages, OG tags and clip links use VOZONDA_PUBLIC_URL or the request host instead of a
  hardcoded domain, so self-hosted installs link to themselves
- Scheduled digests no longer re-bundle entries already used in an earlier digest
- Security: /llm/probe requires write auth, callback_url guarded at registration, path traversal
  on /audio and peaks, SSRF guard on discovered links, no exception text in 401 responses
- Kokoro: installed check, language mapping, downloads written atomically
- cover.py lost in a multi-agent stash collision, recovered from stash
  history; test suite import cleanups (ruff clean)

### Changed
- POST /watchlist/{wid}/digest shares the scheduled digest code path

### Removed
- The per-turn TURN PLAN and the full-rewrite RHYTHM CORRECTION pass (replaced by the script
  contract, the role repair and the rhythm layer)
- Piper voice `lessac` (trained on a non-commercial corpus)

### Security
- urllib3 2.8.0; transformers stays at 4.57.3 until qwen-tts unpins it (see docs/audits/2026-10-security.md)

## [0.5.0] — 2026-08-25

### Added
- Digest mode (#122): bundle N feed articles into one episode - per-watchlist
  digest toggle + story count, render-digest-now endpoint, chapter list in
  listen view, digest badge in library, digest-aware script prompt with
  per-story sections and transitions
- Engine switch (#124): GET/PUT /tts/engine with probe-cache invalidation
- Watchlist last_error surfacing (#149) and honest dns error messages
- PWA shell phase 1 (#138/DUE-016): manifest, service worker, offline page
- Template applied feedback (#136), guided-setup clarity lines (#137)
- seed-qa.sh fixture for data-dependent audit checks (#132)
- restart-api.sh guard: refuses restarts while jobs render
- Session 7 coordination: parallel agent sessions for business plan, UI copy, OSS hardening
- Business plan: Hybrid monetization model, European voices as payment trigger, 3-phase GTM
- OSS hardening: Dockerfile, Dockerfile.web, docker-compose.yml, .env.example, deployment guide

### Fixed
- Go button dead: applyHash tracked by mount effect (untrack), scheme-less
  url normalization, optional piper engine blocking every job
- parse_feed: podcast feeds with urn guids (NPR), RDF/RSS 1.0 namespace,
  non-UTF-8 prologs, size cap truncates instead of discarding (20mb feeds)
- script provider: streaming decode bug, first-json-array raw_decode
  (digest chapters tail), LANGUAGES import in digest prompt
- Removed `<br>` from h1, changed "Two voices" to "Voices"
- Settings toggle restored to expand/collapse pair
- Library search label and empty state aligned with audit contract
- Duplicate settings panel removed
- Focus management after settings level toggle
- Source linking always visible in making-of view

### Changed
- Docs consolidation for v0.5 (see docs/ for the streamlined set)
- Version badge links to the development landing page (planned)
- UI copy rewritten: bold, direct, playful tone across all screens
- Library search label and empty state aligned with audit contract
- Settings toggle label restored to expand/collapse pair
- WCAG AA contrast fixes: green and voice-a light tokens darkened

## [0.4.0] — 2026-08-22

### Added
- Watchlist automation: POST/DELETE /watchlist, background poller, UI WatchlistScreen
- Episode source serving at `/source` with making-of link
- Settings panel rework: flat L2 all-settings + L3 advanced expanders
- Explicit mode toggle (18+ global setting)
- YouTube transcript source support via yt-dlp
- FAQ screen with keyboard shortcuts documentation

### Changed
- Applied 10 UI/UX improvements from audit review
- Language auto-detection for voice selection
- YouTube title extraction for feed items
- Pasted text title generation

### Fixed
- Explicit field display
- HEAD request support
- Duplicate settings panels
- Dead modal removal
- Concurrency handling
- SSRF order in fetcher

## [0.3.0] — 2026-08-15

### Added
- Initial release with core pipeline: script → voice → master
- Docker Compose setup for local development
- FastAPI backend with SQLite job store
- Svelte 5 frontend with Calm Grid design system
- Verification suite: 55 gates (Ruff, Pytest, Svelte-check, clean-worktree)
