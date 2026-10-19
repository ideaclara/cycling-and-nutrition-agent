from decimal import Decimal


def test_groups_with_same_timestamp_merge_into_one_session():
    from withings.sync_measures.handler import consolidate

    groups = [
        {
            "date": 1760850000,
            "grpid": 2,
            "model": "Body Scan",
            "measures": [{"type": 1, "value": 78123, "unit": -3}, {"type": 6, "value": 182, "unit": -1}],
        },
        {
            "date": 1760850000,
            "grpid": 1,
            "model": "Body Scan",
            "measures": [{"type": 91, "value": 812, "unit": -2}, {"type": 155, "value": 41, "unit": 0}],
        },
        {"date": 1760936400, "grpid": 3, "measures": [{"type": 91, "value": 790, "unit": -2}]},
    ]
    items = sorted(consolidate("31179536", groups), key=lambda i: i["timestamp"])

    first, second = items
    assert first["PK"] == "USER#31179536"
    assert first["SK"] == "WITHINGS#MEAS#1760850000"
    assert first["weight_kg"] == Decimal("78.123")
    assert first["fat_ratio_pct"] == Decimal("18.2")
    assert first["pulse_wave_velocity_normalized_ms"] == Decimal("8.12")
    assert first["vascular_age_yrs"] == 41
    assert first["measure_group_ids"] == [1, 2]
    assert second["pulse_wave_velocity_raw_ms"] == Decimal("7.90")
    assert second["device_model"] == "unknown"
