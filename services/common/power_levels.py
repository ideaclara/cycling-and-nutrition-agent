"""Power-based training levels as watt ranges from a threshold power.

Percentages of FTP follow the classic seven-level model (Allen & Coggan,
*Training and Racing with a Power Meter*, Table 3.1). Served from code rather
than retrieval so targets are exact and testable (see TODO.md).
"""

# (level, name, low % of FTP, high % of FTP); None = open-ended
LEVELS: list[tuple[int, str, int | None, int | None]] = [
    (1, "Active Recovery", None, 55),
    (2, "Endurance", 56, 75),
    (3, "Tempo", 76, 90),
    (4, "Lactate Threshold", 91, 105),
    (5, "VO2max", 106, 120),
    (6, "Anaerobic Capacity", 121, 150),
    (7, "Neuromuscular Power", None, None),
]


def power_levels(ftp_w: float) -> list[dict]:
    """Each level with its watt range for this FTP (low/high omitted when open-ended)."""
    if ftp_w <= 0:
        raise ValueError("FTP must be positive")
    levels = []
    for level, name, low, high in LEVELS:
        entry: dict = {"level": level, "name": name}
        if low is not None:
            entry["low_w"] = round(ftp_w * low / 100)
        if high is not None:
            entry["high_w"] = round(ftp_w * high / 100)
        if level == 6:
            entry["note"] = "above 150% of FTP is Level 7"
        levels.append(entry)
    return levels
