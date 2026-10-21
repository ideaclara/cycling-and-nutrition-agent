# To-do

## Reference tables as deterministic data

Tables the coach calculates with should come from code, not from Knowledge Base
retrieval: a retrieved table can be partial (missing rows) or misread, and a
calculation from code can be unit-tested. The reference library keeps every
table for citation, but the coach should use these values from a tool.

1. **Diet Quality Score.** Already in `services/common/dqs_table.py` and scored
   by `log_dqs_entry`. Check the ladders against the book (open since Phase 4).
2. **Power training levels 1–7.** % of FTP and % of FTHR bounds, plus typical
   durations, for each level. A function that turns an FTP (from `DailyFitnessLog`
   or Xert TP) into watt ranges for each level.
3. **Daily carbohydrate by training load.** g/kg of body weight for each training
   tier, combined with the latest Withings weight to give grams per day.
4. **Use them together** for anything that predicts training load or builds a
   plan: a workout's target watts from the levels, its expected XSS from
   duration and intensity, and the day's carbohydrate target from the planned load.
5. **Choose the delivery** and write it down:
   - a plain Python module behind a Bedrock action group (the simplest, and the
     same pattern as `log_dqs_entry`), or
   - an **MCP server** exposing `power_levels(ftp)`, `carb_target(weight_kg, load)`
     and `dqs_score(servings)` as tools. This is more work, but it teaches MCP:
     tool schemas, transports, and how an agent discovers and calls tools.
     It can be tested from Claude Code before any Bedrock wiring.

## Coach v2

The full plan, with design notes, is in `documentation/coach-v2-plan.md`. Work
through it one milestone per Claude session.

### Lab modules (runbooks in `documentation/labs/`, Bedrock built by hand)

- [x] **A. Knowledge Bases**: `coach-kb-semantic-v2` with reranking (library, tables, papers)
- [ ] **B. Guardrails**: denied topics (high intensity on suppressed HRV, extreme
      deficits, medical and eating-disorder diagnosis), content and prompt-attack
      filters, PII, contextual grounding, versions, `ApplyGuardrail`
- [ ] **C. Bedrock Agents**: three action groups, KB, guardrail, alias, traces,
      idle-cost check; optional supervisor with collaborators. Backs the chat page.
- [ ] **D. Flows**: inputs → KB retrieval → prompt → guardrail → output. Daily advice v3.
- [ ] **E. Prompt Management**: versioned prompts, model comparison, optimization. Daily advice v2.
- [ ] **F. Evaluation**: ~40 scenarios (including eating behaviour), LLM-as-a-judge, KB RAG evaluation
- [ ] **G. AgentCore**: Strands agent on Runtime (microVM, short idle timeout),
      Gateway exposing the Lambdas as MCP tools, Memory. Second chat backend.
- [ ] **H. (optional) MCP server**: `power_levels`, `carb_target`, `dqs_score`,
      `route_forecast` (see "Reference tables as deterministic data" above)

### Milestones

1. [~] Intervals.icu ingestion (`IntervalsDaily`), then the **form field review**:
       for each Garmin, TrainingPeaks, Xert, body and DQS field, decide remove,
       prefill from Intervals, or keep manual. Plus BP and body temperature
       readings with timestamps (`ManualReadings`).
       - [x] sync Lambda, table, prefills, readings API and form section (deployed)
       - [ ] **Matt:** create the `intervals/api` secret and run the probe (labs/03-intervals.md)
       - [ ] form field review with the probe output
2. [~] Eating-behaviour KB: review the strategy doc, gap analysis, proposed
       open-access sources, `eating_behaviour/` handler in `prepare_kb_docs.py`
       - [x] handler, gap analysis (`documentation/kb-eating-behaviour-review.md`, local only)
       - [ ] **Matt:** fix the flagged claims, download papers, upload new files, sync the 3 data sources
       - [ ] rerun the comparison with the eating-behaviour queries
3. [x] Module B runbook (`documentation/labs/B-guardrails.md`); **Matt** builds the guardrail,
       then set `guardrailId` / `guardrailVersion` in `infra/cdk.json` so advice uses it
4. [~] Analysis page: design discussion, then `GET /analysis/series` and charts
       - [x] `GET /analysis/series` (deployed)
       - [ ] design discussion, then charts
5. [~] Daily advice v1 (Converse), `CoachAdvice` table, advice card, 07:30 schedule (deployed)
       - [x] switched `agent`/`flow` to Haiku 4.5 and `judge` to Sonnet 4.5: the 5.5 models
             return "not available for this account" (no Marketplace agreement yet)
       - [ ] **Matt:** accept the 5.5 agreement (console playground, or
             `create-foundation-model-agreement`), then switch `config/models.json` back
6. [~] Module C runbook, chat Lambda and Coach tab on Bedrock Agents
       - [x] chat Lambda (both backends, 503 until configured) and Coach tab
       - [x] Module C runbook (`documentation/labs/C-agents.md`)
       - [ ] **Matt:** build the agent; then set `agentId` / `agentAliasId` in `infra/cdk.json`
7. [ ] Module G runbook, AgentCore agent code; then set `agentRuntimeArn`
8. [ ] RideWithGPS routes, ride weather (Open-Meteo), calculator MCP server
9. [ ] Modules D, E, F; move daily advice to v2 and v3

### Decisions and parked items

- [ ] Delete the three older Knowledge Bases (`coach-kb-fixed`, `-semantic`,
      `-hierarchical`) once semantic-v2 is confirmed. Don't re-sync them: their
      `library/` source no longer contains the tables.
- [ ] Direct Garmin access (`python-garminconnect`) only for gaps Intervals can't
      fill, such as Body Battery or stress
- Covered through other sources, no work: Rouvy and Zwift (via Strava), Komoot
  (via Garmin or RideWithGPS), TrainingPeaks (replaced by Intervals). Zwift events
  are out of scope.
- Dropped: Google Fit (REST API deprecated; Health Connect is on-device only).
- Parked (2026-10-21): automatic food-diary import. Protein, carbs, fat and fibre
  are typed into the daily log for now. Options when resumed: FatSecret (official
  per-user diary API, `food_entries.get`, food-by-food), MFP via Apple Health or
  Health Connect plus an export app (daily totals), `python-myfitnesspal` (unofficial),
  or logging meals through the coach with a Nutritionix/Edamam lookup.
- Intervals.icu can't return rides it only received from Strava (11 stubs so far);
  connect those apps to Intervals directly if their metrics matter.
