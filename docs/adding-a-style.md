# Adding a New Style

The style registry (`vozonda_api/style_registry.py`) is the single source of truth for all style definitions. To add a new style, you must update the registry and its source modules.

## Overview

A style lives in two files:
1. **style_registry.py**: order, doc, hook brief, script params, prompt template,
   TTS speaker instructs, UI group and icon
2. **rhythm.py**: the rhythm profile (speaker shares, turn bands, rules)

`styles.py` only re-exports the registry's views for older imports; never add data there.
The registry builds a frozen `Style` dataclass per style and fails at import if a style
has no profile.

## Step-by-Step

### 1. Add to `style_registry.py`

Add the id to `STYLE_IDS` (canonical order, whisper to shout), a one-line doc to
`STYLE_DOCS`, a hook brief to `HOOK_BRIEFS`, and, only if the style needs other turn
numbers than the global defaults, an entry in `_SCRIPT_PARAMS_OVERRIDES`:

```python
_SCRIPT_PARAMS_OVERRIDES["my_new_style"] = {
    "turns_min": 12, "turns_max": 20, "turn_words_max": 40, "short_reactions": 3,
}
```

Add the prompt template to `STYLE_TEMPLATES`. A style that needs its own version of
a shared rule replaces that line, exactly like asmr ("no conflict at all") or socrates
("the disagreement IS the format"):

```python
STYLE_TEMPLATES["my_new_style"] = """You write podcast dialogue scripts for ...
""" + dialog_rules().replace(
    "- Include one disagreement and its resolution.\n",
    "- The style's own line about conflict.\n",
)
```

Optional: TTS speaker instructs for neutral emotion in `_STYLE_SPEAKER_INSTRUCTS`
(`{"A": "Speak ...", "B": "Speak ..."}`).

### 2. Add a rhythm profile to `rhythm.py`

In `PROFILES`, add a `Profile` entry:

```python
"my_new_style": Profile(
    {
        "A": _sp(0.30, 0.45, (2, 5, 0.25), (10, 20, 0.50), (25, 50, 0.25)),
        "B": _sp(0.55, 0.70, (2, 5, 0.10), (15, 25, 0.35), (35, 65, 0.55)),
    },
    (0.15, 0.30),  # quick_share: fraction of turns that are quick reactions
    (0.10, 0.25),  # questions: fraction of turns with a question mark
    "Style-specific rhythm rules replacing shared ones.",
    hard_max=None,  # or int for absolute turn word cap (e.g. asmr=12)
)
```

Key profile fields:
- `speakers`: dict of speaker id -> `Speaker(share, bands)`
- `quick_share`: tuple(min, max) fraction of quick turns, or `None`
- `questions`: tuple(min, max) fraction of turns with `?`
- `rules`: string inserted into prompt replacing shared rhythm rules
- `hard_max`: optional absolute word limit per turn
- `trend`: optional dict speaker -> (start_factor, end_factor) for length trends
- `rare_third`: optional third host id (e.g. "C" for dude style)
- `no_adjacent_quick`: bool, default True

Use `_sp(lo, hi, (min, max, weight), ...)` to define a speaker's word share range and turn-length bands.

### 3. Add group and icon mapping in `style_registry.py`

In `_STYLE_GROUP_MAP`, assign a group: `learn`, `mood`, `drama`, or `play`.

```python
_STYLE_GROUP_MAP["my_new_style"] = "mood"
```

In `_STYLE_ICON_MAP`, assign an icon name (must exist in `apps/web/src/lib/components/Icon.svelte`):

```python
_STYLE_ICON_MAP["my_new_style"] = "my_icon_name"
```

### 4. Verify

Create the golden prompt fixture for the new style only, read it, then run the tests.
Existing fixtures must not change: a changed fixture means an existing style's prompt
changed, which is a behaviour change, not a refactor.

```bash
cd apps/api && VOZONDA_UPDATE_GOLDEN=1 uv run --no-sync --extra tts pytest tests/test_style_golden.py -k my_new_style
```

Run the style registry tests:

```bash
cd apps/api && uv run --no-sync --extra tts pytest tests/test_style_registry.py -v
```

Also run the existing style tests to ensure backwards compatibility:

```bash
cd apps/api && uv run --no-sync --extra tts pytest tests/test_styles.py -v
```

### 5. Update design doc

If you added a new group, icon, or changed the style taxonomy, update `docs/design.md` in the same commit (design doc wins).

## Custom Styles (users, via the API)

Built-in styles ship with the release. Users also create their own styles at
runtime, without a code change: pick one of five rhythm types and name the two
roles. Custom styles live in SQLite (`custom_styles` table, same DB and
migration pattern as the watchlist) and join the registry at runtime with
group `custom`.

Rhythm types (`rhythm.py`, each a profile builder borrowing its numbers from
the built-in profile named):

| type | like | description |
|---|---|---|
| `peer` | debate | Equal conversation, both hosts argue and answer each other. |
| `host_expert` | balanced | Curious host asks, expert guest explains. |
| `narrator_listener` | storyteller | One host narrates the story, the other reacts and guesses. |
| `interrogator` | socrates | One host asks only questions, the other answers shrink over time. |
| `calm` | meditation | Slow guided turns, no turn longer than twenty-five words. |

Endpoints (write auth for changes, 422 on invalid fields):

- `GET /styles/custom` lists the user's styles
- `POST /styles/custom` with `id` (`custom_<slug>`, slug `[a-z0-9_]{2,30}`),
  `name` (max 40), `doc` (max 120), `role_a` and `role_b` (each max 400),
  `tone` (max 300) and `rhythm_type`
- `PUT /styles/custom/{id}` updates fields; `DELETE` removes the style

Built-in ids cannot be taken or overridden. Custom styles appear in
`GET /meta` (`styles`, `style_docs`, `style_meta`). Their script prompt is the
shared dialogue rules plus a role paragraph from `role_a`, `role_b` and `tone`,
with the rhythm type's contract opening the prompt and its reminder closing
it, through the same code path as built-in styles. A job whose custom style
was deleted renders with `balanced` and logs a warning.

## Registry Architecture

```
style_registry.py (single source of truth)
├── Style dataclass (frozen, complete definition)
├── REGISTRY: tuple[Style, ...] (immutable, built at import)
└── Derived views (backwards compatibility):
    ├── STYLE_IDS, STYLES
    ├── STYLE_DOCS, HOOK_BRIEFS, SCRIPT_PARAMS, STYLE_TEMPLATES
    ├── PROFILES (from rhythm.py)
    ├── _STYLE_SPEAKER_INSTRUCTS
    ├── STYLE_META (for /meta endpoint)
    └── get_style(id) -> Style | None
```

All other modules import from `style_registry` (or `styles` which re-exports the derived views). Style data lives in `style_registry.py`, profiles in `rhythm.py`.

## Testing Checklist

- [ ] New style appears in `GET /meta` under `style_meta`
- [ ] `STYLE_IDS` includes the new style in correct position
- [ ] `STYLE_DOCS`, `HOOK_BRIEFS`, `SCRIPT_PARAMS`, `STYLE_TEMPLATES` have entries
- [ ] `PROFILES` has a valid `Profile` with speakers matching `hosts`
- [ ] `_STYLE_SPEAKER_INSTRUCTS` has entry (empty dict if not needed)
- [ ] `STYLE_META` includes `id`, `doc`, `group`, `icon`, `hosts`
- [ ] No em-dashes in template or doc
- [ ] UI icon exists in `Icon.svelte`
- [ ] Golden fixture created for the new style; no existing fixture changed
- [ ] Tests pass: `test_style_registry.py`, `test_style_golden.py`, `test_styles.py`, `test_rhythm_profiles.py`