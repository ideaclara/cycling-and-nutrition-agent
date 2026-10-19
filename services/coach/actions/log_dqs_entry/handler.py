"""Action group: POST /dqs-entries

The agent turns free text ("porridge with berries and a handful of almonds")
into structured items; this Lambda does the scoring deterministically so the
model never does arithmetic:

    {"date": "2026-10-19",
     "food_items": [{"description": "porridge", "category": "whole_grains", "servings": 1}, ...]}

The servings are added to the day's running totals, the DQS is recomputed, and
each item is appended to `dqs_entries` as an audit trail.
"""

import logging
import os
from datetime import UTC, date, datetime

from common import agent_io, daily_log_repo, dqs_table
from common.dates import today

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _validate_items(items) -> list[dict]:
    if not isinstance(items, list) or not items:
        raise ValueError("food_items must be a non-empty array")
    clean = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"food_items[{i}] must be an object")
        category = item.get("category")
        if category not in dqs_table.LADDERS:
            raise ValueError(f"food_items[{i}].category must be one of: {', '.join(dqs_table.CATEGORIES)}")
        try:
            servings = float(item.get("servings", 0))
        except (TypeError, ValueError):
            raise ValueError(f"food_items[{i}].servings must be a number") from None
        if not 0 < servings <= dqs_table.MAX_SERVINGS_PER_CATEGORY:
            raise ValueError(f"food_items[{i}].servings must be > 0 and <= {dqs_table.MAX_SERVINGS_PER_CATEGORY}")
        clean.append(
            {"description": str(item.get("description", ""))[:200], "category": category, "servings": servings}
        )
    return clean


def handler(event, _context):
    params = agent_io.parameters(event)
    try:
        day = date.fromisoformat(params["date"]).isoformat() if params.get("date") else today().isoformat()
        items = _validate_items(params.get("food_items"))
    except ValueError as err:
        return agent_io.error(event, str(err))

    athlete_id = os.environ["ATHLETE_ID"]
    existing = daily_log_repo.get(athlete_id, day) or {}
    servings = {k: float(v) for k, v in (existing.get("dqs_servings") or {}).items()}
    for item in items:
        servings[item["category"]] = servings.get(item["category"], 0.0) + item["servings"]

    logged_at = datetime.now(UTC).isoformat(timespec="seconds")
    entries = list(existing.get("dqs_entries") or []) + [{**item, "logged_at": logged_at} for item in items]

    before = existing.get("dqs_total", 0)
    updated = daily_log_repo.update(athlete_id, day, {"dqs_servings": servings, "dqs_entries": entries}, set())
    return agent_io.respond(
        event,
        {
            "date": day,
            "items_logged": items,
            "dqs_total": updated["dqs_total"],
            "dqs_change": round(updated["dqs_total"] - before, 2),
            "dqs_breakdown": updated["dqs_breakdown"],
            "servings_today": updated["dqs_servings"],
        },
    )
