# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- private or public is now set per show (`show.<n>.public`, `show.default.public`), no longer one switch for every feed; a new show starts private; shows from before follow the old `feed.public`. The master feed `/feed.xml` without the key lists only public shows (404 when there is none); with the key it lists every show that has a feed. A private episode's media links keep the key in every feed opened with it

### Added

- web: `qrcode-generator` (MIT) as a dependency and `lib/qr.ts` for QR codes rendered in the browser (the private feed link to a phone; nothing leaves the device)
- the address other devices use can be set in the settings (`address.public`, wins over `VOZONDA_PUBLIC_URL`; only a plain http(s) address); `GET /distribution` reports it with its scope (this computer, private network or VPN, internet) and whether it answers, plus `public` per show
- `PUT /shows/{slug}/public` and `POST /feed/key/rotate` (a new feed key; old links stop working)

### Fixed

- settings: the feed links to copy left out the key, so a private feed (the default) answered 404 in the podcast app; they now carry it, with a note that anyone who has the link can listen
- native install (`npm run preview -- --host`): feed links pointed at `127.0.0.1:8787`, because the preview rewrites the host; feeds now use `VOZONDA_PUBLIC_URL` when it is set, like share pages and webhooks, so a podcast app on another device can play the episodes
- native install: the Vite preview answered "Blocked request" for the machine's name (for example its Tailscale name) and did not pass per-show feeds (`/{show}/{name}/feed.xml`) to the API; it now accepts the host of `VOZONDA_PUBLIC_URL` (plus `VOZONDA_ALLOWED_HOSTS`) and proxies per-show feeds

## [0.7.2] - 2026-10-10

Security release: update if Vozonda is reachable from another device (reverse proxy, VPN, LAN, `npm run preview -- --host`). Set `VOZONDA_TOKEN` in `.env` first, then update; the web UI asks for it once.

### Security

- remote access needs the token (GHSA-crq5-73gf-fv2h): a request that reaches Vozonda from outside the host, through a reverse proxy, a VPN or the LAN, now needs `VOZONDA_TOKEN`; before, a reverse proxy in front of the web UI made the API act as if every request were local, so the episode list, sources, transcripts, audio and settings were open, and episodes could be started. The web UI asks for the token once and keeps an HttpOnly session for 30 days. Local use on 127.0.0.1 is unchanged and needs no token
- a private episode's audio, transcript and share page open from outside only with the feed key, which a private feed's links now carry; episodes of a public show or published to Nostr stay open. New episode ids carry 12 random hex digits instead of 4
- a request also counts as remote when it is addressed by a name other than a loopback one (the LAN or VPN address of the machine, or a proxy that keeps the original host), and the Vite preview (`npm run preview -- --host`) passes the client address on; before, the preview made every request look local. `VOZONDA_LOCAL_HOSTNAMES` adds names that count as local
- docs: the reverse-proxy example exposes only feeds, audio, transcripts and share pages and keeps the web UI private (VPN or SSH tunnel); if you reach Vozonda from another device in any way, set `VOZONDA_TOKEN` before updating

### Added

- update notice: when a newer release exists the web UI shows it (marked when it is a security release) with the command to update, `git pull && docker compose up -d --build`; it asks GitHub at most every six hours, only while the UI is open, and "stop checking" turns it off (setting `update.check`)

### Fixed

- Docker web container: `/shows`, `/styles`, `/plugins`, `/music`, `/storage`, `/clips`, transcripts and per-show feeds were not passed to the API by the bundled nginx, so those screens and links failed in the Docker setup
- the service worker served `/auth/session` and other API answers from its asset cache; every API path is now network-first

## [0.7.1] - 2026-10-09

### Fixed

- audio uploads are recognised (MP3 with ID3 tags, M4A, WAV, Ogg/Opus, FLAC) and may be up to the audio cap; the source input lists audio and its file picker accepts audio files
- audio: transcription failed on every install since PyAV 19 (faster-whisper 1.2.1 still passes `metadata_errors` to `av.open`); `av` is held below 19 in the `stt` extra and the Docker image
- audio: the default cap for audio files is 100 MB (was 300 MB; about one hour of MP3, matching the one-hour limit), the Whisper timeout grows with the audio length instead of a fixed 300 s, Whisper skips silence (VAD), punctuation chunks run four at a time and keep a chunk raw if a single word changes

### Changed

- settings: the default show says why it offers no Nostr options (it has no Nostr key of its own; name a show to publish on Nostr)

## [0.7.0] - 2026-10-09

### Added

- audio sources: upload or link MP3, M4A, WAV, OGG and OPUS files; the audio is transcribed with faster-whisper, punctuation is restored by the local LLM with word-for-word validation, and pre-existing `<podcast:transcript>` tags are extracted without re-transcribing.
- audio sources: audio downloads have a dedicated size cap (300 MB default, `VOZONDA_AUDIO_MAX_BYTES`); exceeding it raises an error instead of truncating; punctuation restoration processes text in ~300-word chunks with per-chunk validation and `enable_thinking=false`; Whisper model is configurable via `VOZONDA_WHISPER_MODEL` (default `base`).

### Changed

- Docker: the default image no longer installs torch, torchaudio and qwen-tts, so it is much smaller and carries none of their advisories. Qwen3-TTS is opt-in: set `VOZONDA_WITH_QWEN_TTS=1` in `.env` and run `docker compose up -d --build` (#26). **Upgrade note:** if you use the `qwen_tts` engine in Docker, set that variable before you rebuild.
- web: vite 8 and @sveltejs/vite-plugin-svelte 7, upgraded together (their peer ranges only match as a pair; replaces Dependabot #15 and #16)
- the in-app dev page is replaced by the public changelog at vozonda.com/changelog/

### Fixed

- show tiles no longer overflow on medium-width windows (container query replaces viewport media query for 2-column layout)
- tests: the shared test database path is unique per xdist worker; two workers could share one /dev/shm file and fail at random
- security: web dependency `source-map-js` 1.2.1 -> 1.2.2 (event-loop denial of service advisory); transformers/accelerate advisories stay blocked by the qwen-tts pin, tracked in #26
- fetching: the user agent carries a contact URL (`+https://vozonda.com`), as Wikimedia's robot policy asks; without it Wikipedia answered 403 to the Docker image, so the quickstart example failed on a clean machine
- about and FAQ no longer describe turning Nostr bookmarks (NIP-51) into episodes: that is not built yet; it is on the roadmap as an idea
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
