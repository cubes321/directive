from engine.state import GameState
from engine.victory import FINAL_TURN, check_victory


def make_state(turn=1, moscow="soviet", axis_vp=5):
    # minimal synthetic state: moscow + filler VP regions
    regions = [
        {"id": "moscow", "name": "Moscow", "terrain": "urban", "victory_points": 25},
        {"id": "a", "name": "A", "terrain": "clear", "victory_points": axis_vp},
        {"id": "b", "name": "B", "terrain": "clear"},
    ]
    data = {
        "map": {"regions": regions, "edges": [{"between": ["moscow", "a"], "road": "minor", "rail": False},
                                              {"between": ["a", "b"], "road": "minor", "rail": False}]},
        "corps": [
            {"id": "ax1", "name": "Ax1", "side": "axis", "kind": "panzer",
             "location": "a", "commander": "guderian"},
            {"id": "sv1", "name": "Sv1", "side": "soviet", "kind": "infantry",
             "location": "moscow", "commander": "zhukov"},
        ],
        "control": {"moscow": moscow, "a": "axis", "b": "soviet"},
        "supply_sources": {"axis": ["a"], "soviet": ["moscow"]},
        "turn": turn,
        "seed": 1,
    }
    return GameState.from_dict(data)


def test_no_verdict_mid_campaign():
    assert check_victory(make_state(turn=5)) is None


def test_taking_moscow_is_a_decisive_axis_victory_immediately():
    verdict = check_victory(make_state(turn=9, moscow="axis"))
    assert verdict["winner"] == "axis"
    assert verdict["kind"] == "decisive"


def test_campaign_end_without_moscow_counts_objectives():
    # axis holds 20 of 45 available VP at the final turn: marginal axis win
    verdict = check_victory(make_state(turn=FINAL_TURN + 1, axis_vp=20))
    assert verdict["winner"] == "axis"
    assert verdict["kind"] == "marginal"


def test_campaign_end_with_meagre_gains_is_a_soviet_victory():
    verdict = check_victory(make_state(turn=FINAL_TURN + 1, axis_vp=5))
    assert verdict["winner"] == "soviet"


def test_axis_annihilation_is_a_soviet_decisive_victory():
    state = make_state(turn=8)
    state.corps["ax1"].take_losses(strength=100)
    verdict = check_victory(state)
    assert verdict["winner"] == "soviet"
    assert verdict["kind"] == "decisive"
