# To-do

## 1. Add time in zones from Strava

Call `GET /activities/{id}/zones` for each activity, so the coach knows the time spent in each heart-rate and power zone. The main activity response doesn't include this.

- Costs one extra read per activity. The app's limit is 200 reads per 15 minutes and 2,000 a day, so a full backfill needs about twice the calls it does now.
- Probably goes in `services/strava/fetch_activity_worker/handler.py`, right after the detail fetch. Handle 429 the same way: hide the message for 15 minutes.
- Store the zones compressed like the main payload, plus flattened per-zone seconds for heart rate and power, so `get_daily_metrics` can return them.
- Existing activities need a one-off backfill of zones only.
- Example response: `documentation/initial-setup-documentation/strava-example-responses/activities_19084710818_zones.json`.

## 2. Keep personal Strava data out of the public repo

The repo is public, and the sample responses include GPS data: `map.polyline`, `start_latlng`/`end_latlng`, and `latlng` inside efforts and laps.

- Add `.gitignore` rules for `documentation/initial-setup-documentation/strava-example-responses/*.json` (and any other raw API dumps). `scripts/strava_probe.sh` writes its output there.
- `.gitignore` doesn't affect files that are already tracked. Run `git rm --cached` on the samples already committed (e.g. `activities_19084710818.json`).
- The committed files stay in git history either way. Decide whether to rewrite history (e.g. `git filter-repo`) or accept that.
- If redacted samples are still useful for docs and tests, commit copies with the location fields removed. `services/tests/test_strava.py` reads `activities_19084710818.json`, so give the tests a redacted fixture under `services/tests/`.
