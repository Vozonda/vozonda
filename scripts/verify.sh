#!/usr/bin/env bash
# One command, every gate. Run before any push; the pre-push hook calls this.
# --full also runs the browser audit against a running preview (needs
# NODE_PATH to a playwright install and services on :8787/:4173).
set -euo pipefail
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX 2>/dev/null || true
export PATH="/home/cipherfox/.nvm/versions/node/v24.18.0/bin:/home/cipherfox/.local/bin:$PATH"
cd "$(dirname "$0")/.."

fail() { echo "// FAIL: $*" >&2; exit 1; }

echo "// ruff"
# --extra tts: the gate must never sync the prod venv without the voice stack
# (uv run defaults to no extras; 8b0ea0b moved torch/qwen-tts into the tts extra)
(cd apps/api && uv run --no-sync --extra tts ruff check src) || fail ruff

echo "// pytest"
(cd apps/api && uv run --no-sync --extra tts pytest -q -n 4) || fail pytest

echo "// svelte-check (workspace)"
(cd apps/web && npx svelte-check --threshold error) || fail svelte-check

echo "// ui emoji guard (templates + script blocks, all svelte files)"
python3 -c "
import re, sys
from pathlib import Path

# Emoji ranges: Supplementary Multilingual Plane (actual emoji)
# Excludes BMP symbols like checkmarks (U+2713), arrows etc. which are fine.
emoji_re = re.compile(r'[\U0001F000-\U0001FFFF]')
violations = []
for f in sorted(Path('apps/web/src').rglob('*.svelte')):
    for i, line in enumerate(f.read_text(errors='replace').splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith('//') or stripped.startswith('*'):
            continue
        if emoji_re.search(stripped):
            violations.append(f'{f.relative_to(\"apps/web/src\")}:{i}: {stripped[:100]}')
if violations:
    print('// FAIL: Raw emoji in svelte source (use <Icon name=\"...\" /> instead):', file=sys.stderr)
    for v in violations:
        print(f'  {v}', file=sys.stderr)
    sys.exit(1)
" || fail "raw emoji in svelte source (use Icon.svelte)"

echo "// radius lint (no hardcoded px except var(--radius), 0, 1px borders, 50%)"
python3 -c "
import re, sys
from pathlib import Path

# Match border-radius declarations with hardcoded px values
# Allow: 0, 0px, 1px (border-width context), 2px (== var(--radius)), 50% (circles), var(...)
ALLOWED = re.compile(r'^(0|0px|2px|50%|var\(|inherit|unset|initial|calc\(var\()')
RADIUS_RE = re.compile(r'border-radius\s*:\s*([^;}\n]+)')
# Waveform progress bars are exempt (visual only, not interactive)
EXEMPT_FILES = {'Waveform.svelte'}

violations = []
for f in sorted(Path('apps/web/src').rglob('*.svelte')):
    if f.name in EXEMPT_FILES:
        continue
    for i, line in enumerate(f.read_text(errors='replace').splitlines(), 1):
        m = RADIUS_RE.search(line)
        if not m:
            continue
        val = m.group(1).strip().rstrip(';').strip()
        if ALLOWED.match(val):
            continue
        violations.append(f'{f.relative_to(\"apps/web/src\")}:{i}: border-radius:{val}')
if violations:
    print('// FAIL: Hardcoded border-radius violates Calm Grid (use var(--radius) or 50%):', file=sys.stderr)
    for v in violations:
        print(f'  {v}', file=sys.stderr)
    sys.exit(1)
" || fail "hardcoded border-radius (Calm Grid: use var(--radius) or 50% for circles)"

echo "// typescript any gate"
python3 -c "
import re, sys
from pathlib import Path

ANY_RE = re.compile(r'(:\s*any\b|as\s+any\b)')
SUPPRESS = re.compile(r'(//\s*ts-any-ok|<!--\s*ts-any-ok|eslint-disable.*@typescript-eslint/no-explicit-any)')
violations = []
for f in sorted(Path('apps/web/src').rglob('*.svelte')) + sorted(Path('apps/web/src').rglob('*.ts')):
    for i, line in enumerate(f.read_text(errors='replace').splitlines(), 1):
        if ANY_RE.search(line) and not SUPPRESS.search(line):
            violations.append(f'{f.relative_to(\"apps/web/src\")}:{i}: {line.strip()[:100]}')
if violations:
    print('// FAIL: TypeScript \"any\" without suppression comment (add // ts-any-ok if intentional):', file=sys.stderr)
    for v in violations:
        print(f'  {v}', file=sys.stderr)
    sys.exit(1)
" || fail "TypeScript 'any' without suppression (add // ts-any-ok if intentional)"


echo "// gen-dev-page"
# Fleet agents run this gate inside their task scope; regenerating the tracked
# dev.html there made every web task fail on a file it never touched
# (VOZONDA-L1 eight times, LAZY-CATCH, 2026-09-24). Humans and CI still regenerate it.
case "${SOVEREIGN_AGENT:-}" in
  fleet-*) echo "  (skipped under the fleet: ${SOVEREIGN_AGENT})" ;;
  *) python3 scripts/gen-dev-page.py || echo "[warn] gen-dev-page failed (kept old dev.html)" ;;
esac

echo "// build"
(cd apps/web && npm run build >/dev/null) || fail build

echo "// svelte-check (fresh worktree, ci truth)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git archive HEAD | tar -x -C "$tmp"
(cd "$tmp/apps/web" && npm ci --silent >/dev/null 2>&1 && npx svelte-check --threshold error) \
  || fail "fresh-clone svelte-check (local workspace lies)"

if [[ "${1:-}" == "--full" ]]; then
  echo "// browser audit"
  (cd apps/web && NODE_PATH="${NODE_PATH:-}" node scripts/audit.cjs) || fail audit
fi

echo "// all gates green"
