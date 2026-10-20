"""Action group: GET /daily-metrics?date=YYYY-MM-DD

Returns one consolidated picture of a day for the coach agent:
- the DailyFitnessLog entry (Garmin, Xert, TrainingPeaks, DQS, waist)
- the Intervals.icu wellness record (HRV, sleep, resting HR, CTL/ATL) and any
  blood pressure or temperature readings
- the most recent Withings scale session on or before that day
- a summary of that day's Strava activities, including time in heart-rate and
  power zones (without the raw payload)
"""

import logging
from datetime import date

from common import agent_io, metrics_repo
from common.dates import today

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, _context):
    params = agent_io.parameters(event)
    try:
        day = date.fromisoformat(params["date"]) if params.get("date") else today()
    except ValueError:
        return agent_io.error(event, "date must be in YYYY-MM-DD format")
    return agent_io.respond(event, metrics_repo.day_snapshot(day))
