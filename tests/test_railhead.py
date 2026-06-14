from engine.map import GameMap
from engine.supply import (
    advance_railhead,
    compute_supply,
    default_railhead_on_load,
    initial_railhead,
)
from engine.units import Corps


def line_map():
    # s == a == b == c == d, all rail+highway
    return GameMap.from_dict(
        {
            "regions": [{"id": r, "name": r.upper(), "terrain": "clear"}
                        for r in ["s", "a", "b", "c", "d"]],
            "edges": [
                {"between": [x, y], "road": "highway", "rail": True}
                for x, y in [("s", "a"), ("a", "b"), ("b", "c"), ("c", "d")]
            ],
        }
    )


def corps(loc, cid="c1"):
    return Corps(id=cid, name=cid, side="axis", kind="infantry", location=loc, commander="x")


def all_axis():
    return {r: "axis" for r in ["s", "a", "b", "c", "d"]}


def test_unconverted_captured_rail_costs_supply():
    # railhead only reaches 'a'; b,c,d are captured but not yet converted
    got = compute_supply(line_map(), all_axis(), ["s"], [corps("c", "far")],
                         converted={"s", "a"})
    assert got["far"] < 100  # two truck legs beyond the railhead


def test_converting_the_whole_line_restores_supply():
    got = compute_supply(line_map(), all_axis(), ["s"], [corps("d", "tip")],
                         converted={"s", "a", "b", "c", "d"})
    assert got["tip"] == 100


def test_supply_falls_off_with_distance_beyond_railhead():
    m, ctrl = line_map(), all_axis()
    near = compute_supply(m, ctrl, ["s"], [corps("b", "near")], converted={"s", "a"})["near"]
    far = compute_supply(m, ctrl, ["s"], [corps("d", "far")], converted={"s", "a"})["far"]
    assert near > far


def test_converted_none_keeps_legacy_all_rail_free():
    # backward compatible: without a converted set, friendly rail is all free
    got = compute_supply(line_map(), all_axis(), ["s"], [corps("d", "tip")])
    assert got["tip"] == 100


def test_advance_railhead_crawls_one_region_per_turn():
    m, ctrl = line_map(), all_axis()
    conv = advance_railhead(m, ctrl, "axis", {"s"}, 1)
    assert conv == {"s", "a"}
    conv = advance_railhead(m, ctrl, "axis", conv, 1)
    assert conv == {"s", "a", "b"}


def test_advance_railhead_respects_speed():
    conv = advance_railhead(line_map(), all_axis(), "axis", {"s"}, 2)
    assert conv == {"s", "a", "b"}


def test_railhead_cannot_convert_through_enemy():
    ctrl = all_axis()
    ctrl["b"] = "soviet"
    conv = advance_railhead(line_map(), ctrl, "axis", {"s", "a"}, 5)
    assert "b" not in conv and "c" not in conv


def test_railhead_drops_regions_lost_to_the_enemy():
    ctrl = all_axis()
    ctrl["b"] = "soviet"
    conv = advance_railhead(line_map(), ctrl, "axis", {"s", "a", "b"}, 1)
    assert "b" not in conv


def test_initial_railhead_covers_prewar_network_only():
    ctrl = {"s": "axis", "a": "axis", "b": "soviet", "c": "soviet", "d": "soviet"}
    assert initial_railhead(line_map(), ctrl, "axis", ["s"]) == {"s", "a"}


def test_default_on_load_lags_behind_the_front():
    # a long held corridor: the railhead should sit behind the deepest point
    converted = default_railhead_on_load(line_map(), all_axis(), "axis", ["s"])
    assert "d" not in converted  # the tip is not yet converted
    assert "s" in converted and "a" in converted  # the rear is


def test_scenario_starts_railhead_at_the_prewar_network():
    from pathlib import Path

    from engine.scenario import load_scenario

    state = load_scenario(Path(__file__).parent.parent / "data")
    converted = {state.game_map.regions[r].name for r in state.railheads["axis"]}
    assert "Warsaw" in converted  # home rail is converted
    assert "Smolensk" not in converted  # nothing captured yet, let alone converted
    assert state.railheads["soviet"]  # the soviet side has a railhead too
