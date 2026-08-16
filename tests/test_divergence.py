from pathlib import Path

import pytest

from commanders.briefing import build_briefing
from commanders.divergence import bucket_for, parse_staff_options
from engine.scenario import load_scenario

DATA_DIR = Path(__file__).parent.parent / "data"


def test_parses_each_corps_options_in_order():
    state = load_scenario(DATA_DIR)
    options = parse_staff_options(build_briefing(state, "guderian"))
    assert options["xxiv_pz"] == [
        ("attack", "baranovichi"),
        ("advance", "pripyat"),
        ("defend", None),
    ]


def test_parses_every_briefed_corps():
    state = load_scenario(DATA_DIR)
    options = parse_staff_options(build_briefing(state, "guderian"))
    assert set(options) == {"xxiv_pz", "xlvi_pz", "xlvii_pz"}


def test_a_worn_corps_is_offered_reserve_not_hold():
    # _staff_options swaps "hold current position" for "hold in reserve" below
    # 70 supply or organization; both must map to a posture.
    state = load_scenario(DATA_DIR)
    corps = state.corps_for("guderian")[0]
    corps.supply = 50
    options = parse_staff_options(build_briefing(state, "guderian"))
    assert options[corps.id][-1] == ("reserve", None)


def test_an_unrecognized_option_line_raises():
    # Silence here would be the worst failure mode: unparsed options make every
    # order look off-menu, i.e. personality appears to rise as the metric blinds.
    briefing = "STAFF OPTIONS:\nFor X Corps [x_ak]:\n  * dig in and pray\n"
    with pytest.raises(ValueError, match="dig in and pray"):
        parse_staff_options(briefing)


def test_a_briefing_without_staff_options_yields_nothing():
    assert parse_staff_options("SITUATION BRIEFING - no options here") == {}


ATTACK = ("attack", "minsk")
ADVANCE = ("advance", "slonim")
HOLD = ("defend", None)


def _order(posture, objective=None, corps_id="xxiv_pz"):
    return {"corps_id": corps_id, "posture": posture, "objective": objective}


def test_the_staffs_lead_suggestion_is_first():
    assert bucket_for(_order("attack", "minsk"), [ATTACK, ADVANCE, HOLD]) == "first"


def test_a_later_move_suggestion_is_middle():
    assert bucket_for(_order("advance", "slonim"), [ATTACK, ADVANCE, HOLD]) == "middle"


def test_the_trailing_hold_option_is_hold():
    assert bucket_for(_order("defend"), [ATTACK, ADVANCE, HOLD]) == "hold"


def test_index_one_is_hold_when_the_list_is_only_two_long():
    # A quiet sector offers one move and then the hold. Raw rank would call
    # this "middle" and read as independence; it is the opposite.
    assert bucket_for(_order("defend"), [ATTACK, HOLD]) == "hold"


def test_the_only_option_being_hold_scores_as_hold_not_first():
    # Starving infantry in the mud can reach nothing at all.
    assert bucket_for(_order("defend"), [HOLD]) == "hold"


def test_an_objective_the_staff_never_raised_is_off_menu():
    assert bucket_for(_order("advance", "slutsk"), [ATTACK, ADVANCE, HOLD]) == "off-menu"


def test_the_right_region_with_the_wrong_posture_is_off_menu():
    assert bucket_for(_order("advance", "minsk"), [ATTACK, ADVANCE, HOLD]) == "off-menu"


def test_a_missing_objective_key_is_treated_as_none():
    assert bucket_for({"corps_id": "x", "posture": "defend"}, [ATTACK, HOLD]) == "hold"
