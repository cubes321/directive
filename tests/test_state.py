from pathlib import Path

from engine.scenario import load_scenario
from engine.state import GameState

DATA_DIR = Path(__file__).parent.parent / "data"


def minimal_state_data():
    return {
        "map": {
            "regions": [
                {"id": "brest", "name": "Brest", "terrain": "clear"},
                {"id": "minsk", "name": "Minsk", "terrain": "urban", "victory_points": 5},
            ],
            "edges": [{"between": ["brest", "minsk"], "road": "highway", "rail": True}],
        },
        "corps": [
            {"id": "xxiv_pz", "name": "XXIV Panzer", "side": "axis", "kind": "panzer",
             "location": "brest", "commander": "guderian"},
            {"id": "sov_13a", "name": "13th Army", "side": "soviet", "kind": "infantry",
             "location": "minsk", "commander": "pavlov"},
        ],
        "control": {"brest": "axis", "minsk": "soviet"},
        "supply_sources": {"axis": ["brest"], "soviet": ["minsk"]},
        "turn": 1,
        "seed": 42,
    }


def test_state_loads_from_dict():
    s = GameState.from_dict(minimal_state_data())
    assert s.turn == 1
    assert s.corps["xxiv_pz"].kind == "panzer"
    assert s.control["minsk"] == "soviet"
    assert s.game_map.regions["minsk"].victory_points == 5


def test_state_round_trips():
    s = GameState.from_dict(minimal_state_data())
    s.corps["xxiv_pz"].take_losses(strength=10)
    s.directives["guderian"] = "Take Minsk."
    assert GameState.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_turn_date_is_weekly_from_barbarossa_start():
    s = GameState.from_dict(minimal_state_data())
    assert s.date.isoformat() == "1941-06-22"
    s.turn = 3
    assert s.date.isoformat() == "1941-07-06"


def test_corps_for_commander():
    s = GameState.from_dict(minimal_state_data())
    assert [c.id for c in s.corps_for("guderian")] == ["xxiv_pz"]


def test_corps_at_region():
    s = GameState.from_dict(minimal_state_data())
    assert [c.id for c in s.corps_at("minsk")] == ["sov_13a"]


def test_last_orders_and_intel_round_trip_through_a_save():
    state = load_scenario(DATA_DIR)
    state.last_orders = {
        "guderian": {
            "commander": "guderian",
            "orders": [{"corps_id": "xxiv_pz", "posture": "attack", "objective": "minsk"}],
            "dispatch": "Forward.",
            "reasoning": "",
        }
    }
    state.intel = {"soviet": {"commander": "guderian", "name": "G", "orders": []}}
    restored = GameState.from_dict(state.to_dict())
    assert restored.last_orders["guderian"]["orders"][0]["objective"] == "minsk"
    assert restored.intel["soviet"]["commander"] == "guderian"


def test_a_save_predating_signals_intelligence_still_loads():
    state = load_scenario(DATA_DIR)
    payload = state.to_dict()
    del payload["last_orders"]
    del payload["intel"]
    restored = GameState.from_dict(payload)
    assert restored.last_orders == {}
    assert restored.intel == {}
