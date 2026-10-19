"""Diet Quality Score (DQS) scoring, after Matt Fitzgerald's *Racing Weight*.

Each food category has a points ladder: the 1st serving of the day scores the
first value, the 2nd serving the second value, and so on. Servings past the end
of the ladder keep scoring the last value. Fractional servings score that
fraction of the next slot's value.

VERIFY these ladders against your own copy of the book before relying on them;
they are transcribed from memory of the published table and are the single
place to correct.
"""

from math import floor

HIGH_QUALITY = {
    "fruit": [2, 2, 2, 1, 0, 0],
    "vegetables": [2, 2, 2, 1, 0, 0],
    "lean_meats_fish": [2, 2, 1, 0, 0, -1],
    "nuts_seeds": [2, 2, 1, 0, 0, -1],
    "whole_grains": [2, 2, 1, 0, 0, -1],
    "dairy": [2, 1, 1, 0, -1, -2],
}

LOW_QUALITY = {
    "refined_grains": [-1, -1, -2, -2, -2, -2],
    "sweets": [-2, -2, -2, -2, -2, -2],
    "fried_foods": [-2, -2, -2, -2, -2, -2],
    "fatty_proteins": [-1, -1, -2, -2, -2, -2],
}

LADDERS = {**HIGH_QUALITY, **LOW_QUALITY}
CATEGORIES = tuple(LADDERS)
MAX_SERVINGS_PER_CATEGORY = 20


def _slot(ladder: list[int], index: int) -> int:
    return ladder[min(index, len(ladder) - 1)]


def category_points(category: str, servings: float) -> float:
    if category not in LADDERS:
        raise ValueError(f"Unknown DQS category '{category}'. Expected one of: {', '.join(CATEGORIES)}")
    if servings < 0:
        raise ValueError("Servings cannot be negative")
    ladder = LADDERS[category]
    whole = floor(servings)
    points = sum(_slot(ladder, i) for i in range(whole))
    fraction = servings - whole
    if fraction:
        points += fraction * _slot(ladder, whole)
    return round(points, 2)


def score(servings: dict[str, float]) -> dict:
    """Score a day's servings. Returns the total and a per-category breakdown."""
    breakdown = {cat: category_points(cat, float(n)) for cat, n in servings.items() if float(n) > 0}
    return {"total": round(sum(breakdown.values()), 2), "by_category": breakdown}
