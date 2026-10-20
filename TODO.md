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
