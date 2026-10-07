---
type: tactical-backlog
scope: vozonda
last_updated: 2026-10-04
---

# TODO - vozonda (open items only)

Priority: Critical / High / Medium / Low. Ids are stable (`DUE-NNN`).
Feature work is tracked natively as Gitea issues; this file tracks the tactical DUE-number backlog only.

## High (Launch & Sovereign Nostr Readiness)

- [x] #240 / #241 Kokoro-82M Expressive Local TTS Provider Seam & UI Selector (DUE-018 - landed 2026-09-01 via 44e91c8)
- [x] #236 / #237 Multi-Engine LLM Provider Architecture & UI Selector (landed 2026-09-01 via f9bb513, 76645b8)
- [x] #231 / #232 Podcast Show Entity, Hierarchical RSS Feeds & UI Settings (landed 2026-09-01 via 943e803, 311cb05)
- [x] #229 Nostr Profile Screen with Avatar, Name & Activity (landed 2026-09-01 via e02c4be)
- [x] #182 Standalone Public Share View (/e/{id}) with Rich OpenGraph Tags (landed)
- [x] #184 Social Highlight Audio Clips Slicing & Social Teasers (DUE-020 - landed)
- [x] #185 Nostr Multi-Signer Login & Identity Link (NIP-07, NIP-46 Amber/Bunker, npub, nsec) (landed 2026-09-01 via 6e53f5c, closes Gitea #247)
- [x] #181 Live Queue Position & Wait Time Indicator in SSE Pipeline (landed via 3ad14ca, fa918c8; closes Gitea #181)
- [ ] #183 Sovereign L402 Lightning Pay-per-Job & Access Token Gate (DUE-067)
- [x] #186 In-Player Nostr Zaps (NIP-57) & WebLN One-Click Tips on Listen Screen (landed via 1435622)
- [x] #187 Swarm Transcript Highlights (NIP-84 kind 9802) & Community Quotes (landed via 1435622)
- [x] #407 / #418 VOZONDA-TEST-ISOLATION: production path & HF_HOME test isolation (landed 2026-10-04 via 508defb by mistral_code)
- [ ] #188 Nostr Bookmark Sync (NIP-51 kind 10003) for Watchlist Ingestion
- [ ] #256 Key Takeaways & Executive Summary Pipeline Extraction (DUE-071)
- [ ] #257 Dual Mode Player: Podcast Mode vs. Key Takeaways 60s Reader (DUE-072)
- [ ] #258 RSS & Watchlist Digest Integration for Key Takeaways (DUE-073)
- [ ] #259 Streaming Sats & 1-Click Boostagrams via WebLN / NWC (DUE-074)
- [ ] #260 Waveform Timestamp Pins for Boostagrams & NIP-84 Highlights (DUE-075)
- [ ] #261 'Clip & Boost' Nostr Social Slicing Flow (DUE-076)

## High (UI/UX Hardening - Heart & Kidney Audit)

- [x] #270 Calm Grid Design Token & Control Pattern Audit (DUE-082 - landed, radius 2px, tokens.css, lines WCAG AA 3.33:1)
- [x] #271 Accessibility & Keyboard-First Deep Audit (DUE-083 - landed, 0 axe issues, Tab flow, focus-visible, WCAG 2.1 AA sunlight contrast)
- [x] #272 Responsive & Mobile Tactile Audit 375px-1280px (DUE-084 - landed)
- [x] #273 Compose Flow Friction Audit - One Flow Minimal Chrome (DUE-085 - landed)
- [x] #274 Listen & Transcript Experience Audit - Waveform Karaoke Chapters (DUE-086 - landed)
- [x] #275 Performance Motion & Copy Polish Audit (DUE-087 - landed, JS <60KB, LCP <1s, no em-dashes, PWA shell)
- [x] #276 Unified Player Options, Slogan CTA, Provenance Facts & Boost A/B Test QA Audit (DUE-088 - landed)
- [x] #277 Player & Reader Defaults Settings Section (DUE-089 - landed 2026-09-18)
- [x] #278 FAQ Knowledge Base, Scroll-Spy Hardening & Settings Spacing Polish (DUE-090 - landed 2026-09-18)
- [x] #279 Template Audio Showcases, Dialogue Script Tuning & Inline Previews (DUE-091 - landed 2026-09-18)
- [ ] #280 Comprehensive English Voice Probe Matrix & Music Effect Samples (DUE-092)
- [x] #281 Safe Custom Music Ingestion via SSRF-Guarded URL Import (DUE-093 - landed 2026-09-18)

## Medium

- [ ] DUE-067 hosted-tier week-4 review: qualitative go/no-go for self-service portal judged on feedback. Full decisions in docs/archive/internal/business-plan.md section 2.
- [x] DUE-016 PWA: offline audio caching via CacheStorage in service worker (Phase 1 landed via 774d45d).

## Low

- [ ] DUE-013 Voice bake-off harness (same script through N providers)
- [x] DUE-014 nostr: source provider via njump / NIP-19 resolution (landed 2026-08-27)
- [x] DUE-015 PDF source provider (landed 2026-08-26 via pdftotext + Qwen Vision)
- [x] DUE-016 Multi-level source research depth (direct, deep-page, fact-check, contrast)
- [x] DUE-017 Voxtral second provider (landed 2026-08-27 via Mistral EU Audio API & emotion tags)
- [x] DUE-020 API backend complete: POST /clips endpoint (landed)
- [x] DUE-065 design/UI/UX challenge: landed 2026-08-27 (sticky quick launch top bar on compose, 42px tactile buttons, scroll-spy, high contrast chevrons, V4V auto-balance)

## Rules

Status flips only by the session that verified the fix. Do not create parallel roadmap files. Strategic phases: docs/archive/internal/plan.md.
