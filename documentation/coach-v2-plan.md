# Plan: Coach v2 — more data sources, analysis, daily advice, chat, eating-behaviour KB

## Context
The original build plan (Phases 0–6) is implemented and deployed:
- Strava, Withings, the daily-log API, the action-group Lambdas, the Amplify form behind Cognito sign-in, and CI/CD.
- Module A (Knowledge Base) is finished, with `coach-kb-semantic-v2` plus reranking as the chosen KB. It has three data sources: library, tables and papers.

You now want the coach to grow beyond a lab, with costs near zero and charged only when used. This plan adds:
1. More data sources, starting with **Intervals.icu**. It is the official, key-based route to the Garmin wellness data, and it replaces TrainingPeaks for CTL, ATL and TSB.
2. An **analysis page** with charts. What it shows will be designed together before any of it is built.
3. **Daily advice** from the latest data, shown on the home page.
4. A **chat page** that can use either **Bedrock Agents** (Module C, built in the console) or **AgentCore Runtime** (a new Module G), switchable side by side.
5. **Knowledge Base articles on overconsumption and binge-eating**, drawn from your material and from open-access sources I propose.

Some things don't change:
- **Auth:** the existing Cognito sign-in (`<Authenticator hideSignUp>` plus a JWT authorizer) stays as it is.
- **Bedrock is manual:** you build every Bedrock resource (guardrail, agent, AgentCore runtime, prompts, flows) from runbooks. Claude writes the code, schemas and runbooks.
- **Cost rule:** nothing has an idle charge. That means Lambda, HTTP API and on-demand DynamoDB, Bedrock Agents (no idle cost), and the AgentCore Runtime microVM type, never the Instances type. Any new secret adds $0.40 a month.

## Workstreams, in build order

### 1. TODO.md updates (first commit)
Add:
- the lab modules B–H from the appendix, as a checklist
- the form field review (2a-review)
- the decision on deleting the three older Knowledge Bases
- direct Garmin access only for gaps Intervals can't fill
- RideWithGPS routes and the ride-weather tool
- the parked data sources (see 2e)

### 2. Data sources
Each new source copies the Strava and Withings pattern:
- the secret is created by hand in Secrets Manager
- a probe script saves a sample response, git-ignored, which decides the attributes
- a scheduled sync Lambda, plus a `POST /<source>/sync` route
- an on-demand DynamoDB table keyed `athleteId` + `date`
- tests with moto and fixtures

**2a. Intervals.icu (do first)**
- **Secret:** `intervals/api` holds `{athlete_id, api_key}`. The API uses Basic auth, with user `API_KEY` and the key as the password.
- **Probe:** `scripts/intervals_probe.sh` calls `GET /api/v1/athlete/{id}/wellness?oldest=…&newest=…` and fetches one activity.
- **Table `IntervalsDaily`** (PK `athleteId`, SK `date`):
  - wellness: HRV, resting HR, sleep seconds and score, readiness, weight, steps, plus `kcalConsumed` and macros if MyFitnessPal reaches Intervals through Garmin; the probe will show whether it does
  - load: CTL, ATL, form, ramp rate
- **Sync:** `services/intervals/sync/handler.py` runs every 6 hours, fetching the last 7 days so late edits are picked up. A backfill starts from 2026-01-01. Power curves (`/power-curves`) are fetched on demand for the analysis page.
- **CDK:** a new `infra/lib/intervals-stack.ts`, with the table in `data-stack.ts`.
- **Form:** Garmin and TrainingPeaks fields are prefilled from `IntervalsDaily` and marked "from Intervals". Typing a value still overrides them; manual values win. `get_daily_metrics` merges `IntervalsDaily` the same way.
- **Later:** a "write planned workout" agent action to the Intervals calendar.

**2a-review. Data-entry form field review (a checkpoint right after the Intervals probe)**

For each existing form field, decide whether to **remove** it (Intervals always has it), **prefill** it (Intervals usually has it, and manual entry overrides), or **keep it manual** (Intervals doesn't have it). The candidates are:

| Group | Fields | Likely outcome |
|---|---|---|
| Garmin | readiness, overnight HRV, resting HR, sleep duration, sleep score | prefill from Intervals wellness |
| TrainingPeaks | CTL, ATL, TSB, TSS, IF | replace with Intervals CTL, ATL and form; TSS and IF come per activity |
| Xert | TP, HIE, PP, LTP, low/high/peak XSS | keep manual, since Intervals has no Xert data (it has its own eFTP, W′ and Pmax) |
| Body | waist | keep manual |
| DQS | servings | keep manual |

Changes go into `services/common/daily_log_schema.py` (`FIELDS`), which the form reads through `GET /daily-log/schema`. Existing data isn't touched; removed fields just stop showing.

**2a-manual. New manual readings: blood pressure and body temperature**
- These are timestamped readings, and a day can have several. They are not fields on the daily row.
- **New table `ManualReadings`:**
  - PK `athleteId`, SK `<type>#<ISO-8601 UTC timestamp>`, for example `BP#2026-10-21T06:45:00Z`
  - `type` is `BP` or `TEMP`
- **Blood pressure:** `systolic_mmhg` (70–250), `diastolic_mmhg` (40–150, must be below systolic) and `pulse_bpm` (30–220), all integers.
- **Body temperature:** `temp_c` (34.0–42.0, one decimal place).
- **Timestamps:** the user enters a date and time, which is taken as Europe/London and stored as UTC. Times in the future are rejected.
- **API:** `POST /readings`, `GET /readings?from=&to=&type=` and `DELETE /readings/{type}/{ts}`, in `services/coach/readings/handler.py`.
  - Validation follows the `daily_log_schema.py` pattern in a new `common/readings_schema.py`, also served to the form.
- **Form:** a new "Readings" section with a date-and-time input and the BP and temperature inputs, plus a list of that day's readings that can be deleted.
- **Reuse:** `get_daily_metrics` and `/analysis/series` include each day's readings.
- **Withings:** if you have a Withings BP monitor, the Withings sync already stores BP (measure types 9, 10 and 11). The analysis page then shows both sources, labelled.

**2b. Garmin directly:** parked until the Intervals probe shows what's missing, such as Body Battery or stress. If it's needed, use `python-garminconnect` with its tokens in Secrets Manager, and note the risk under Garmin's terms.

**2c. RideWithGPS:**
- Use the official API (API key plus your auth token).
- Store planned routes in a `PlannedRoutes` table, with track points and elevation in the data bucket as gzip JSON.

**2d. Ride weather (an Epic Ride Weather replacement):**
- Use the **Open-Meteo** forecast API, which is free and needs no key.
- Sample the route points at the times you'll reach them, from the start time and an expected speed based on your power and the elevation profile.
- Expose it as a tool `route_forecast(route_id, start_time)`. This is a good candidate for the MCP server already in TODO.md, alongside `power_levels` and `carb_target`.

**2e. Covered through another source, no new work:**
- Rouvy and Zwift rides reach us through Strava.
- Komoot routes go through Garmin or RideWithGPS.
- TrainingPeaks is replaced by Intervals.
- Zwift events are out of scope.

**Dropped:** Google Fit. Its REST API is deprecated and shutting down, and Health Connect works only on the device, with no cloud API. Garmin and Intervals already cover steps and heart rate.

**About community MCP servers** (for Strava, Intervals and Garmin):
- They run as local stdio processes for desktop clients such as Claude Code. That makes them useful for exploring a source from Claude Code, but the coach can't use them for ingestion.
- The coach needs history in DynamoDB for charts and trends, so it ingests through the APIs.
- MCP comes into the project in Module G (AgentCore Gateway exposes our Lambdas as MCP tools) and in the calculator MCP server from TODO.md.

### 3. Analysis page
- **Backend:** add `GET /analysis/series?from=&to=` to the coach API. It returns per-day series merged from `DailyFitnessLog`, `IntervalsDaily` and `WithingsTelemetry`, plus daily Strava totals: moving time, kJ, and XSS or TSS.
  - It goes in a new `services/coach/analysis/handler.py`, reusing `common/ddb.py`, `common/dates.py` and the Withings and Strava readers in `services/coach/actions/get_daily_metrics/handler.py`. Those readers will be factored into `common/metrics_repo.py` so that advice and analysis share them.
- **Frontend:**
  - Navigation with **Log, Coach, Analysis** tabs, using `react-router-dom` with `HashRouter` so Amplify needs no rewrite rules.
  - Charts in **Recharts**. Load the `dataviz` skill before designing them.
- **Design discussion first:** a short session where we agree on the views before any code. Candidates:
  - a performance management chart (CTL, ATL, TSB)
  - HRV and resting heart rate against a rolling baseline band
  - weight, body fat and waist
  - weekly Diet Quality Score
  - weekly volume and kJ
  - power curve: season best against the last 42 days

### 4. Daily advice
- **Lambda** `services/coach/advice/handler.py`:
  - It runs on EventBridge at 07:30 Europe/London, after the morning syncs, and on demand through `POST /advice/refresh`.
  - It gathers today's metrics through `common/metrics_repo.py`.
  - It writes to a **`CoachAdvice`** table (PK `athleteId`, SK `date`), holding the text, the model, the inputs used and the guardrail result. It's a separate table so it never collides with form PUTs.
  - `GET /advice/latest` serves it.
- **Three versions, switched by a config value**, so you see the same feature built three ways:
  - **v1 (now):** the Converse API with the `flow` model from `config/models.json`, a prompt template in `bedrock/prompts/daily-advice.md`, and `guardrailConfig` once Module B exists.
  - **v2 (after Module E):** a managed prompt invoked by its ARN.
  - **v3 (after Module D):** `InvokeFlow` on the flow alias.
- **Frontend:** an advice card at the top of the Log page, showing which inputs it was based on and how fresh they are.

### 5. Chat (Bedrock Agents and AgentCore, side by side)
- **Route:** `POST /chat` with `{message, sessionId, backend: "agent" | "agentcore"}`, handled by `services/coach/chat/handler.py`:
  - `agent` calls `InvokeAgent(agentId, agentAliasId, sessionId, enableTrace=True)` and returns the answer, the KB citations and any guardrail intervention.
  - `agentcore` calls `InvokeAgentRuntime(runtimeArn, runtimeSessionId)`.
  - IDs and ARNs come from CDK context values (`agentId`, `agentAliasId`, `agentRuntimeArn`). They're empty until you build each one, and the route returns 503 "not configured yet" until then.
  - CDK grants only `bedrock:InvokeAgent` and `bedrock-agentcore:InvokeAgentRuntime` on those ARNs. Those permissions sit on our own Lambda, not on a Bedrock resource.
- **Transcript:** a `ChatMessages` table (PK `sessionId`, SK timestamp) with a 30-day TTL, so the page can show history.
- **Timeout:** HTTP API stops waiting after 30 seconds. Start synchronous. If real turns take longer than about 25 seconds, switch to an asynchronous pattern: `POST` returns a `turnId` and the page polls `GET /chat/{turnId}`.
- **Frontend Coach tab:**
  - message list with a backend switch
  - "new session" button
  - collapsible citations, and a visible marker when the guardrail blocks something, which is useful for studying
- **Runbooks, in dependency order:**
  - **Module B (Guardrails)**, including the eating-behaviour safety topics from §6
  - **Module C (Bedrock Agents)**, with the three action groups, the KB `S0TE1PL4MW`, the guardrail and an alias
  - **Module G (AgentCore)**: Claude writes a Strands agent in `agentcore/coach/` that uses the same tools. Your Lambdas become MCP tools through AgentCore Gateway, it adds a KB retrieve tool and short-term Memory, and it runs on the microVM runtime with a short `idleRuntimeSessionTimeout`. You deploy it by following the runbook.

### 6. Knowledge Base: overconsumption and binge-eating
- **Your strategy document:** export it from Google Docs as **Markdown (.md)** to `~/Documents/Racing/S3 Vectors Folder/eating_behaviour/`, a new folder next to `nutrition/`, `periodisation/` and `power_models/`.
  - That folder is the "raw" source tree. `scripts/prepare_kb_docs.py` only reads it, and writes the cleaned copies to the git-ignored `bedrock/kb-docs/`, which is what gets uploaded to the KB source bucket.
  - The script gets a new handler for `eating_behaviour/` that sets `domain: eating_behaviour`, `source_type: strategy` and the document title.
  - `prepare_kb_docs.py` then treats it like the book chapters: each table becomes its own `tables/` document with labelled rows and the minus signs kept, and the prose stays in `library/`.
  - The script needs one new clean-up step for Google's Markdown export: stray backslash escapes such as `\-` and `\.`, `<br>` tags inside table cells, and image links, which are dropped.
  - Also keep a PDF export, just to compare against visually.
- **Review of your document first:** before proposing anything, Claude reads your strategy document (locally only, never committed) and writes a short gap analysis:
  - the topics it covers well
  - the claims that would benefit from a cited source
  - the topics it doesn't cover, for example athlete-specific appetite after long rides, the link between restriction and bingeing as described in the IOC REDs paper already in the KB, and when to seek clinical help

  **The proposed list of open-access sources is built from that gap analysis**, so it adds evidence and missing topics rather than repeating what your document already covers.
- **Sources:** your material plus a list I propose. The list will be open-access guidelines and reviews, each with its licence, covering:
  - appetite regulation in endurance athletes
  - how restriction leads to bingeing
  - mindful eating and behavioural strategies
  - when to seek help

  It goes into the raw folder, which stays local and git-ignored.
- **Pipeline:**
  - PDFs go under `papers/eating_behaviour/`, which the existing `papers` data source already picks up.
  - Book chapters go through `scripts/prepare_kb_docs.py` into `library/eating_behaviour/`, with a new `domain: eating_behaviour`.
  - Add tests to `services/tests/test_prepare_kb_docs.py`. You run the syncs.
- **Safety:** the coach gives behaviour strategies but never diagnoses. Module B adds a denied topic for diagnosing eating disorders and a contextual response that points to a GP or Beat (the UK eating-disorder charity). The eval set in Module F gets scenarios for this.
- **Check:** add three queries to `bedrock/kb/queries.txt` and rerun the reranked comparison on semantic-v2.

## New sessions
Yes. Start a **new Claude session now**, after approving this plan. This one has already been compacted once.

Then use **one session per milestone**. Each starts by reading this plan, `TODO.md` and memory:
1. TODO.md, then Intervals.icu (2a), the form field review (2a-review), and BP and temperature readings (2a-manual)
2. Eating-behaviour KB sources and pipeline (6)
3. Module B runbook (you build the guardrail)
4. Analysis design discussion, then the API and page (3)
5. Daily advice v1 (4)
6. Module C runbook, plus the chat Lambda and Coach tab on Bedrock Agents (5)
7. Module G AgentCore, plus the chat backend switch (5)
8. RideWithGPS, ride weather and the calculator MCP server (2c, 2d, TODO)
9. Modules D, E and F, which also move advice to v2 and v3

## Verification
- **Each Lambda:**
  - pytest with moto and fixtures saved from the probes
  - `ruff check` and `ruff format --check`
  - the frontend `npm run lint`, `npm test` and `npm run build`
  - CI green, and the Deploy run watched after each push to main
- **Intervals:**
  - after the backfill, `IntervalsDaily` has one row per day from 2026-01-01
  - running sync again changes nothing
  - the form shows prefilled Garmin and TrainingPeaks values
- **Analysis:** `GET /analysis/series` for a 90-day window returns every series. The page renders in light and dark mode and at phone width.
- **Advice:**
  - `POST /advice/refresh` writes today's row
  - the scheduled run appears in CloudWatch the next morning
  - the card shows the inputs it used
- **Chat:**
  - with the IDs empty the route returns 503
  - after Module C, a question such as "Can I do VO2 intervals today?" with suppressed HRV is refused or redirected by the agent or guardrail, and the trace and citations appear
  - the same question through AgentCore after Module G gives a comparable answer
  - the Billing console shows no charges on idle days
- **KB:** the new queries rank eating-behaviour sources in the top 2 after reranking, and a diagnosis-seeking question triggers the guardrail.
- **Readings:**
  - a BP reading saved for 07:00 London time is stored with a UTC timestamp, appears in that day's list and can be deleted
  - systolic not above diastolic, a temperature of 45, or a time in the future each get a 400 from both the form and the API

## Appendix: lab modules
Each module has a teaching runbook in `documentation/labs/`. You build the Bedrock resources in the console, and Claude reviews them afterwards with read-only calls.

| Module | Topic | Status | Depends on | What it adds to the coach |
|---|---|---|---|---|
| **A** | Knowledge Bases: S3 Vectors, chunking strategies, parsing, metadata, reranking | ✅ Done | — | `coach-kb-semantic-v2` (library, tables and papers) |
| **B** | Guardrails: denied topics (high intensity when HRV is suppressed, extreme deficits, medical and eating-disorder diagnosis), content and prompt-attack filters, PII, contextual grounding and relevance, versions, `ApplyGuardrail` | Next | A | Safety layer for advice and chat |
| **C** | Bedrock Agents: instructions, three action groups (OpenAPI schemas plus the Lambda resource policy), KB attachment, guardrail, aliases and versions, reading traces, billing check that idle costs $0; optional supervisor with collaborator agents | Planned | A, B | Chat backend "agent" |
| **D** | Flows: input (HRV, sleep, TSB), then KB retrieval, a prompt node, a guardrail and output; versions and aliases | Planned | A, B | Daily advice v3 (`InvokeFlow`) |
| **E** | Prompt Management: versioned prompts with variables, comparing the `flow` model with Nova Lite and Nova Pro, prompt optimization | Planned | — | Daily advice v2 (managed prompt) |
| **F** | Evaluation: about 40 scenarios in `eval_dataset.jsonl` (recovery, DQS maths, ramp rate, grounded refusals, eating behaviour), LLM-as-a-judge with the `judge` model, a KB RAG evaluation | Planned | C (and D) | Quality baseline and regression check |
| **G** | AgentCore: Runtime on microVMs (a Strands agent, idle timeout, per-second billing), Gateway exposing the Lambdas as MCP tools, Memory, Observability | Planned | C | Chat backend "agentcore", side by side with C |
| **H** (optional) | Building an MCP server: tools `power_levels(ftp)`, `carb_target(weight_kg, load)`, `dqs_score(servings)` and `route_forecast(route_id, start_time)`, tested from Claude Code, then served through AgentCore Gateway | Planned | G | Deterministic calculators and ride weather |
