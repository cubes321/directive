from pathlib import Path

from engine.scenario import load_scenario

DATA_DIR = Path(__file__).parent.parent / "data"


def test_scenario_loads_and_is_connected():
    s = load_scenario(DATA_DIR)
    # every region reachable from brest ignoring control
    seen = {"brest"}
    frontier = ["brest"]
    while frontier:
        here = frontier.pop()
        for n in s.game_map.neighbors(here):
            if n not in seen:
                seen.add(n)
                frontier.append(n)
    assert seen == set(s.game_map.regions)


def test_axis_controls_only_start_regions():
    s = load_scenario(DATA_DIR)
    axis_regions = {r for r, side in s.control.items() if side == "axis"}
    assert axis_regions == {"warsaw", "siedlce", "lomza", "brest", "suwalki"}
    assert s.control["moscow"] == "soviet"


def test_all_corps_locations_and_sources_exist_on_map():
    s = load_scenario(DATA_DIR)
    for corps in s.corps.values():
        assert corps.location in s.game_map.regions, corps.id
    for sources in s.supply_sources.values():
        for src in sources:
            assert src in s.game_map.regions


def test_moscow_is_the_biggest_prize():
    s = load_scenario(DATA_DIR)
    vps = {r.id: r.victory_points for r in s.game_map.regions.values()}
    assert max(vps, key=vps.get) == "moscow"


def test_both_sides_start_fully_supplied_on_rail():
    s = load_scenario(DATA_DIR)
    starved = [c.id for c in s.corps.values() if c.supply < 100]
    assert starved == []
