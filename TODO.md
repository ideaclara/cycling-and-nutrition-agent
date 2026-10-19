# To-do

## 1. Add time in zones from Strava

Call `GET /activities/{id}/zones` for each activity, so the coach knows the time spent in each heart-rate and power zone. The main activity response doesn't include this.

- Costs one extra read per activity. The app's limit is 200 reads per 15 minutes and 2,000 a day, so a full backfill needs about twice the calls it does now.
- Probably goes in `services/strava/fetch_activity_worker/handler.py`, right after the detail fetch. Handle 429 the same way: hide the message for 15 minutes.
- Store the zones compressed like the main payload, plus flattened per-zone seconds for heart rate and power, so `get_daily_metrics` can return them.
- Existing activities need a one-off backfill of zones only.
- Example response: `documentation/initial-setup-documentation/strava-example-responses/activities_19084710818_zones.json`.
