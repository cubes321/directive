from engine.map import GameMap


def make_map_data():
    return {
        "regions": [
            {"id": "minsk", "name": "Minsk", "terrain": "urban", "victory_points": 5},
            {"id": "borisov", "name": "Borisov", "terrain": "clear"},
            {"id": "orsha", "name": "Orsha", "terrain": "clear"},
            {"id": "pripyat", "name": "Pripyat Marshes", "terrain": "marsh"},
        ],
        "edges": [
            {"between": ["minsk", "borisov"], "road": "highway", "rail": True},
            {"between": ["borisov", "orsha"], "road": "highway", "rail": True},
            {"between": ["minsk", "pripyat"], "road": "minor", "rail": False},
        ],
    }


def test_map_builds_regions_from_dict():
    m = GameMap.from_dict(make_map_data())
    assert m.regions["minsk"].name == "Minsk"
    assert m.regions["minsk"].terrain == "urban"
    assert m.regions["minsk"].victory_points == 5
    assert m.regions["borisov"].victory_points == 0


def test_neighbors_are_symmetric():
    m = GameMap.from_dict(make_map_data())
    assert set(m.neighbors("minsk")) == {"borisov", "pripyat"}
    assert m.neighbors("orsha") == ["borisov"]


def test_edge_lookup_works_in_both_directions():
    m = GameMap.from_dict(make_map_data())
    assert m.edge("minsk", "borisov").road == "highway"
    assert m.edge("borisov", "minsk").rail is True
    assert m.edge("minsk", "pripyat").rail is False


def test_unknown_edge_raises():
    m = GameMap.from_dict(make_map_data())
    import pytest

    with pytest.raises(KeyError):
        m.edge("minsk", "orsha")


def test_edge_referencing_unknown_region_rejected():
    import pytest

    data = make_map_data()
    data["edges"].append({"between": ["minsk", "atlantis"], "road": "minor", "rail": False})
    with pytest.raises(ValueError, match="atlantis"):
        GameMap.from_dict(data)
