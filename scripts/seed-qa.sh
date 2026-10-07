#!/usr/bin/env bash
# seed-qa.sh — render one demo episode via the API so data-dependent audit checks
# have material on fresh instances.
#
# Usage:
#   ./scripts/seed-qa.sh [TEXT|URL]
#
# If no argument, uses a built-in test text about vozonda.
# If argument starts with http, treats as URL; otherwise as pasted text.
# Requires: curl, jq, vozonda-api running on http://127.0.0.1:8787
#
# Documentation for audit.cjs: this script creates a "playable episode in recent"
# so the audit check at line 152-287 (smoke suite) has an audio-bearing job to
# exercise. Run before audit on fresh instances.
#
# Exit codes: 0 = success, 1 = API error, 2 = job failed, 3 = timeout

set -euo pipefail

API_BASE="${VOZONDA_API_BASE:-${VOZONDA_API_BASE:-http://127.0.0.1:8787}}"
DEFAULT_TEXT="This is a test article about self-hosted AI. Vozonda turns articles into podcasts with two AI voices. It runs locally on your own hardware with no cloud dependencies. The pipeline fetches content, extracts readable text, generates a dialogue script with a local LLM, renders voices with local TTS, and stitches everything into an MP3 with transcript."
INPUT="${1:-$DEFAULT_TEXT}"
STYLE="${STYLE:-balanced}"
FORMAT="${FORMAT:-dialog}"
TONE="${TONE:-neutral}"
LANGUAGE="${LANGUAGE:-auto}"
HOSTS="${HOSTS:-2}"
EXPLICIT="${EXPLICIT:-false}"
POLL_INTERVAL=5
MAX_WAIT=300  # 5 minutes max

echo "🌱 vozonda seed-qa: creating demo episode"

# Check API health
if ! curl -sf "$API_BASE/health" >/dev/null; then
  echo "❌ API not reachable at $API_BASE"
  exit 1
fi

# Create job - use text if input doesn't look like URL, otherwise URL
if [[ "$INPUT" =~ ^https?:// ]]; then
  SOURCE_TYPE="url"
  SOURCE_VALUE="$INPUT"
  JOB_JSON=$(jq -n --arg url "$SOURCE_VALUE" --arg style "$STYLE" --arg format "$FORMAT" --arg tone "$TONE" --arg language "$LANGUAGE" --argjson hosts "$HOSTS" --argjson explicit "$EXPLICIT" '{url: $url, style: $style, format: $format, tone: $tone, language: $language, hosts: $hosts, explicit: $explicit}')
else
  SOURCE_TYPE="text"
  SOURCE_VALUE="$INPUT"
  JOB_JSON=$(jq -n --arg text "$SOURCE_VALUE" --arg style "$STYLE" --arg format "$FORMAT" --arg tone "$TONE" --arg language "$LANGUAGE" --argjson hosts "$HOSTS" --argjson explicit "$EXPLICIT" '{text: $text, style: $style, format: $format, tone: $tone, language: $language, hosts: $hosts, explicit: $explicit}')
fi

JOB_RESPONSE=$(curl -s -X POST "$API_BASE/jobs" -H "Content-Type: application/json" -d "$JOB_JSON")

JOB_ID=$(echo "$JOB_RESPONSE" | jq -r '.id // empty')
if [[ -z "$JOB_ID" ]]; then
  echo "❌ Failed to create job:"
  echo "$JOB_RESPONSE" | jq .
  exit 1
fi

echo "✅ Job created: $JOB_ID"

# Poll for completion
ELAPSED=0
while [[ $ELAPSED -lt $MAX_WAIT ]]; do
  JOB=$(curl -s "$API_BASE/jobs/$JOB_ID")
  STATE=$(echo "$JOB" | jq -r '.state // empty')

  case "$STATE" in
    done)
      echo "✅ Job completed successfully"
      TURNS=$(echo "$JOB" | jq -r '.script | length // 0')
      DURATION_MS=$(echo "$JOB" | jq -r '.duration_ms // 0')
      DURATION_SEC=$((DURATION_MS / 1000))
      echo "   Turns: $TURNS"
      echo "   Duration: ${DURATION_SEC}s"
      echo "   Audio: $API_BASE/audio/$JOB_ID.mp3"
      echo ""
      echo "📋 To verify in audit:"
      echo "   Run: npx playwright test apps/web/scripts/audit.cjs"
      echo "   The 'playable episode in recent' check will now PASS"
      exit 0
      ;;
    failed)
      ERROR=$(echo "$JOB" | jq -r '.error // "unknown error"')
      echo "❌ Job failed: $ERROR"
      echo "$JOB" | jq .
      exit 2
      ;;
    running|queued)
      STAGE=$(echo "$JOB" | jq -r '.current_stage // "unknown"')
      echo "⏳ [$ELAPSED s] $STATE ($STAGE)..."
      ;;
    *)
      echo "⚠️  Unknown state: $STATE"
      ;;
  esac

  sleep $POLL_INTERVAL
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

echo "❌ Timeout after ${MAX_WAIT}s waiting for job completion"
exit 3