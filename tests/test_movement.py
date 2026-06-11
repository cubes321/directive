from engine.map import GameMap
from engine.movement import move_cost, movement_points, reachable
from engine.units import Corps


def make_map():
    # brest --hw-- minsk --hw-- orsha --hw-- smolensk, plus a marsh detour
    return GameMap.from_dict(
        {
            "regions": [
                {"id": "brest", "name": "Brest", "terrain": "clear"},
                {"id": "minsk", "name": "Minsk", "terrain": "urban"},
                {"id": "orsha", "name": "Orsha", "terrain": "clear"},
                {"id": "smolensk", "name": "Smolensk", "terrain": "urban"},
                {"id": "marsh", "name": "Marshes", "terrain": "marsh"},
            ],
            "edges": [
                {"between": ["brest", "minsk"], "road": "highway", "rail": True},
                {"between": ["minsk", "orsha"], "road": "highway", "rail": True},
                {"between": ["orsha", "smolensk"], "road": "highway", "rail": True},
                {"between": ["brest", "marsh"], "road": "none", "rail": False},
                {"between": ["marsh", "orsha"], "road": "none", "rail": False},
            ],
        }
    )


def make_corps(**overrides):
    base = dict(id="c1", name="C1", side="axis", kind="panzer", location="brest", commander="x")
    base.update(overrides)
    return Corps(**base)


def test_panzer_moves_farther_than_infantry():
    assert movement_points(make_corps(kind="panzer")) > movement_points(
        make_corps(kind="infantry")
    )


def test_low_supply_halves_movement():
    fresh = make_corps()
    starved = make_corps(supply=10)
    assert movement_points(starved) == movement_points(fresh) // 2


def test_highway_cheaper_than_no_road():
    m = make_map()
    assert move_cost(m, "brest", "minsk") < move_cost(m, "brest", "marsh")


def test_marsh_terrain_costs_extra():
    m = make_map()
    assert move_cost(m, "brest", "marsh") > move_cost(m, "marsh", "orsha") - 2


def test_reachable_respects_budget():
    m = make_map()
    # Panzer with 6 MP from brest: minsk (2), orsha (4), smolensk (6)
    got = reachable(m, "brest", mp=6)
    assert got["minsk"] == 2
    assert got["orsha"] == 4
    assert got["smolensk"] == 6
    assert "brest" not in got


def test_cannot_move_through_enemy_region_but_can_end_there():
    m = make_map()
    got = reachable(m, "brest", mp=6, blocked={"minsk"})
    assert "minsk" in got  # can attack into it
    assert "orsha" not in got or got["orsha"] > 4  # not via minsk highway
