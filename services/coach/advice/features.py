"""Turn the raw data for one day into the facts the advice prompt is given.

Everything numeric is computed here, deterministically, so the model only has
to write: it never does arithmetic on HRV baselines or watt ranges itself.
A manually typed value wins over the Intervals.icu value for the same field.
"""

from datetime import date, timedelta
from statistics import mean

from common import daily_log_repo, intervals_repo, metrics_repo, readings_repo
from common.power_levels import power_levels

BASELINE_DAYS = 7
LOOKBACK_DAYS = 28


def _merged(log: dict | None, intervals: dict | None) -> dict:
    """Daily-log fields, filled from Intervals where the log has no value, plus ctl/atl/tsb."""
    return {
        **intervals_repo.as_daily_fields(intervals),
        **(log or {}),
        **intervals_repo.load_fields(intervals, log),
    }


def _baseline(days: list[dict], field: str) -> float | None:
    values = [d[field] for d in days if isinstance(d.get(field), (int, float))]
    return round(mean(values), 1) if values else None


def _pct(today_value, baseline) -> float | None:
    if today_value is None or not baseline:
        return None
    return round((today_value - baseline) / baseline * 100, 1)


def status(facts: dict) -> str:
    """green / amber / red from deterministic thresholds; unknown without recovery data."""
    flags = set(facts["flags"])
    if flags & {"possible_fever", "high_blood_pressure", "hrv_well_below_baseline"}:
        return "red"
    if flags & {"hrv_below_baseline", "resting_hr_raised", "short_sleep", "deep_fatigue", "fast_ramp"}:
        return "amber"
    if facts["recovery"]["hrv_ms"] is None and facts["load"]["tsb"] is None:
        return "unknown"
    return "green"


def build(athlete_id: str, day: date) -> dict:
    start = day - timedelta(days=LOOKBACK_DAYS)
    logs = {i["date"]: i for i in daily_log_repo.query_range(athlete_id, start.isoformat(), day.isoformat())}
    intervals = {i["date"]: i for i in intervals_repo.query_range(athlete_id, start.isoformat(), day.isoformat())}
    by_day = {
        d.isoformat(): _merged(logs.get(d.isoformat()), intervals.get(d.isoformat()))
        for d in (start + timedelta(days=n) for n in range(LOOKBACK_DAYS + 1))
    }
    today = by_day[day.isoformat()]
    previous = [by_day[(day - timedelta(days=n)).isoformat()] for n in range(1, BASELINE_DAYS + 1)]
    week_ago = by_day[(day - timedelta(days=7)).isoformat()]

    hrv, rhr = today.get("hrv_overnight_avg_ms"), today.get("resting_hr_bpm")
    hrv_base, rhr_base = _baseline(previous, "hrv_overnight_avg_ms"), _baseline(previous, "resting_hr_bpm")
    ctl, atl = today.get("ctl"), today.get("atl")
    tsb = today.get("tsb", round(ctl - atl, 1) if ctl is not None and atl is not None else None)
    ramp = round(ctl - week_ago["ctl"], 1) if ctl is not None and week_ago.get("ctl") is not None else None

    yesterday = day - timedelta(days=1)
    rides = metrics_repo.activities_on(yesterday)
    recent_rides = intervals_repo.activities_range(athlete_id, start.isoformat(), day.isoformat())
    # Threshold power: the latest Xert TP typed into the log, else the FTP Intervals used on the latest ride.
    ftp = next(
        (by_day[d]["xert_tp_w"] for d in sorted(by_day, reverse=True) if by_day[d].get("xert_tp_w")),
        next((r["icu_ftp"] for r in reversed(recent_rides) if r.get("icu_ftp")), None),
    )
    tss = [
        r["icu_training_load"]
        for r in recent_rides
        if r["start_date_local"][:10] == yesterday.isoformat() and r.get("icu_training_load") is not None
    ]
    readings = readings_repo.query(athlete_id, day, day)
    bp = next((r for r in reversed(readings) if r["type"] == "BP"), None)
    temp = next((r for r in reversed(readings) if r["type"] == "TEMP"), None)
    withings = metrics_repo.latest_withings(day)

    facts = {
        "date": day.isoformat(),
        "recovery": {
            "hrv_ms": hrv,
            "hrv_7d_baseline_ms": hrv_base,
            "hrv_vs_baseline_pct": _pct(hrv, hrv_base),
            "resting_hr_bpm": rhr,
            "resting_hr_7d_baseline_bpm": rhr_base,
            "sleep_h": today.get("sleep_duration_h"),
            "sleep_score": today.get("sleep_score"),
            "readiness": today.get("training_readiness"),
        },
        "load": {"ctl": ctl, "atl": atl, "tsb": tsb, "ctl_change_7d": ramp},
        "yesterday": {
            "rides": len(rides),
            "moving_time_h": round(sum(r.get("moving_time") or 0 for r in rides) / 3600, 2),
            "kilojoules": sum(r.get("kilojoules") or 0 for r in rides),
            "tss": sum(tss) if tss else None,
            "dqs_total": (logs.get(yesterday.isoformat()) or {}).get("dqs_total"),
            **{
                field: (logs.get(yesterday.isoformat()) or {}).get(field)
                for field in ("protein_g", "carbs_g", "fat_g", "fibre_g")
            },
        },
        "threshold_power_w": ftp,
        "power_levels": power_levels(ftp) if ftp else None,
        "body": {"weight_kg": (withings or {}).get("weight_kg"), "waist_cm": today.get("waist_cm")},
        "readings_today": {
            "blood_pressure": {k: bp[k] for k in ("local_time", "systolic_mmhg", "diastolic_mmhg", "pulse_bpm")}
            if bp
            else None,
            "temperature_c": temp["temp_c"] if temp else None,
        },
    }

    flags = []
    pct = facts["recovery"]["hrv_vs_baseline_pct"]
    if pct is not None and pct <= -25:
        flags.append("hrv_well_below_baseline")
    elif pct is not None and pct <= -15:
        flags.append("hrv_below_baseline")
    if rhr is not None and rhr_base is not None and rhr - rhr_base >= 5:
        flags.append("resting_hr_raised")
    if facts["recovery"]["sleep_h"] is not None and facts["recovery"]["sleep_h"] < 6:
        flags.append("short_sleep")
    if tsb is not None and tsb < -25:
        flags.append("deep_fatigue")
    if ramp is not None and ramp > 7:
        flags.append("fast_ramp")
    if temp and temp["temp_c"] >= 37.8:
        flags.append("possible_fever")
    if bp and (bp["systolic_mmhg"] >= 160 or bp["diastolic_mmhg"] >= 100):
        flags.append("high_blood_pressure")
    facts["flags"] = flags
    facts["missing"] = [
        name
        for name, value in (
            ("HRV", hrv),
            ("sleep", facts["recovery"]["sleep_h"]),
            ("fitness/fatigue (CTL/ATL)", ctl),
            ("threshold power", ftp),
        )
        if value is None
    ]
    facts["status"] = status(facts)
    return facts
