#!/usr/bin/env bash
# Fetch a week of Intervals.icu wellness records and list every field that has
# a value, to decide which daily-log form fields Intervals can replace.
#
# Usage: scripts/intervals_probe.sh [days]
# Needs: aws CLI credentials for us-east-1, jq, and the intervals/api secret
# (documentation/labs/03-intervals.md).
#
# The output contains personal health data, so it goes to a git-ignored folder.
set -euo pipefail

DAYS="${1:-7}"
REGION="${AWS_REGION:-us-east-1}"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/documentation/initial-setup-documentation/intervals-example-responses"
mkdir -p "$OUT_DIR"

SECRET="$(aws secretsmanager get-secret-value --region "$REGION" --secret-id intervals/api --query SecretString --output text)"
ATHLETE="$(jq -r '.athlete_id // "0"' <<<"$SECRET")"
KEY="$(jq -r '.api_key // empty' <<<"$SECRET")"
[[ -n "$KEY" ]] || { echo "No api_key in intervals/api." >&2; exit 1; }

NEWEST="$(date +%F)"
OLDEST="$(date -d "-${DAYS} days" +%F)"
OUT="${OUT_DIR}/wellness_${OLDEST}_${NEWEST}.json"

curl -sS --fail-with-body -u "API_KEY:${KEY}" \
  "https://intervals.icu/api/v1/athlete/${ATHLETE}/wellness?oldest=${OLDEST}&newest=${NEWEST}" \
  | jq . > "$OUT"

echo "Saved $OUT"
echo "Fields with a value on at least one day (count of days):"
jq -r '[.[] | to_entries[] | select(.value != null and .value != "") | .key] | group_by(.) | map("\(.[0]) \(length)") | .[]' "$OUT" | column -t
