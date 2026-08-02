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


def _spill_state(depot_control="soviet", spur_control="soviet"):
    # depot -- spur -- far, plus an isolated island with no link.
    # A reinforcement is scheduled into depot on turn 2.
    return GameState.from_dict({
        "map": {
            "regions": [{"id": r, "name": r.title(), "terrain": "clear"}
                        for r in ["depot", "spur", "far", "island"]],
            "edges": [
                {"between": ["depot", "spur"], "road": "highway", "rail": True},
                {"between": ["spur", "far"], "road": "highway", "rail": True},
            ],
        },
        "corps": [],
        "control": {"depot": depot_control, "spur": spur_control,
                    "far": "soviet", "island": "axis"},
        "supply_sources": {"soviet": ["far"], "axis": ["island"]},
        "reinforcements": [{"turn": 2, "corps": {
            "id": "sov_new", "name": "New Army", "side": "soviet",
            "kind": "infantry", "location": "depot", "commander": "zhukov",
        }}],
        "turn": 2, "seed": 1,
    })


def test_a_blocked_reinforcement_spills_to_the_nearest_friendly_region():
    # An army that cannot detrain at its depot detrains short of it. It must not
    # sit in a siding for the rest of the war: Siberian Group Lukin - the single
    # largest Soviet counterweight - was withheld for an entire campaign because
    # Moscow happened to be full on the turn it was due.
    s = _spill_state()
    for i in range(STACKING_LIMIT):           # depot is friendly but full
        s.corps[f"filler{i}"] = Corps(
            id=f"filler{i}", name=f"Filler {i}", side="soviet", kind="infantry",
            location="depot", commander="zhukov",
        )
    report = resolve_turn(s, {})
    assert "sov_new" in s.corps
    assert s.corps["sov_new"].location == "spur"      # one hop back down the line
    assert not s.reinforcements                        # and no longer pending
    assert {"corps": "sov_new", "to": "spur", "arrived": True,
            "diverted_from": "depot"} in report.movements


def test_a_reinforcement_spills_when_the_enemy_holds_its_depot():
    s = _spill_state(depot_control="axis")
    resolve_turn(s, {})
    assert s.corps["sov_new"].location == "spur"


def test_a_reinforcement_with_nowhere_to_spill_stays_pending_and_is_reported():
    # Every reachable region is enemy-held, so there is genuinely nowhere to
    # detrain. Only then may it wait - and it must still say so.
    s = _spill_state(depot_control="axis", spur_control="axis")
    s.control["far"] = "axis"
    report = resolve_turn(s, {})
    assert "sov_new" not in s.corps
    assert len(s.reinforcements) == 1                  # still pending
    assert {"corps": "sov_new", "to": "depot", "delayed": True} in report.movements


def test_reinforcements_survive_save_round_trip():
    s = load_scenario(DATA_DIR)
    restored = GameState.from_dict(s.to_dict())
    assert restored.reinforcements == s.reinforcements
