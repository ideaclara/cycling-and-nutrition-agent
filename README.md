# Cycling & Nutrition AI Coach — Amazon Bedrock Lab

A personal AI cycling and nutrition coach, built as a hands-on lab for the AWS Certified Generative AI Developer – Professional exam. It runs in **us-east-1** and costs less than $100 a month. The full brief is in [`documentation/Amazon Bedrock Lab.md`](documentation/Amazon%20Bedrock%20Lab.md).

**Bedrock resources are built by hand in the console, for learning.** This repo holds everything around them: data ingestion, the daily-log API and form, the Lambdas the agent calls, their OpenAPI schemas, and the teaching runbooks.

## Layout

| Path | What |
|---|---|
| `config/models.json` | Single source of model choices for each role (agent, flow, compare, judge, embeddings) |
| `infra/` | CDK (TypeScript): data, API and Cognito, Strava, Withings, coach API, Amplify, GitHub OIDC |
| `services/` | Python Lambdas (standard library + boto3 only) and their pytest suite |
| `frontend/` | Vite + React daily-log form (Garmin, Xert, TrainingPeaks, DQS, waist) |
| `bedrock/action-groups/` | OpenAPI schemas you attach to the agent's action groups |
| `scripts/` | Strava payload probe, Withings migration, config validation, model drift check |
| `documentation/labs/` | Runbooks, starting with [`00-setup.md`](documentation/labs/00-setup.md) |

## Data

| Table | Keys | Fed by |
|---|---|---|
| `StravaActivities` | `athleteId` / `<start_date>#<activityId>` | Strava sync every 6 hours (full payload, gzipped) |
| `WithingsTelemetry` | `USER#<id>` / `WITHINGS#MEAS#<epoch>` | Withings Step Functions pipeline, hourly |
| `DailyFitnessLog` | `athleteId` / `YYYY-MM-DD` | The form and the `log_dqs_entry` agent action |

## Develop

```bash
(cd services && uv sync && uv run pytest && uv run ruff check . ../scripts)
(cd infra && npm ci && npx tsc --noEmit && npx cdk synth --quiet)
(cd frontend && npm ci && npx vitest run && npm run build)
```

Pull requests run CI. Pushes to `main` run CI and then deploy, through `.github/workflows/deploy.yml`.
