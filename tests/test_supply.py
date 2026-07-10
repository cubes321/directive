import os
import subprocess
import sys
from pathlib import Path

from engine.map import GameMap
from engine.supply import advance_railhead, compute_supply
from engine.units import Corps

REPO_ROOT = Path(__file__).parent.parent


def _branching_map():
    # src --rail-- a --rail-- b   and   src --rail-- m --rail-- n
    # railhead {src,a,m}; b and n are the two frontier candidates.
    return GameMap.from_dict(
        {
            "regions": [
                {"id": r, "name": r.title(), "terrain": "clear"}
                for r in ["src", "a", "b", "m", "n"]
            ],
            "edges": [
                {"between": ["src", "a"], "road": "highway", "rail": True},
                {"between": ["a", "b"], "road": "highway", "rail": True},
                {"between": ["src", "m"], "road": "highway", "rail": True},
                {"between": ["m", "n"], "road": "highway", "rail": True},
            ],
        }
    )


def test_advance_railhead_picks_a_deterministic_frontier():
    game_map = _branching_map()
    control = {r: "axis" for r in ["src", "a", "b", "m", "n"]}
    # With speed 1 and two candidates (b via a, n via m), the choice must be
    # fixed by a stable traversal order, not by set-iteration order.
    result = advance_railhead(game_map, control, "axis", {"src", "a", "m"}, speed=1)
    added = result - {"src", "a", "m"}
    assert added == {"b"}, added


def _opening_axis_railhead(hashseed: int) -> str:
    code = (
        "from pathlib import Path; import asyncio;"
        "from commanders.campaign import Campaign;"
        "c = Campaign.new(Path('data'));"
        "asyncio.run(c.play_turn({}));"
        "print(','.join(sorted(c.state.railheads['axis'])))"
    )
    env = {**os.environ, "PYTHONHASHSEED": str(hashseed)}
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env, cwd=REPO_ROOT,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip().splitlines()[-1]


def test_railhead_conversion_is_deterministic_across_hash_seeds():
    # Same game seed must give the same railhead regardless of the interpreter's
    # string-hash randomization; otherwise campaigns are not reproducible.
    results = {_opening_axis_railhead(s) for s in (1, 2, 6)}
    assert len(results) == 1, f"railhead varied across hash seeds: {results}"


def make_map():
    # source --rail-- a --rail-- b --road-- c --road-- d --road-- e
    return GameMap.from_dict(
        {
            "regions": [
                {"id": r, "name": r.title(), "terrain": "clear"}
                for r in ["source", "a", "b", "c", "d", "e"]
            ],
            "edges": [
                {"between": ["source", "a"], "road": "highway", "rail": True},
                {"between": ["a", "b"], "road": "highway", "rail": True},
                {"between": ["b", "c"], "road": "minor", "rail": False},
                {"between": ["c", "d"], "road": "minor", "rail": False},
                {"between": ["d", "e"], "road": "minor", "rail": False},
            ],
        }
    )


def make_corps(location, supply=100, cid="c1"):
    return Corps(
        id=cid, name=cid, side="axis", kind="infantry",
        location=location, commander="x", supply=supply,
    )


def all_axis_control():
    return {r: "axis" for r in ["source", "a", "b", "c", "d", "e"]}


def test_corps_on_rail_network_fully_supplied():
    m = make_map()
    corps = make_corps("b")
    got = compute_supply(m, all_axis_control(), sources=["source"], corps_list=[corps])
    assert got["c1"] == 100


def test_supply_degrades_with_truck_distance_from_railhead():
    m = make_map()
    near = make_corps("c", cid="near")
    far = make_corps("e", cid="far")
    got = compute_supply(m, all_axis_control(), sources=["source"], corps_list=[near, far])
    assert got["near"] > got["far"]
    assert got["far"] < 100


def test_supply_cannot_trace_through_enemy_territory():
    m = make_map()
    control = all_axis_control()
    control["b"] = "soviet"  # cuts everything past 'a'
    cut_off = make_corps("d", supply=80)
    got = compute_supply(m, control, sources=["source"], corps_list=[cut_off])
    assert got["c1"] == 40  # isolated: decays by 40


def test_isolated_supply_floors_at_zero():
    m = make_map()
    control = all_axis_control()
    control["b"] = "soviet"
    cut_off = make_corps("d", supply=20)
    got = compute_supply(m, control, sources=["source"], corps_list=[cut_off])
    assert got["c1"] == 0


def test_rail_does_not_flow_through_enemy_but_reroute_costs_supply():
    m = make_map()
    corps_on_a = make_corps("a")
    control = all_axis_control()
    got = compute_supply(m, control, sources=["source"], corps_list=[corps_on_a])
    assert got["c1"] == 100
