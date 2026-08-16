from pathlib import Path

import pytest

from commanders.briefing import build_briefing
from commanders.divergence import parse_staff_options
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
