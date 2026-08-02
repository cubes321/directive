from pathlib import Path

from engine.scenario import load_scenario
from engine.state import GameState
from engine.turn import STACKING_LIMIT, resolve_turn
from engine.units import Corps

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
    report = resolve_turn(s, {})
    assert entry["corps"]["id"] not in s.corps
    assert entry in s.reinforcements  # still pending
    # A blocked arrival must never be silent: it has to show up in the report
    # even though nothing actually happened on the map.
    assert {
        "corps": entry["corps"]["id"],
        "to": entry["corps"]["location"],
        "delayed": True,
    } in report.movements


def test_reinforcements_delayed_if_spawn_region_at_stacking_limit():
    # sov_sib1 (task 5's real bug): the arrival region is friendly-held but
    # already full, so the reinforcement is blocked exactly as if the enemy
    # held it - and must be reported the same way, not silently dropped.
    s = load_scenario(DATA_DIR)
    first = min(r["turn"] for r in s.reinforcements)
    entry = next(r for r in s.reinforcements if r["turn"] == first)
    location = entry["corps"]["location"]
    side = entry["corps"]["side"]
    for i in range(STACKING_LIMIT):
        filler = Corps(
            id=f"filler{i}", name=f"Filler {i}", side=side, kind="infantry",
            location=location, commander="c",
        )
        s.corps[filler.id] = filler
    s.turn = first
    report = resolve_turn(s, {})
    assert entry["corps"]["id"] not in s.corps
    assert entry in s.reinforcements  # still pending
    assert {
        "corps": entry["corps"]["id"],
        "to": location,
        "delayed": True,
    } in report.movements


def test_reinforcements_survive_save_round_trip():
    s = load_scenario(DATA_DIR)
    restored = GameState.from_dict(s.to_dict())
    assert restored.reinforcements == s.reinforcements
