"""Turn a Strava ``GET /activities/{id}/zones`` response into item attributes.

The response is a list with one entry per zone type that has data, e.g.::

    [{"type": "heartrate", "score": 113.0, "custom_zones": true,
      "distribution_buckets": [{"min": 0, "max": 105, "time": 1130.0}, ...]},
     {"type": "power", "distribution_buckets": [{"min": 0, "max": 50, "time": 275.0}, ...]}]

`max: -1` marks the open-ended top bucket. Rides without a heart-rate strap or
power meter simply have fewer (or no) entries.
"""

import gzip
import json
from decimal import Decimal

PREFIX = {"heartrate": "hr", "power": "power"}


def _number(value):
    return Decimal(str(value)) if isinstance(value, float) else value


def build_attributes(raw: bytes) -> dict:
    """Attributes to merge into the StravaActivities item."""
    zones = json.loads(raw.decode("utf-8")) or []
    attributes: dict = {"zones_gzip": gzip.compress(raw, compresslevel=9)}
    for zone in zones:
        prefix = PREFIX.get(zone.get("type"))
        if not prefix:
            continue
        buckets = zone.get("distribution_buckets") or []
        attributes[f"{prefix}_zone_seconds"] = [_number(b.get("time", 0)) for b in buckets]
        attributes[f"{prefix}_zone_bounds"] = [[b.get("min"), b.get("max")] for b in buckets]
        if zone.get("score") is not None:
            attributes[f"{prefix}_zone_score"] = _number(zone["score"])
    return attributes
