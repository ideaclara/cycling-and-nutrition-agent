"""Field definitions and validation for DailyFitnessLog items.

One table row per athlete per day. The manual-entry form, the PUT endpoint and
the agent actions all use these definitions, so ranges are enforced in one place.
"""

from dataclasses import dataclass

from common import dqs_table


@dataclass(frozen=True)
class Field:
    label: str
    group: str
    minimum: float
    maximum: float
    integer: bool = False
    unit: str = ""
    decimals: int | None = None


FIELDS: dict[str, Field] = {
    # Garmin daily metrics
    "training_readiness": Field("Training Readiness", "garmin", 0, 100, integer=True),
    "hrv_overnight_avg_ms": Field("Overnight Avg HRV", "garmin", 0, 300, unit="ms"),
    "resting_hr_bpm": Field("Resting HR", "garmin", 20, 120, integer=True, unit="bpm"),
    "sleep_duration_h": Field("Sleep Duration", "garmin", 0, 24, unit="h", decimals=2),
    "sleep_score": Field("Sleep Score", "garmin", 0, 100, integer=True),
    # Xert
    "xert_tp_w": Field("Threshold Power (TP)", "xert", 0, 1000, unit="W"),
    "xert_hie_kj": Field("High Intensity Energy (HIE)", "xert", 0, 100, unit="kJ", decimals=1),
    "xert_pp_w": Field("Peak Power (PP)", "xert", 0, 3000, unit="W"),
    "xert_ltp_w": Field("Lower Threshold Power (LTP)", "xert", 0, 1000, unit="W"),
    "xert_low_xss": Field("Low XSS", "xert", 0, 1000),
    "xert_high_xss": Field("High XSS", "xert", 0, 1000),
    "xert_peak_xss": Field("Peak XSS", "xert", 0, 1000),
    # TrainingPeaks CTL/ATL/TSB/TSS/IF were removed: Intervals.icu supplies them
    # (IntervalsDaily per day, IntervalsActivities per ride). Old values stay stored.
    # Body
    "waist_cm": Field("Waist", "body", 50, 150, unit="cm", decimals=1),
}

NOTES_MAX_LENGTH = 2000


class ValidationError(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


def _number(field: Field, value) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("must be a number")
    if field.integer and value != int(value):
        raise ValueError("must be a whole number")
    if not field.minimum <= value <= field.maximum:
        raise ValueError(f"must be between {field.minimum:g} and {field.maximum:g}")
    if field.integer:
        return int(value)
    return round(float(value), field.decimals) if field.decimals is not None else float(value)


def validate_update(payload: dict) -> tuple[dict, set[str]]:
    """Validate a partial update.

    Returns ``(values_to_set, names_to_remove)``. A field sent as ``null`` is
    removed. ``dqs_servings`` is validated here; the score is computed by the caller.
    """
    errors: dict[str, str] = {}
    to_set: dict = {}
    to_remove: set[str] = set()

    for name, value in payload.items():
        try:
            if name in FIELDS:
                if value is None:
                    to_remove.add(name)
                else:
                    to_set[name] = _number(FIELDS[name], value)
            elif name == "dqs_servings":
                if value is None:
                    to_remove.add(name)
                    continue
                if not isinstance(value, dict):
                    raise ValueError("must be an object of category -> servings")
                servings = {}
                for cat, n in value.items():
                    if cat not in dqs_table.LADDERS:
                        raise ValueError(f"unknown category '{cat}'")
                    if isinstance(n, bool) or not isinstance(n, (int, float)):
                        raise ValueError(f"servings for '{cat}' must be a number")
                    if not 0 <= n <= dqs_table.MAX_SERVINGS_PER_CATEGORY:
                        raise ValueError(f"servings for '{cat}' must be 0–{dqs_table.MAX_SERVINGS_PER_CATEGORY}")
                    servings[cat] = float(n)
                to_set[name] = servings
            elif name == "notes":
                if value is None:
                    to_remove.add(name)
                elif not isinstance(value, str) or len(value) > NOTES_MAX_LENGTH:
                    raise ValueError(f"must be text of at most {NOTES_MAX_LENGTH} characters")
                else:
                    to_set[name] = value
            else:
                raise ValueError("unknown field")
        except ValueError as err:
            errors[name] = str(err)

    if errors:
        raise ValidationError(errors)
    return to_set, to_remove
