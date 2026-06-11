from engine.fog import visible_enemy_contacts
from engine.state import GameState


def state_data():
    # a -- b -- c -- d in a line; axis at a, soviets at c and d
    return {
        "map": {
            "regions": [
                {"id": r, "name": r.upper(), "terrain": "clear"} for r in ["a", "b", "c", "d"]
            ],
            "edges": [
                {"between": ["a", "b"], "road": "highway", "rail": False},
                {"between": ["b", "c"], "road": "highway", "rail": False},
                {"between": ["c", "d"], "road": "highway", "rail": False},
            ],
        },
        "corps": [
            {"id": "ax1", "name": "Ax1", "side": "axis", "kind": "panzer",
             "location": "b", "commander": "guderian", "strength": 90},
            {"id": "sv1", "name": "Sv1", "side": "soviet", "kind": "infantry",
             "location": "c", "commander": "pavlov", "strength": 62},
            {"id": "sv2", "name": "Sv2", "side": "soviet", "kind": "infantry",
             "location": "d", "commander": "pavlov", "strength": 80},
        ],
        "control": {"a": "axis", "b": "axis", "c": "soviet", "d": "soviet"},
        "supply_sources": {"axis": ["a"], "soviet": ["d"]},
        "turn": 1,
        "seed": 1,
    }


def test_enemy_adjacent_to_own_corps_is_spotted():
    s = GameState.from_dict(state_data())
    contacts = visible_enemy_contacts(s, "axis")
    assert "c" in contacts
    assert contacts["c"][0]["kind"] == "infantry"


def test_enemy_beyond_recon_range_is_invisible():
    s = GameState.from_dict(state_data())
    contacts = visible_enemy_contacts(s, "axis")
    assert "d" not in contacts


def test_spotted_strength_is_an_estimate_not_exact():
    s = GameState.from_dict(state_data())
    contacts = visible_enemy_contacts(s, "axis")
    estimate = contacts["c"][0]["estimated_strength"]
    assert estimate != 62  # rounded band, not the true value
    assert estimate % 25 == 0


def test_fog_is_symmetric_for_the_other_side():
    s = GameState.from_dict(state_data())
    contacts = visible_enemy_contacts(s, "soviet")
    assert "b" in contacts  # axis corps at b adjacent to soviet corps at c
