"""Field definitions and validation for ManualReadings items.

Readings are timestamped (several a day are allowed), unlike the one-row-per-day
DailyFitnessLog. The form reads these definitions from GET /readings/schema.
"""

from datetime import UTC, datetime, timedelta

from common.daily_log_schema import Field, ValidationError, _number
from common.dates import local_tz

TYPES: dict[str, dict[str, Field]] = {
    "BP": {
        "systolic_mmhg": Field("Systolic", "bp", 70, 250, integer=True, unit="mmHg"),
        "diastolic_mmhg": Field("Diastolic", "bp", 40, 150, integer=True, unit="mmHg"),
        "pulse_bpm": Field("Pulse", "bp", 30, 220, integer=True, unit="bpm"),
    },
    "TEMP": {
        "temp_c": Field("Body temperature", "temp", 34, 42, unit="°C", decimals=1),
    },
}

# Allow a little clock skew between the browser and Lambda.
FUTURE_TOLERANCE = timedelta(minutes=5)


def parse_local_time(value) -> datetime:
    """Parse "YYYY-MM-DDTHH:MM[:SS]" (athlete's local time) or an ISO time with an offset, as UTC."""
    if not isinstance(value, str) or not value:
        raise ValueError("must be a date and time (YYYY-MM-DDTHH:MM)")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError("must be a date and time (YYYY-MM-DDTHH:MM)") from err
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_tz())
    return parsed.astimezone(UTC).replace(microsecond=0)


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_reading(payload: dict, now: datetime | None = None) -> tuple[str, datetime, dict]:
    """Validate a new reading. Returns ``(type, measured_at_utc, values)``.

    Every field of the type is required: a blood pressure reading without a
    pulse, or a temperature without a value, is rejected.
    """
    errors: dict[str, str] = {}
    kind = payload.get("type")
    if kind not in TYPES:
        raise ValidationError({"type": f"must be one of {', '.join(TYPES)}"})
    fields = TYPES[kind]

    measured_at = None
    try:
        measured_at = parse_local_time(payload.get("measured_at"))
        if measured_at > (now or datetime.now(UTC)) + FUTURE_TOLERANCE:
            raise ValueError("must not be in the future")
    except ValueError as err:
        errors["measured_at"] = str(err)

    values: dict = {}
    for name, field in fields.items():
        if payload.get(name) is None:
            errors[name] = "is required"
            continue
        try:
            values[name] = _number(field, payload[name])
        except ValueError as err:
            errors[name] = str(err)

    for name in payload.keys() - fields.keys() - {"type", "measured_at"}:
        errors[name] = "unknown field"

    if (
        kind == "BP"
        and {"systolic_mmhg", "diastolic_mmhg"} <= values.keys()
        and values["diastolic_mmhg"] >= values["systolic_mmhg"]
    ):
        errors["diastolic_mmhg"] = "must be lower than systolic"

    if errors:
        raise ValidationError(errors)
    return kind, measured_at, values
