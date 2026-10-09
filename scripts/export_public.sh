#!/usr/bin/env bash
# export_public.sh — create a public-ready copy of the repository.
#
# Usage: scripts/export_public.sh <target-dir>
#
# 1. Creates a temp dir, archives HEAD into it.
# 2. Removes docs/archive/, .fleet-generated, opencode.json and any file
#    that public_scan.py marks as private.
# 3. Initializes git so public_scan.py can run git ls-files.
# 4. Runs public_scan.py on the temp copy; exits 1 on any finding.
# 5. On success, copies the clean tree to TARGET.
#
# This never touches a remote and never runs git push.

set -euo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"
TARGET="${1:?Usage: scripts/export_public.sh <target-dir>}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP" 2>/dev/null || true' EXIT

# ── 1. git archive HEAD → temp dir ─────────────────────────────────
git -C "$REPO_ROOT" archive HEAD | tar -x -C "$TMP"

# ── 2. remove private artifacts ─────────────────────────────────────
rm -rf "$TMP/docs/archive" "$TMP/.fleet-generated" "$TMP/opencode.json"

# ── 3. init git so public_scan.py can ls-files ──────────────────────
git -C "$TMP" init -q
git -C "$TMP" config user.email "public@vozonda.dev"
git -C "$TMP" config user.name "Vozonda"
git -C "$TMP" config gc.auto 0
git -C "$TMP" config maintenance.auto false
git -C "$TMP" add -A
git -C "$TMP" -c gc.auto=0 commit -q --allow-empty -m "public export"

# ── 4. public scan ──────────────────────────────────────────────────
if python3 "$SELF_DIR/public_scan.py" --repo "$TMP" \
    --allowlist "$SELF_DIR/public_scan.allow"; then
  : # scan passed
else
  echo "public_scan found issues in the export – aborting" >&2
  python3 "$SELF_DIR/public_scan.py" --repo "$TMP" \
      --allowlist "$SELF_DIR/public_scan.allow" --json 2>/dev/null || true
  exit 1
fi

# ── 5. copy clean tree to TARGET (with .git so scanner works) ───────
rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -a "$TMP/"* "$TMP"/.git "$TARGET/"
echo "Public export ready at $TARGET"