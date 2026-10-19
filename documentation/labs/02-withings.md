# 02 — Withings: migrate to us-east-1

**Goal:** you'll have the `WithingsTelemetry` history (399 items) copied to us-east-1, and the hourly ingestion running from us-east-1 instead of eu-west-2.

## How it works

```
EventBridge (hourly, created DISABLED)
   └─> Step Functions withings-ingestion
         ├─ RefreshToken   (withings-token-refresher → secret prod/withings/credentials)
         └─ SyncMeasures   (withings-sync-measures → getmeas, last 30 days → WithingsTelemetry)
```

This is the same two-step state machine as the eu-west-2 `UniversalIngestionPipeline`. The AppConfig dispatcher is replaced by a plain schedule, because only the `measures` endpoint is needed. The coach reads the table directly, so the old `GET /telemetry/measures` dashboard API isn't ported.

> ⚠️ **One pipeline at a time.** Withings issues a new refresh token on every refresh and invalidates the old one. If eu-west-2 and us-east-1 both run, whichever refreshes second fails. That's why the new schedule is created **disabled**.

## 1. Copy the secret

```bash
aws secretsmanager get-secret-value --region eu-west-2 --secret-id prod/withings/credentials \
  --query SecretString --output text > /tmp/withings.json
aws secretsmanager create-secret --region us-east-1 --name prod/withings/credentials \
  --tags Key=project,Value=cycling-coach --secret-string file:///tmp/withings.json
shred -u /tmp/withings.json
```

## 2. Deploy

```bash
cd infra && npx cdk deploy CoachWithings
```

## 3. Cut over

1. **Disable** the eu-west-2 schedule:
   ```bash
   aws events disable-rule --region eu-west-2 \
     --name Prod-WithingsIngestionPip-FiveMinuteHeartbeatRule60-cBpxiD9qlnfc
   ```
2. **Copy the history:**
   ```bash
   cd services && uv run python ../scripts/migrate_withings.py --dry-run && uv run python ../scripts/migrate_withings.py
   ```
3. **Re-copy the secret** (step 1 again, with `put-secret-value` in place of `create-secret`). The eu-west-2 pipeline may have rotated the token after your first copy.
4. **Enable** the new schedule:
   ```bash
   aws events enable-rule --region us-east-1 --name withings-sync-hourly
   ```
5. Start one execution by hand from the Step Functions console with this input, so you don't have to wait an hour:
   ```json
   {"secret_name": "prod/withings/credentials", "endpoint_config": {"lookback_days": 30}}
   ```

## Verify

- The execution succeeds, and its output shows `persisted_items` greater than 0.
- A new weigh-in shows up in `WithingsTelemetry` in us-east-1 within an hour.
- Item counts match between Regions, apart from new weigh-ins.

When you're happy, decide separately whether to tear down the eu-west-2 stack.
