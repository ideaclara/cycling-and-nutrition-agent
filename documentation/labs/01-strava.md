# 01 — Strava: OAuth, payload probe and backfill

**Goal:** you'll have every Strava activity since 1 January 2026 stored in full in `StravaActivities`, with new ones arriving every 6 hours.

## How it works

```
EventBridge (every 6h) ─┐
POST /strava/sync ──────┴─> strava-list-activities
                               │ 1. newest stored activity → `after` (or 2026-01-01)
                               │ 2. GET /athlete/activities?after=…  (pages of 200)
                               ▼
                       SQS strava-activity-fetch-queue  ──(5 failures)──> DLQ
                               ▼
                       strava-fetch-activity-worker
                               │ GET /activities/{id}?include_all_efforts=true
                               ▼
                 DynamoDB StravaActivities (+ S3 if payload > 350 KB gzipped)
```

Each item keeps:
- every **scalar** top-level field as its own attribute (`name`, `distance`, `weighted_average_watts`, `suffer_score` …)
- the **complete response**, gzip-compressed, in `raw_gzip`

Tokens live in the Secrets Manager secret `strava/oauth`. Every Lambda refreshes the token when it is within 5 minutes of expiry.

## 1. Create the secret

Use the client ID and secret from <https://www.strava.com/settings/api>:

```bash
aws secretsmanager create-secret --region us-east-1 --name strava/oauth \
  --tags Key=project,Value=cycling-coach \
  --secret-string '{"client_id":"<id>","client_secret":"<secret>"}'
```

It is created by hand rather than by CDK so that no stack update or teardown can ever overwrite live tokens.

## 2. Deploy and point Strava at the new callback

```bash
cd infra && npx cdk deploy CoachStrava
```

On the Strava API settings page, set **Authorization Callback Domain** to the API host from the `ApiUrl` output, for example `abc123.execute-api.us-east-1.amazonaws.com`. Strava allows one callback domain per app, so this replaces the eu-west-2 domain.

## 3. Authorize

Open `<ApiUrl>/strava/authorize` in a browser and approve. Leave **"View data about your private activities"** ticked: the callback rejects the grant without `activity:read_all`. You should see **Connected**.

The authorize step stores a one-time `state` value in the secret, and the callback checks it. Without that check, anyone who knew the URL could connect *their* Strava account and overwrite your tokens.

## 4. Probe the real payload

```bash
scripts/strava_probe.sh 19378104521
```

The script saves `documentation/initial-setup-documentation/strava-example-responses/activities_19378104521_all_efforts.json` and prints:
- the payload size, raw and gzipped
- the top-level keys
- the number of segment efforts

**Checkpoint, then tell Claude the numbers.** Compare the keys with `services/strava/activity_item.py`. Every scalar key becomes an attribute automatically, so the question is whether any *nested* field deserves flattening (like `gear_name` already is). The gzipped size should be well under 350 KB. If it isn't, the S3 overflow path will handle it.

## 5. Backfill

Sign in to the Amplify app (`AppUrl` output of `CoachFrontend`) and click **Sync Strava** in the header. It calls `POST /strava/sync` with your Cognito token and reports how many activities were queued. The first run should queue everything since 1 January (`after=1767225600`).

Watch progress in CloudWatch Logs (`/aws/lambda/strava-fetch-activity-worker`) or in the SQS console. Your app's read limit is 200 calls per 15 minutes and 2,000 per day, according to the `x-readratelimit-limit` header from the probe, so a backfill of a few hundred rides takes one or two windows. When the worker hits a 429, it hides the message for 15 minutes and the backfill carries on by itself.

## Verify

- `aws dynamodb scan --table-name StravaActivities --select COUNT` matches the number of rides since 1 January on Strava.
- Running sync again queues 0 or 1 activities. The newest one may be re-listed, but the worker skips it because it is already stored.
- The DLQ `strava-activity-fetch-dlq` is empty.

## Cutover

The old eu-west-2 segment stack is no longer needed for this project. Decide separately whether to tear it down.
