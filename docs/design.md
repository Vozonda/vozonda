# Calm Grid - Design System

> One screen, one purpose. Warm paper, terminal honesty.
> Reference points: sovgrid.org and calm editorial print UX.
> Award-winning means: nothing you can remove.

## Principles

0. **Form follows function. Every element earns its place by what it tells
   you.** If a visual element carries no information the user can act on,
   it is removed, no matter how charming. Decoration is a defect.
0a. **Simple stays simple. Advanced explains itself.** The main flow shows
   only what most people change (link, dialog vs solo, style, language).
   Everything else lives behind "More options", and every option carries a
   one-sentence plain-language explanation of its effect. No jargon without
   translation: never "timbre", always "voice character". If an option needs
   a paragraph to explain, it belongs in expert mode or not at all.
1. **One flow, minimal chrome.** The app IS the flow: input -> progress ->
   listen. No classic top nav, ever. Secondary places (about, faq, library)
   live in the compose footer; settings opens as a modal via an "all
   settings" link sitting next to the style chips, where the choice happens.
   Task flows keep contextual back links ("← new episode", "← back").
2. **Paper, not dashboard.** Cream background, serif body, generous whitespace.
   It should feel like a printed transcript, not an admin panel.
3. **Terminal honesty.** Pipeline state is shown as machine truth:
   `// extracting`, `// scripting`, `// voicing`. JetBrains Mono, small,
   lowercase. Never fake progress bars.
4. **Two voices are the hero.** Speaker identity is visual (color + initial),
   audio is the artifact. Waveform > cover art.
 5. **Sovgrid touch = green on paper.** NVIDIA-green as the single accent
    hue (links, active states, the record dot). On paper, green text uses
    the AA-darkened variant `#4A7300` (5.2:1); raw NVIDIA `#76B900` stays
    on dark surfaces and in dark mode, where it passes contrast. Everything
    else is ink on cream. Dark mode inverts to near-black with the same
    bright green.

## Tokens

- `--ui-size: 0.95rem` (raised from 0.8125rem on 2026-08-23: 13px base was
  below comfortable reading size; the maintainer read the site at 120% zoom. Every
  dimension derives from this token, so the whole grid scales with it.)
- Style spectrum accents `--style-{learn,mood,drama,play}` encode category
  intensity calm -> loud; `--danger` marks the 18+ unfiltered state. `--line` raised to meet
  WCAG 2.1 SC 1.4.11 AA non-text contrast (>= 3.0:1) on 2026-10-04 (dark `#766E58` at 3.33:1,
  light `#8F8776` at 3.31:1): section borders, table lines, and input boundaries remain clearly visible
  even in direct sunlight and outdoor glare. Section-header icons render at 18px.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--paper` | `#FAF6EF` | `#1F1D14` | background |
| `--ink` | `#1A1815` | `#EDE8DD` | primary text |
| `--ink-soft` | `#4A453C` | `#B0A99A` | secondary text |
| `--line` | `#8F8776` | `#766E58` | hairlines, borders (WCAG AA >= 3:1) |
| `--green` | `#4A7300` | `#84B832` | accent only; calm sage green on dark |
| `--voice-a` | `#4A7300` | `#84B832` | speaker A |
| `--voice-b` | `#8A4200` | `#EA8C35` | speaker B |

All light/dark values meet WCAG AA (>= 4.5:1) against their paper color
(dark paper `#1F1D14` lifted from pure black-brown to warm charcoal for daylight readability;
`--ink-soft` brightened to `#B0A99A` restores AAA on the lighter paper).

Type scale (fluid, clamp-based, single source via CSS tokens):

- h1 (page title): Source Serif 4, 600, `clamp(1.5rem, 4.5vw, 2.7rem)`,
  line-height 1.08, letter-spacing -0.02em, text-wrap balance
  → Token: `--h1-size`, `--h1-weight`, `--h1-line-height`, `--h1-letter-spacing`, `--h1-margin`, `--h1-text-wrap`
- h2 (section headings): Source Serif 4, 600, `clamp(1.5rem, 3.5vw, 2rem)`,
  line-height 1.18, text-wrap balance
  → Token: `--h2-size`, `--h2-weight`, `--h2-line-height`, `--h2-margin`, `--h2-text-wrap`
- lede: `clamp(0.85rem, 2.2vw, 1.08rem)`, color `--ink-soft`, max-width 52ch
  → Token: `--lede-size`, `--lede-color`
- kicker: `--kicker-color` (green-text), mono font
  → Token: `--kicker-color`
- Display fallback (old spec): Source Serif 4, 600, `clamp(2rem, 5vw, 3.5rem)`
- Body: Source Serif 4, 400, 1.06rem/1.65
- Meta/UI: JetBrains Mono, 400, 0.78rem, letter-spacing `0.04em`

Spacing: 4px base grid; section rhythm `--space-6: 64px`.
UI mono size: exactly one, `--ui-size: 13px`; nothing between it and the
serif display/lede sizes.
Radius: 2px on inputs/buttons (print-like), 12px on cards if ever needed.
Shadows: minimal tactile affordance on interactive form controls (`0 1px 2px rgba(0,0,0,0.04)`). Depth comes from type hierarchy and hairlines.

Form controls (Calm Grid doctrine):
- Text inputs (`input[type='text']`, `input[type='url']`, `input[type='search']`): 1.5px solid border, subtle 5-8% surface tint matching dropdowns, uniform `--ui-size` font, 44px min-height, and sage green outline on focus.
- Dropdowns (`select`): 1.5px solid border, subtle 7-8% surface tint background, clear 1.75px stroke chevron arrow. Unmistakable clickability without visual clutter.
- Segmented Controls & Mode Toggles (`.seg`): Enclosed in a `.seg` container (subtle 4% ink-on-paper tint, 1px hairline border, `var(--radius)`). Buttons inside inherit 2px radius, lowercase mono font, muted `--ink-soft` text for unselected options, and the active state fills with high-contrast accent color (`var(--green)` or style category accent) with inverted `--paper` text (bold 600 weight). Unmistakable tactile state at a glance in both dark and light modes with zero ambiguity.
- Dedicated Icon System: Lucide-derived inline SVG icons via `<Icon name="..." />` only. Zero raw Unicode emojis in UI components. Decoration is a defect; icons must be quiet, functional, and inherit `currentColor`.
- Checkboxes (`input[type='checkbox']`): 17px squared box with `--radius`, sage green `#84B832` fill on checked, and paper checkmark.
- Sliders (`input[type='range']`): 6px line track, 16px circular grab thumb in `--green` with scale(1.15) on hover/grab.
- Value Splits (Podcasting 2.0 V4V): Single multi-segment proportion bar with live percentage segments (Creator = `--green`, Source = `--amber`, App = `--line`), intelligent 100% auto-balancing against Creator anchor, locked server-env host node address with fixed badge, and instant presets (70/20/10 trio split, 50/50 creator+app, 34/33/33 equal).
- Host Lineup Preview (Compose): Dynamic preview card at the base of the voices panel showing real-time host pills with custom names, gender icons, selected timbres, and active emotion tags.
- Sticky Quick Launch Bar (Compose): When the user scrolls past the main source input to pick show templates or tweak voices, a compact frosted glass header docks at `top: 0` showing real-time source preview, format badge, and an instant tactile `go` generation button.

Layout:
- Page width: `--content-max-width: 880px` for every screen (desktop max-width; responsive down to 320px). One width only: no screen narrows itself (2026-10-02: settings ran at 640px beside an 880px front page). Long prose keeps a readable measure with `max-width: 52ch`-`65ch` on the text, not on the page.
- Uniform padding: `var(--space-6) var(--space-4)` on all screens

Header (single source of truth in App.svelte):
- One `<header>` per page, rendered in App.svelte. NO duplicate headers
  in child components (AboutScreen, LibraryScreen, FaqScreen, WatchlistScreen)
- Branding: `// vozonda` as `<a href="/">` link (mono, green-text, no underline)
- Every screen has exactly ONE `<h1>`, never h2 for page titles
- Compose: h1 = "Turn sources into your podcast" (no full stop, centred like its lede) + lede "Vozonda reads them, voices make waves, you listen." (voices = voz, waves = onda: the lede spells the name; operator, 2026-10-03)
- Other screens: h1 = "// {screen-name}" (library, faq, watchlist, listen, about)
- `.kicker` class for branding link: color `--kicker-color`, mono font, no decoration
- `.kicker:hover`: underline
- `.lede`: `--lede-size`, `--lede-color`, max-width `52ch`
- Typography tokens in `tokens.css`: `--h1-size`, `--h2-size`, `--lede-size`,
  `--kicker-color`, `--content-max-width`

## Screens

### 1. Compose (home)
Three steps to the first episode, full depth one click away (VOZONDA-UX-1;
NotebookLM's audio overview dialog is the bar). No setting is deleted;
depth moves into one collapsed section instead of showing all at once.

- Step 1 source: the source card with weblink / plain text toggle and
  sticky quick launch bar, plus "+ add source" collecting up to 10 links
  as removable chips. With 2 or more sources the job posts as digest=true
  with digest_sources; with one source nothing changes.
- Step 2 format: four large cards mapped to existing styles (deep dive ->
  balanced, brief -> serious, critique -> socrates, debate -> debate). A
  "more styles" link opens fine-tune, where all 20 styles stay reachable.
  Language shows "auto (detected from source)" by default with a change
  link; auto stays the default so a wrong language cannot be picked by
  accident.
- Step 3 fine-tune / customize: curated show templates with adaptive engine badges,
  hosts and voices, engine, tone, music, speed, gap and the explicit
  rating inside one collapsed section. Sticky across jobs (localStorage),
  and shows a one-line summary of non-default values while collapsed
  ("2 hosts, kokoro, calm, music off").
- Show summary: the show picker summarizes what you get in one honest sentence
  (voices, pacing, length, plus " · script comes to you first" when script
  review is active).
- Script review (customize panel): its own compact row "script" (with the prompts
  icon) as the last row of the customize panel (after length and voices), not inside
  the length card. Renders as a two-state segmented control ("straight to audio" |
  "script to me first") with plain-language explanation naming automated delivery vs
  reading and editing script and title before audio is made. Disabled with
  explanation for multi-source digest shows.
- One primary button ("make it talk") always visible; no modal, no popup.

```
 // vozonda

 ┌ source ─────────────────────────────────────────────────────┐
 │ [ weblink | plain text ]  [ paste a link or youtube url__ ] [ go ] │
 │       plain text mode: full-width textarea, card grows with it │
 └─────────────────────────────────────────────────────────────┘
   (source card: brain icon header, same card style as below)

 ┌ template ───────────────────────────────────────────────────┐
 │ a template is a shortcut: it prefills style, format, voices │
 │ and pacing. fine-tune anything below, your changes win.     │
 │                                                              │
 │ [classic]    [duel]       [solo · calm]   [news briefing]  │
 │  balanced    debate       meditation     serious          │
 │  conv · 2h   conv · 2h    aloud · 1h     conv · 2h        │
 │  natural      fast        slow         natural            │
 └─────────────────────────────────────────────────────────────┘
  (tiles show name + abbreviated context incl. pacing preset,
   no language - stays auto,
    no persistent selected state, brief flash on click only.
    separate card between source and style. layout-grid icon header.
    short explainer sits right below the section header - same
    pattern as every settings section.)

style     learn  [balanced] [eli5] [serious] [socrates]
          mood   [asmr] [meditation] [slang] [noir]
          drama  [sensational] [storyteller] [debate] [courtroom] [clash] [conspiracy] [true_crime] [crisis_room]
          play   [futbol] [dude] [tech_roast] [trivia]
          // balanced tour: curious host, expert guest.

voices    [dialog hosts | solo narrator]
          hosts  [1] [2] [3]
          emotion = how each line is spoken · timbre = which voice performs it
          host A  ▶ [Dylan (m) · young energy · native Chinese ▾]
                  [warm · like sharing good news ▾]
                  [custom name]
          host B  ▶ [Sohee (f) · bright and quick · native Korean ▾]
                  [neutral ▾] [custom name]

language  translate to [auto ▾]   auto follows the source

rating    [clean] [18+ unfiltered]
          no other service allows this. unfiltered: swearing allowed.

[ ⚙ settings ]  pacing · value for value      <- prominent, USP flexibility
```

- Style chips carry NO icons; the four category labels do, one each
  (book/heart/flame/bolt), tinted with the style spectrum tokens.
- Style spectrum tokens encode intensity, calm -> loud:
  `--style-learn` (cool blue) -> `--style-mood` (violet) ->
  `--style-drama` (terracotta) -> `--style-play` (amber). Group label and
  selected chip inherit their category accent; unselected chips stay
  ink-soft. Both themes define their own AA-safe values.
- Section cards: bordered, `color-mix` paper tint, icon + bright ink
  header (same pattern as the settings dashboard). Style chips sit in an
  auto-fill grid; category labels are uppercase, letter-spaced,
  accent-tinted and explicitly non-interactive.
- The style explanation ("what this style delivers") is celebrated: no
  `//` prefix - a lined, centered box with a per-style icon tinted in the
  category accent, serif italic text.
- The settings CTA is deliberately prominent (bordered button, inverts on
  hover): flexibility is the product's USP, the door stays visible.
- Voice rows are two lines: timbre select on top, a 50/50 grid below it
  with per-host emotion and custom name. Emotion is per voice (a/b/c +
  solo), not global; the settings page owns no emotion control. Timbre
  options carry their temperament hint ("Dylan (m) · young energy ·
  native Chinese") so the old long help field fits inside the dropdown.
- Emotion dropdowns render `id · help` from `/meta` (e.g., "warm · like
  sharing good news with a friend"). Emotions vocabulary lives in the
  API (Product Vocabulary); the web only renders. new emotions = one
  API commit, no frontend touch.
- Under the voices header: "style = how the script is written (persona,
  turn length, vocabulary) · emotion = how each line is spoken
  (tone of voice)", a one-line plain-language separator so users
  don't confuse the two axes.
- Voices live here because they belong to THIS episode (per-job voice
  profile, DUE-078); the play buttons probe rendered voice samples.
  On narrow screens the sub grid stacks under the timbre row.

### 1b. Settings (own route `#settings`), nerd dashboard by design

Our users are audio tweak freaks; this page may look like a mixing desk.
Dense mono readouts right-aligned per control, section cards, icons per
section (pacing gauge, v4v bolt, prompts book, engine cpu).

```
← back   settings          qwen_tts · qwen3.6-35b · v0.4.0

[pacing]   playback speed ----o---- 1.00x
           turn gap     ----o---- 380 ms

[value for value]  your lightning address [you@wallet.com]
                   creator split ----o---- 95/5
                   app lightning address [app@sovgrid.org]

[custom prompts]   style [balanced ▾]  key: script.balanced
                   [ 14-line textarea, blank = built-in ]
                   reset to default

[engine]           9 voices · 14 styles · 10 languages
```

- Every control saves instantly to the settings store (no save button).
  A transient "saved" note under the header confirms each write.
- Custom prompts replace the writer prompt entirely per style; the key
  readout shows which setting key is being edited.

### 1c. Legacy compose mask (pre 2026-08-23)

```
// vozonda - Turn sources into your podcast

[ Paste a URL or the article text ________ ]  [ make it talk ]

format   [ two hosts | one narrator ]
style    [ balanced ]  more ▾
         Balanced tour: curious host, expert guest.

demo     live demo
recent   ~/jade-vs-plus  ~/ppq-fallback  ~/sglang-fixes
```

- Slogan (v0.3.0): "Turn sources into your podcast" /
  "No cloud. No accounts. Your machine does the talking."
- Single input, single button, Enter submits. The field takes a URL or a
  pasted article (api tells them apart; bare domains get https://).
- Options live in a FIELD GRID: fixed label column (`format`, `style`,
  `demo`, `recent`, width 64px), values baseline-aligned on one axis.
  Progressive disclosure: only the selected style chip shows, `more ▾`
  expands the rest; the style doc line explains the pick in plain words.
- Style choice is curated, not a wall: four chips (balanced, storyteller,
  tech_roast, futbol) plus an "all styles" expander that shows the rest grouped by
  intent (learn / mood / drama / play). 20 styles total. "all settings" sits
  in the same row.
  The live demo is not on this screen at all; recents stay the archive window.
- One UI type size for all interactive/meta text: `--ui-size: 13px`.
  Display serif and lede stay the only other sizes on this screen.
- Compose hero headline renders only on compose. Footer is centered and
  demarcated with a clean border-top line and generous spacing, carrying
  the secondary places (`about · faq · library · watchlist`) above the
  sovereign metadata tagline. Settings never appears in the footer.
- Episodes are deep-linkable: every listen screen has a unique `#e=<id>`
  url; opening it loads that episode directly, browser-back returns.
- Transcript labels name the actual voice (`A · aiden`), never just host/
  guest; narration stays "narrator". Making of carries a `tuning` row with
  the speed/emotion/gap snapshot taken at render time - jobs made before
  the snapshot simply omit the row instead of guessing.
- The archive answers "why should I listen": each entry shows an LLM-written
  one-sentence hook under its title, and one quiet filterbar row (sort,
  lang, style) above the shelf keeps finding episodes cheap without
  becoming a second options wall.

### 2. Progress (the honest part)

```
// working on: jade-hardware-wallet-comparison

  ✓ fetch      412ms
  ✓ extract    1.2s     3,891 words
  ● script     streaming...  61%
  ○ voice      waiting
  ○ master     waiting
```

- Checklist aesthetic, mono labels, real timings when available.
- Streaming script preview below (serif), so waiting feels productive.
- Cancel is always one click. State survives reload (jobs are server-side).

### 3. Listen (the artifact)

```
Jade vs Plus: A Hardware Wallet Comparison
08:24 min · Aug 31, 2026, 13:30

┌───────────────────────────────────────────────────────────┬──────────────┐
│  [ ▶ ]  by: cipherfox & analyst                           │              │
│                                                           │   [Cover]    │
│  ~~~~~~~~~~~~~~~~~~~~~~~~ Waveform ~~~~~~~~~~~~~~~~~~~~~~ │   [ 1:1 ]    │
│                                                           │  (112×112px) │
│  04:31 / 11:42                    [1.0x] [play options]   │              │
└───────────────────────────────────────────────────────────┴──────────────┘

[ transcript ] [ chapters (3) ] [ takeaways (4) ] [ highlights (2) ] [ clips (1) ] [ facts ]
boost: [+50 sats] [+100 sats] [+500 sats] [custom boost...]       stream: [off] 10/m

18 turns · 1,420 words                              [text options]

  A  cipherfox    "So the firmware bug was five years old?"
  B  analyst      "Older than most people's stacks. That is the story."
```

- Player container features an organic ambient blur backdrop with a clean 2-column layout: left column hosts play button + host byline, full-width interactive Waveform, and time/controls (`[1.0x] [play options]`); right column anchors the sharp 1:1 artwork thumbnail (112x112px).
- Unified episode navigation (`.seg`): consolidates all 6 episode areas into a single tab bar directly under the player. No accordions above or below. Tabs: `transcript`, `chapters (N)`, `takeaways (N)`, `highlights (N)`, `clips (N)`, `facts`.
- V4V boost strip: 1-click sats boost (+50, +100, +500), `custom boost...` action opening the full NIP-57 modal, and sats/min streaming while listening.
- Transcript synced to audio; current line highlighted, click line = seek, quote sharing via link or Nostr NIP-84 highlights. Dedicated `text options` drawer exposes karaoke toggle (default on), chapter breaks in text (default off), autoscroll follow/free toggle, text scale (normal/large/compact), and copy full transcript.
- Chapters navigation: clean index numbering, active state tracking with green accent, clear time offsets, and seek buttons.
- Key takeaways view (60s reader): executive summary card with source quotes and confidence metrics, followed by insight cards with jump-to-audio buttons.
- Community highlights view: Nostr NIP-84 quotes with author npub and jump-to-quote seek buttons.
- Audio clips view: turn-range selection, audio player, MP3 download, share link, and Nostr Clip & Boost.
- Episode facts drawer (mono, quiet): source, format, style, language context, voices, cast, script stats with copy button, audio specs with MP3 download, render duration, community engagement stats (plays, zaps, highlights), and Value4Value Lightning splits.

### Library / Archive

- Banner: `// library · N episodes · X plays · Y highlights · Z sats zapped`
- 2-row toolbar grid:
  - Row 1: Search input (`search by title or topic...`) with search icon and clear button, paired with sort dropdown (`newest`, `most played`, `most highlighted`, `most zapped`, `longest`, `shortest`).
  - Row 2 (content filters & view controls): style select -> type select (single stories, digest bundles, auto from feeds) -> language select -> count indicator (`N of M`), density toggle (`detailed`/`compact`), and `manage` mode toggle.
- Episode engagement metrics: Plays (`▷`), Highlights (`highlighter` / NIP-84), and Zaps (`zap` sats) prominently anchored on every card.
- Management mode: reveals batch toolbar (`select all`, `delete selected (N)`, `delete all`) with inline confirmation prompts and per-row checkboxes.
- Single delete: hover over any episode row reveals quiet trash button for instant single-item removal.

### Empty / error states

- Empty home shows one serif sentence: "Nothing here yet. Paste something
  worth hearing."
- Errors speak plainly in mono: `// voice provider unreachable - retry?`
  Retry inline, never a dead end, never a stack trace.

## Compose style system (2026-08-24, guard against dead-code sweeps)

These rules live in `EssentialsSection.svelte` scoped CSS. They look
removable; they are not. The audit (`apps/web/scripts/audit.cjs`, check
"compose style system intact") fails without them.

- Style chips sit in category groups: 6.5em uppercase label column left,
  chips right. Stacks on <= 480px.
- Category color coding via `.g-learn/.g-mood/.g-drama/.g-play` with
  `--style-*` tokens from tokens.css: colors the group label (inherit),
  the selected chip, and the styledoc icon.
- Styledoc box (style explanation): centered grid, 27px icon on top,
  serif italic centered text, category-colored border. Never flatten to
  a flex row.
- Template card (ex-catch): tiles with name + abbreviated context
  (style · format · hosts). No language in templates - it stays auto.
  No persistent selected state, 600ms flash only. Layout-grid icon.
- Emotion dropdown: neutral option reads "default emotion · neutral" so
  the control announces what it does. Other options: "id · help".
- Voice explainer line: emotion = line delivery, timbre = the speaker's
  acoustic fingerprint. The style part lives in the style card header
  ("how the script is written (persona, turn length, vocabulary)").
- Every section leads with its short explainer right below the header
  (style, template, voices, rating). The voices line covers emotion +
  timbre only; the style part lives in the style card.
- Voice rows use a three-column header row: test (probe play) |
  timbre | name. Hidden below 380px where rows stack. Selects shrink
  with width 100% + min-width 0 so long timbre labels never stretch
  the card.
- Settings entry: "advanced settings" button with centered pitch line
  ("pacing · value for value · custom prompts · engine · much more")
  below the essentials and again under the watchlist feed editor.
  The settings screen itself renders no such CTA (compose branch is
  screen-guarded). Hosted tier may gate access later (#123).
- Settings page hero: h1 "Advanced settings." + lede "Where the show
  gets its edge." - same serif hero as every screen. People may pay for
  this page, it looks like a product.
- App footer carries a "system status" card (engine icon, explainer:
  green = active, grey = installed but idle, hollow = not installed).
  It is the frontend of the doctor backend (doctor.py, GET /doctor):
  every failed check carries a human fix hint. #126 upgrades it to
  dynamic per-check warnings; warnings stay mono + soft, no red alarm.
- Watchlist page (2026-08-24 rework): results first, actions last.
  Order: watched feeds card (rss icon, explainer, your-podcast-feed
  url + copy, feed list) -> auto episodes card (play icon, explainer,
  episode list, "all files stay local" note) -> watch a feed card
  (plus icon, explainer, add form) -> essentials cards at full width
  (never nested inside a card - card-in-card reads as a bug) ->
  centered advanced settings CTA line ends the page. Same card
  pattern as compose essentials: icon + lowercase header, precise
  explainer below, then content.
- Every settings section has a reset control in its header (restores
  shipped defaults for that section's keys, skips keys without a known
  default). The engine section carries the runtime line
  (tts_engine · llm · version) plus a help text explaining how to swap
  engines (registry + restart); a real switch endpoint is planned
  (#124), then the line becomes a select.

## Motion

- Durations: 120ms (hover), 200ms (state change). Easing: `ease-out`.
- The only signature motion: the waveform breathes while playing
  (subtle 2px amplitude oscillation). Nothing else moves unless data moves.
- The running pipeline stage shows a CSS-only braille terminal spinner
  (its own exception to 'nothing else moves unless data moves', operator
  decision 2026-10-01), static under `prefers-reduced-motion`.
- `prefers-reduced-motion`: disable breathing, keep crossfades.

## Accessibility (non-negotiable)

- WCAG 2.2 AA minimum; axe-clean like the blog deploy gate.
- Full keyboard flow: Tab reaches input, button, player, transcript lines.
- Transcript is real DOM text (screen-reader native), `aria-live="polite"`
  for progress steps, `role="status"` for job state.
- Focus ring: 2px `--green`, offset 2px, never removed.

## Performance budget

- Initial JS < 60 KB gzip (hard limit, AGENTS.md rule 9).
- First paint ships only the compose flow and show picker; secondary screens
  (settings, watchlist, listen player, library, faq, about, profile) and
  heavy dialogs load lazily via dynamic import().
- Verified on build via `npm run budget` (scripts/bundle_budget.cjs).
- LCP < 1s local.

## Signature moments (each earns its place by function)

Inspiration blend: Boris' paper calm + Gumroad's typographic confidence +
ClaudeCast's humor. Principles above stay law; every moment below states the
function that justifies it:

1. **Karaoke for thoughts.** While playing, the active transcript line renders
   large and centered like film subtitles; the rest recedes to soft ink.
   FUNCTION: you always know exactly where you are without hunting.
2. **Ink fills as you listen.** Unheard lines are pale, heard lines are full
   ink. The waveform is not a progress bar; your transcript is.
   FUNCTION: progress becomes readable and resumable at a glance.
3. **Voice identity glyphs with live amplitude.** Each speaker has a plain
   glyph (A / B) whose ring thickness follows their actual audio level.
   FUNCTION: see who is speaking while listening away from the screen.
4. **Quote cards for sharing.** Highlight clips render a clean quote card:
   best line in Source Serif on paper, QR to the clip, split shown openly.
   FUNCTION: shareable artifact that carries content AND payment route.
5. **Keyboard is a first-class citizen.** `/` focuses input, `space`
   play/pause, `j/k/l` seek, `.` mark highlight, `?` shows the map.
   FUNCTION: power users never touch the mouse.

Rejected as decoration (see Anti-patterns): button waveforms reacting to
typing, paper grain textures, checklist-to-waveform morphs, book-spine shelves,
glyph facial expressions per style. Each was charming; none informed.

Motion budget stays strict: nothing moves unless data moves. Reduced-motion
keeps state differences visible.

## Platform decision

**PWA first (phases 1-2), Android via Boris fork (phase 3).**

- The pitch needs something installable on any device today: one codebase,
  offline shell, homescreen icon, works desktop + mobile.
- Android native comes as a Boris fork reusing its reader, highlights, and
  Zapstore path; it calls this API for audio.
- No Electron. No app-store gatekeepers. Distribution: URL + Zapstore.

## Anti-patterns (will not ship)

- Curation over mass (2026-08-24, maintainer): competitors like tts.ai dump
  40+ models, hundreds of voices and every slider (SSML, pitch, CFG
  weight) into one page. We win by EDITING the option space: 15 curated
  styles, curated timbres with personalities, five templates, opinionated
  defaults. We never blindly expose every knob a backend offers.

- Decorative elements without informational value: grain textures, ambient
  animations, morph transitions between equal-information states.
- Spinners. Progress is a checklist with real stages or it does not exist.
- Gradients, glassmorphism, confetti, emoji in UI copy.
- Settings sprawl. Provider selection lives behind one gear icon, defaults
  are opinionated.
- Skeleton screens longer than 300ms; show the checklist instead.

## Three-level compose & watchlist mask (2026-08-22, decided with the maintainer)

SUPERSEDED (2026-08-24): this spec described a SettingsPanel modal with
L2/L3 expanders. The built reality replaced it: source card + template
card + inline essentials on compose, advanced settings as its own page,
shared EssentialsSection component. Kept for history - do not build
from this section; the card system sections above are the contract.

Core belief: settings depth and quality is what beats the cloud default
machines. Nothing gets cut in this rework; depth becomes visible instead
of hidden behind a popup.

Levels, all flat, no nesting:

- L1 always visible: the source field (url or pasted text) plus the one
  button. On watchlist: feed url plus subscribe. No frame around L1 -
  the page is the frame.
- L2 "all settings" expander: styles (chips + groups), format, language,
  tone / narrator mood, hosts count with per-host timbres, and a short
  voice preview per timbre.
- L3 "advanced" expander, separate from L2 (never nested): editable
  script prompts per style, the explicit 18+ switch, speed, gap between
  speakers, voice emotion.

Rules:

- Both expanders are independent and sticky across jobs; nothing closes
  itself on submit.
- Frames appear only while a level is expanded; collapsed levels are one
  quiet line. The maintainer adds the fine structural lines by hand.
- One shared panel component renders L2/L3 for compose AND watchlist;
  identical design guaranteed by code reuse, not discipline.
- Watchlist values are stored per feed at subscribe time (the mask state
  freezes into the feed config); editing a feed reopens the same mask.
- Explicit 18+ is per job / per feed, not a global switch - feeds can mix,
  and RSS marks exactly the loud items as explicit.
- The settings modal dies. Its content lives on inside the panel.

## Brand (2026-10-03)

Logo, icon and rules live in `brand/` (see `brand/README.md`): a square speech bubble holding
the player's waveform, four bars played (green), three to come. Outline mark from 24 px,
solid icon below. Colours are the tokens above; the wordmark is Source Serif 4 at 640.
Every new UI uses the tokens (`--font-mono`, `--ui-size`, `--danger`, ...), never raw px font
sizes or invented variable names: the source tray shipped `var(--mono)` and 11px help texts
that broke the look in dark mode.

