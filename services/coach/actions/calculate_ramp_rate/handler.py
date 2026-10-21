"""Action group: GET /ramp-rate?days=N&end_date=YYYY-MM-DD

Ramp rate is the change in chronic training load (CTL) expressed per week:

    ramp_per_week = (CTL_end - CTL_start) * 7 / days

CTL/ATL/TSB come from IntervalsDaily, falling back to the TrainingPeaks values
once typed into DailyFitnessLog. Missing days are allowed: the nearest value on
or before each end of the window is used.
"""

import logging
import os
from datetime import date, timedelta

from common import agent_io, daily_log_repo, intervals_repo
from common.dates import today

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEFAULT_DAYS = 7
MAX_DAYS = 90
# Look this far before the window start for a CTL value if that day wasn't logged.
LOOKBACK_DAYS = 7

# Commonly cited guidance: ~3–5 CTL/week is sustainable; >5–8 needs care; >8 is aggressive.
THRESHOLDS = ((8, "aggressive"), (5, "high"), (0, "sustainable"))


def classify(ramp: float) -> str:
    if ramp < 0:
        return "detraining"
    for limit, label in THRESHOLDS:
        if ramp > limit:
            return label
    return "maintaining"


def _nearest_on_or_before(rows: list[dict], day: str) -> dict | None:
    eligible = [r for r in rows if r["date"] <= day and r.get("ctl") is not None]
    return eligible[-1] if eligible else None


def compute(rows: list[dict], start: date, end: date) -> dict:
    """Pure calculation over {date, ctl, atl, tsb} rows sorted by date ascending."""
    first = _nearest_on_or_before(rows, start.isoformat())
    last = _nearest_on_or_before(rows, end.isoformat())
    if not first or not last or first["date"] >= last["date"]:
        return {"error": "Not enough CTL data in this window: Intervals.icu needs at least two days."}

    span = (date.fromisoformat(last["date"]) - date.fromisoformat(first["date"])).days
    ramp = (last["ctl"] - first["ctl"]) * 7 / span
    trend = [
        {k: r[k] for k in ("date", "ctl", "atl", "tsb") if k in r}
        for r in rows
        if start.isoformat() <= r["date"] <= end.isoformat() and r.get("ctl") is not None
    ]
    return {
        "window": {"start": first["date"], "end": last["date"], "days": span},
        "ctl_start": first["ctl"],
        "ctl_end": last["ctl"],
        "ramp_per_week": round(ramp, 2),
        "assessment": classify(ramp),
        "latest_atl": last.get("atl"),
        "latest_tsb": last.get("tsb"),
        "trend": trend,
    }


def handler(event, _context):
    params = agent_io.parameters(event)
    try:
        days = int(params.get("days") or DEFAULT_DAYS)
        end = date.fromisoformat(params["end_date"]) if params.get("end_date") else today()
    except (TypeError, ValueError):
        return agent_io.error(event, "days must be an integer and end_date must be YYYY-MM-DD")
    if not 1 <= days <= MAX_DAYS:
        return agent_io.error(event, f"days must be between 1 and {MAX_DAYS}")

    start = end - timedelta(days=days)
    athlete, lo, hi = os.environ["ATHLETE_ID"], (start - timedelta(days=LOOKBACK_DAYS)).isoformat(), end.isoformat()
    logs = {r["date"]: r for r in daily_log_repo.query_range(athlete, lo, hi)}
    intervals = {r["date"]: r for r in intervals_repo.query_range(athlete, lo, hi)}
    rows = [
        {"date": d, **intervals_repo.load_fields(intervals.get(d), logs.get(d))}
        for d in sorted(logs.keys() | intervals.keys())
    ]
    result = compute(rows, start, end)
    return agent_io.respond(event, result, 200 if "error" not in result else 404)
