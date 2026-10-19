# 00 — Setup: account, models and first deploy

**Goal:** you'll have the non-Bedrock infrastructure running in us-east-1, `config/models.json` filled in, and cost tracking switched on.

## 1. Pick your models (Bedrock console, read-only)

Open **Amazon Bedrock → Model catalog** in **us-east-1**.

**Concept: model IDs vs inference profiles.** A model ID such as `anthropic.claude-haiku-…` names one model in one Region. Newer models are often only callable on-demand through a **cross-Region inference profile**, which comes in two kinds:

| Profile | Example | Where requests may run |
|---|---|---|
| Geographic | `us.anthropic.claude-haiku-5-5` | Any Region in that geography (US) |
| Global | `global.anthropic.claude-haiku-5-5` | Any commercial AWS Region worldwide |

Either way you *call* the profile from your source Region (us-east-1), and Bedrock picks where to run it. Global gives the most capacity headroom and is typically priced a little below geographic, so check the pricing page. Choose geographic only if data residency matters. This project has no residency requirement, so it **defaults to global, with the `us.` profile of the same model as the fallback**. Use the fallback for any console feature that doesn't list global profiles.

What this means for IAM: a role that calls a profile must be allowed to use the *profile* ARN **and** the underlying foundation model in every Region the profile can route to. For a global profile, that means a Region wildcard on the foundation-model ARN. You'll meet this again in Module C, when the agent's service role is created.

For each role in `config/models.json`, find the model and copy the exact ID or inference profile ID:

| Role | Model | Where it's used |
|---|---|---|
| `agent` | Claude Haiku 5.5 (`global.`). The `fallback` is the `us.` profile | Coach agent (Module C) |
| `flow` | Claude Haiku 5.5 (`global.`) | Prompt node in the Flow (Module D) |
| `compare` | Amazon Nova Lite and Amazon Nova Pro | Prompt comparisons (Module E) |
| `judge` | Claude Sonnet 5.5 (`global.`) | LLM-as-a-judge evaluation (Module F) |
| `embeddings` | Titan Text Embeddings v2, 1024 dimensions | Knowledge Base (Module A) |

To list the profiles from the CLI:

```bash
aws bedrock list-inference-profiles --region us-east-1 \
  --query 'inferenceProfileSummaries[].[inferenceProfileId,inferenceProfileName]' --output table
```

Then check:

```bash
cd services && uv run python ../scripts/validate_config.py   # warns about any REPLACE_ME left
```

> **Self-check:** (1) Why might an on-demand call to a bare model ID fail with "on-demand throughput isn't supported" while a profile for the same model works? (2) A company must keep EU customer data in the EU. Which profile type should it use, and what would a `global.` profile risk?

## 2. Activate the cost allocation tag (a day after step 4)

Every resource CDK creates is tagged `project=cycling-coach`. The project budget filters on that tag, but AWS only sees the tag after you activate it:

**Billing and Cost Management → Cost allocation tags → User-defined → `project` → Activate.**

**You can't do this yet.** A user-defined tag key only appears in that list once at least one resource carries it, and it can take up to 24 hours to show up after that. Do step 4 first, then come back the next day. Costs are only tracked by the tag from the moment you activate it, so the project budget shows $0 until then. Tag the Bedrock resources you build by hand with `project=cycling-coach` too, so they count towards this budget. Your account-wide `$100 Monthly Cost Budget` and the `Default-Services-Monitor` anomaly monitor stay in place as the overall backstop.

## 3. Fill in the CDK context

In `infra/cdk.json`, set:
- `budgetEmail`: where budget alerts are sent.
- `githubRepo`: `owner/repo`, for the OIDC deploy role.

`athleteId` (Strava) and `withingsUserId` are already filled in from the old systems.

## 4. First deploy (from your machine)

```bash
cd infra
npm ci
npx cdk bootstrap aws://022074716478/us-east-1      # once per account and Region
npx cdk deploy CoachData CoachApiGateway CoachApi CoachFrontend CoachCicd
```

`CoachStrava` and `CoachWithings` are deployed in runbooks 01 and 02, after their secrets exist.

Create your user. Self sign-up is disabled, so this is the only way in:

```bash
POOL=$(aws cloudformation describe-stacks --stack-name CoachApiGateway \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)
aws cognito-idp admin-create-user --user-pool-id "$POOL" --username <your-email> \
  --user-attributes Name=email,Value=<your-email> Name=email_verified,Value=true
```

Cognito emails a temporary password. You'll set a new one at first sign-in.

## 5. Wire up GitHub Actions

1. Push this repo to GitHub (`githubRepo` above).
2. Set the repository variable `AWS_DEPLOY_ROLE_ARN` to the `DeployRoleArn` output of `CoachCicd`.
3. Create a `production` environment. You can optionally require a reviewer on it.

From then on, every push to `main` runs CI and then deploys. Every pull request runs CI only.

## 6. Run the frontend locally (optional)

```bash
cd frontend && cp .env.example .env.local   # fill in from the CoachApiGateway outputs
npm ci && npm run dev
```

## Cost check

Before any Bedrock work, the stacks cost close to nothing while idle: on-demand DynamoDB, Lambda, HTTP API, the Cognito free tier, and Amplify hosting at pennies. Secrets Manager is about $0.40 per secret per month.
