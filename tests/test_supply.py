from engine.map import GameMap
from engine.supply import compute_supply
from engine.units import Corps


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
