import pytest

from common import dqs_table


def test_first_servings_of_vegetables_score_ladder():
    assert dqs_table.category_points("vegetables", 3) == 6
    assert dqs_table.category_points("vegetables", 4) == 7
    assert dqs_table.category_points("vegetables", 6) == 7


def test_servings_past_ladder_repeat_last_value():
    # dairy ladder ends at -2; 8 servings = 2+1+1+0-1-2-2-2
    assert dqs_table.category_points("dairy", 8) == -3


def test_fractional_serving_scores_fraction_of_next_slot():
    assert dqs_table.category_points("fruit", 1.5) == 3  # 2 + 0.5*2
    assert dqs_table.category_points("sweets", 0.5) == -1


def test_score_totals_and_breakdown():
    result = dqs_table.score({"fruit": 2, "sweets": 1, "whole_grains": 0})
    assert result == {"total": 2, "by_category": {"fruit": 4, "sweets": -2}}


def test_unknown_category_rejected():
    with pytest.raises(ValueError, match="Unknown DQS category"):
        dqs_table.category_points("pizza", 1)
