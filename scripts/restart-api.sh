#!/usr/bin/env bash
# restart-api.sh - restart vozonda-api without killing in-flight renders.
#
# The startup reconciliation (DUE-028) marks running jobs as failed on
# boot. A blind `systemctl --user restart` therefore turns every active
# render into a graveyard entry. This guard makes that mistake hard.
#
# Usage:
#   ./scripts/restart-api.sh            restart, refuses while jobs run
#   ./scripts/restart-api.sh --force    restart anyway (kills renders)
#
# Exit codes: 0 = restarted, 1 = refused (jobs running), 2 = api unreachable

set -euo pipefail

RUNNING=$(curl -s --max-time 5 'http://127.0.0.1:8787/jobs?limit=50' 2>/dev/null \
  | python3 -c "import json,sys; print(len([j for j in json.load(sys.stdin).get('jobs',[]) if j['state']=='running']))" \
  2>/dev/null) || RUNNING=""

if [ -z "$RUNNING" ]; then
  echo "api unreachable on 127.0.0.1:8787 - restarting anyway (it is down)."
elif [ "$RUNNING" -gt 0 ] && [ "${1:-}" != "--force" ]; then
  echo "REFUSED: $RUNNING job(s) currently running. A restart marks them failed."
  echo "Wait for them to finish, then re-run. Or: $0 --force (kills renders)."
  exit 1
fi

systemctl --user restart vozonda-api
sleep 3
curl -s --max-time 5 http://127.0.0.1:8787/meta > /dev/null && echo "vozonda-api restarted and answering." || {
  echo "restarted but /meta not answering yet - check: journalctl --user -u vozonda-api"
  exit 2
}
