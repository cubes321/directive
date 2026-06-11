from pathlib import Path

from engine.scenario import load_scenario
from engine.state import GameState
from engine.turn import resolve_turn

DATA_DIR = Path(__file__).parent.parent / "data"


def test_scenario_carries_reinforcement_schedule():
    s = load_scenario(DATA_DIR)
    assert s.reinforcements, "expected a soviet reinforcement schedule"
    assert all(r["corps"]["side"] == "soviet" for r in s.reinforcements)


def test_reinforcements_arrive_on_schedule():
    s = load_scenario(DATA_DIR)
    first = min(r["turn"] for r in s.reinforcements)
    s.turn = first
    arriving = [r["corps"]["id"] for r in s.reinforcements if r["turn"] == first]
    resolve_turn(s, {})
    for cid in arriving:
        assert cid in s.corps
        assert not s.corps[cid].is_destroyed


def test_reinforcements_delayed_if_spawn_region_lost():
    s = load_scenario(DATA_DIR)
    first = min(r["turn"] for r in s.reinforcements)
    entry = next(r for r in s.reinforcements if r["turn"] == first)
    s.control[entry["corps"]["location"]] = "axis"  # enemy took the railhead
    s.turn = first
    resolve_turn(s, {})
    assert entry["corps"]["id"] not in s.corps
    assert entry in s.reinforcements  # still pending


def test_reinforcements_survive_save_round_trip():
    s = load_scenario(DATA_DIR)
    restored = GameState.from_dict(s.to_dict())
    assert restored.reinforcements == s.reinforcements
