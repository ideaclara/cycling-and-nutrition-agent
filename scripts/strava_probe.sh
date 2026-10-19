#!/usr/bin/env bash
# Fetch one activity with every field Strava returns, to check the real payload
# against the (sometimes out-of-date) developer documentation.
#
# Usage: scripts/strava_probe.sh [activity_id]
# Needs: aws CLI credentials for us-east-1, jq. Run after the OAuth flow has
# stored tokens in the strava/oauth secret (documentation/labs/01-strava.md).
#
# The token is read from Secrets Manager. If it has expired, call
# POST /strava/sync once first (the Lambdas refresh it), then rerun this script.
set -euo pipefail

ACTIVITY_ID="${1:-19378104521}"
REGION="${AWS_REGION:-us-east-1}"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/documentation/initial-setup-documentation/strava-example-responses"
OUT="${OUT_DIR}/activities_${ACTIVITY_ID}_all_efforts.json"

BUNDLE="$(aws secretsmanager get-secret-value --region "$REGION" --secret-id strava/oauth --query SecretString --output text)"
TOKEN="$(jq -r '.access_token // empty' <<<"$BUNDLE")"
EXPIRES_AT="$(jq -r '.expires_at // 0' <<<"$BUNDLE")"
[[ -n "$TOKEN" ]] || { echo "No access_token in strava/oauth: complete the OAuth flow first." >&2; exit 1; }
(( EXPIRES_AT > $(date +%s) )) || { echo "Token expired: trigger POST /strava/sync to refresh it, then retry." >&2; exit 1; }

curl -sS --fail-with-body -X GET \
  "https://www.strava.com/api/v3/activities/${ACTIVITY_ID}?include_all_efforts=true" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/json" \
  -D >(grep -i ratelimit >&2) \
  | jq . > "$OUT"

BYTES=$(stat -c %s "$OUT")
GZ=$(jq -c . "$OUT" | gzip -9 | wc -c)
echo "Saved ${OUT}"
echo "Payload: ${BYTES} bytes pretty-printed, ${GZ} bytes gzip-compressed (inline limit 350000)"
echo "Top-level keys:"; jq -r 'keys[]' "$OUT" | paste -sd' ' -
echo "segment_efforts: $(jq '.segment_efforts | length' "$OUT")  laps: $(jq '.laps | length' "$OUT")"
