#!/usr/bin/env bash
# update.sh - update a native Vozonda installation (git pull, build, safe service restart).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "Updating Vozonda in $ROOT..."
git pull

if [ -d "apps/web" ] && command -v npm >/dev/null 2>&1; then
  echo "Building web frontend..."
  (cd apps/web && npm run build)
fi

if [ -x "./scripts/restart-api.sh" ]; then
  ./scripts/restart-api.sh
elif command -v systemctl >/dev/null 2>&1 && systemctl --user is-active --quiet vozonda-api 2>/dev/null; then
  systemctl --user restart vozonda-api
fi

if command -v systemctl >/dev/null 2>&1 && systemctl --user is-active --quiet vozonda-web 2>/dev/null; then
  systemctl --user restart vozonda-web
  echo "vozonda-web restarted."
fi

echo "Update complete."
