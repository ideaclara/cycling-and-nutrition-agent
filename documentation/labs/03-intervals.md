# 03 — Intervals.icu: wellness and fitness data

**Goal:** Intervals.icu fills `IntervalsDaily` every 6 hours with the Garmin data it
syncs: HRV, resting HR, sleep and readiness. It also adds its own fitness (CTL) and
fatigue (ATL) values. The daily form then shows these as prefills, so you only type
what Intervals doesn't know.

## How it works

```
EventBridge (every 6h) ─┐
POST /intervals/sync ───┴─> intervals-sync ──> GET /api/v1/athlete/{id}/wellness ──> IntervalsDaily
```

- **First run:** when the table is empty, it backfills from 2026-01-01.
- **Later runs:** it re-fetches the last 7 days, because Intervals keeps updating recent days when Garmin syncs late or fitness is recalculated. Only days that changed are written.
- **What's stored:** every non-null field Intervals returns. The probe below shows which ones you actually have.
- **What reads it:**
  - The daily form shows Intervals values as greyed placeholders marked "From Intervals.icu". Typing a value overrides it, and only what you type is saved to `DailyFitnessLog`.
  - The agent's `get_daily_metrics` returns both. Its instructions say to prefer your typed value.

## 1. Get your API key and athlete ID

In Intervals.icu, go to **Settings → Developer Settings**:
- **API key:** generate one if there isn't one yet.
- **Athlete ID:** shown on the same page. It looks like `i123456`.

## 2. Create the secret

Store it in a file first, so the key never appears in your shell history:

```bash
umask 077
cat > /tmp/intervals.json <<'JSON'
{"athlete_id": "i123456", "api_key": "PASTE_KEY_HERE"}
JSON
aws secretsmanager create-secret --region us-east-1 --name intervals/api \
  --tags Key=project,Value=cycling-coach --secret-string file:///tmp/intervals.json
shred -u /tmp/intervals.json
```

The secret costs $0.40 a month. The stack is deployed by CI, and until the secret exists the sync just logs "not configured yet".

## 3. Probe the data

```bash
scripts/intervals_probe.sh 14
```

This saves the raw response to a git-ignored folder and lists every field with a value, along with how many days have it. Look for:
- `hrv`, `restingHR`, `sleepSecs`, `sleepScore` and `readiness`, which come from Garmin
- `ctl`, `atl` and `rampRate`, Intervals' own fitness model
- `kcalConsumed`, `carbohydrates`, `protein` and `fatTotal`, which are present only if MyFitnessPal reaches Intervals through Garmin
- `systolic`, `diastolic`, `weight` and `bodyFat`, if you enter them in Intervals or another app syncs them

**Then do the form field review with Claude** (milestone 1, step 2a-review in `documentation/coach-v2-plan.md`): for each field, remove it, prefill it, or keep it manual.

## 4. Backfill

```bash
aws lambda invoke --region us-east-1 --function-name intervals-sync \
  --cli-binary-format raw-in-base64-out --payload '{}' /dev/stdout
```

This returns something like `{"oldest": "2026-01-01", "newest": "…", "fetched": 293, "written": 293}`. Run it again and `written` should be 0. You can also press **Sync** in the app, which syncs Strava and Intervals together.

## 5. Check

```bash
aws dynamodb query --region us-east-1 --table-name IntervalsDaily \
  --key-condition-expression 'athleteId = :a' --expression-attribute-values '{":a":{"S":"3634905"}}' \
  --select COUNT
```

You should see one item per day since 1 January that Intervals has data for. Then open the form for yesterday: the Garmin and TrainingPeaks fields you didn't type show the Intervals values as placeholders.

## Cost

| Item | Cost |
|---|---|
| Secret | $0.40 a month |
| Lambda (4 runs a day) and DynamoDB (on-demand, a few hundred items) | Under $0.01 a month |
