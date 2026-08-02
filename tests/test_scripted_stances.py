"""The tuning stances. Plain "advance" never lunges and rarely halts, which
makes it a misleading instrument: a rules change looked like a marginal axis
win on an advance trace and was a rout in live play."""

from commanders.scripted import scripted_orders
from engine.state import GameState


def _corridor(supply=100):
    # a -- b -- c -- d, all highway (cost 2). A panzer corps has 6 MP, so it can
    # reach d in a single bound. All friendly ground, goal is d.
    return GameState.from_dict({
        "map": {
            "regions": [{"id": r, "name": r.title(), "terrain": "clear"}
                        for r in ["a", "b", "c", "d"]],
            "edges": [
                {"between": ["a", "b"], "road": "highway", "rail": True},
                {"between": ["b", "c"], "road": "highway", "rail": True},
                {"between": ["c", "d"], "road": "highway", "rail": True},
            ],
        },
        "corps": [{"id": "p1", "name": "P1", "side": "axis", "kind": "panzer",
                   "location": "a", "commander": "guderian", "supply": supply}],
        "control": {"a": "axis", "b": "axis", "c": "axis", "d": "axis"},
        "supply_sources": {"axis": ["a"]},
        "turn": 1, "seed": 1,
    })


def _objective(state, stance):
    return scripted_orders(state, "guderian", stance=stance, goal="d").orders[0].objective


def test_advance_steps_one_region_at_a_time():
    # the historical default, unchanged - existing traces stay comparable
    assert _objective(_corridor(), "advance") == "b"


def test_blitz_takes_the_deepest_bound_it_can_reach():
    # 0 of 118 scripted moves were multi-hop; 31 of 108 live ones were. This is
    # the stance that exercises the lunge penalty at all.
    assert _objective(_corridor(), "blitz") == "d"


def test_methodical_also_steps_but_halts_far_sooner():
    assert _objective(_corridor(), "methodical") == "b"


def test_methodical_rests_on_strained_supply_where_advance_presses_on():
    strained = 50   # under methodical's threshold, over advance's
    assert _objective(_corridor(supply=strained), "advance") == "b"
    orders = scripted_orders(_corridor(supply=strained), "guderian",
                             stance="methodical", goal="d").orders[0]
    assert orders.posture == "reserve"


def test_blitz_presses_on_when_advance_would_stop_to_resupply():
    starved = 10    # under advance's rest threshold, blitz has none
    advance = scripted_orders(_corridor(supply=starved), "guderian",
                              stance="advance", goal="d").orders[0]
    assert advance.posture == "reserve"
    blitz = scripted_orders(_corridor(supply=starved), "guderian",
                            stance="blitz", goal="d").orders[0]
    assert blitz.posture == "advance"


def test_an_unknown_stance_still_just_defends():
    assert scripted_orders(_corridor(), "guderian", stance="defend",
                           goal="d").orders[0].posture == "defend"
