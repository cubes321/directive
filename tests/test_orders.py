from engine.map import GameMap
from engine.orders import CommanderOrders, CorpsOrder, fallback_orders, validate_orders
from engine.units import Corps


def make_map():
    return GameMap.from_dict(
        {
            "regions": [
                {"id": r, "name": r.title(), "terrain": "clear"}
                for r in ["brest", "minsk", "orsha", "smolensk", "vyazma"]
            ],
            "edges": [
                {"between": ["brest", "minsk"], "road": "highway", "rail": True},
                {"between": ["minsk", "orsha"], "road": "highway", "rail": True},
                {"between": ["orsha", "smolensk"], "road": "highway", "rail": True},
                {"between": ["smolensk", "vyazma"], "road": "highway", "rail": True},
            ],
        }
    )


def make_corps(cid, commander="guderian", side="axis", location="brest", **kw):
    base = dict(id=cid, name=cid, side=side, kind="panzer", location=location, commander=commander)
    base.update(kw)
    return Corps(**base)


def setup():
    game_map = make_map()
    corps = [
        make_corps("xxiv_pz"),
        make_corps("xlvi_pz", location="minsk"),
        make_corps("other_corps", commander="hoth", location="minsk"),
        make_corps("sov_1", commander="pavlov", side="soviet", location="smolensk"),
    ]
    control = {"brest": "axis", "minsk": "axis", "orsha": "axis",
               "smolensk": "soviet", "vyazma": "soviet"}
    return game_map, corps, control


def test_valid_orders_produce_no_errors():
    game_map, corps, control = setup()
    orders = CommanderOrders(
        commander="guderian",
        orders=[
            CorpsOrder(corps_id="xxiv_pz", posture="attack", objective="minsk"),
            CorpsOrder(corps_id="xlvi_pz", posture="defend", objective=None),
        ],
        dispatch="Advancing on Minsk.",
    )
    assert validate_orders(orders, game_map, corps, control) == []


def test_ordering_another_commanders_corps_is_an_error():
    game_map, corps, control = setup()
    orders = CommanderOrders(
        commander="guderian",
        orders=[CorpsOrder(corps_id="other_corps", posture="defend", objective=None)],
        dispatch="",
    )
    errors = validate_orders(orders, game_map, corps, control)
    assert any("other_corps" in e for e in errors)


def test_unknown_corps_is_an_error():
    game_map, corps, control = setup()
    orders = CommanderOrders(
        commander="guderian",
        orders=[CorpsOrder(corps_id="ghost_corps", posture="defend", objective=None)],
        dispatch="",
    )
    errors = validate_orders(orders, game_map, corps, control)
    assert any("ghost_corps" in e for e in errors)


def test_unknown_objective_region_is_an_error():
    game_map, corps, control = setup()
    orders = CommanderOrders(
        commander="guderian",
        orders=[CorpsOrder(corps_id="xxiv_pz", posture="attack", objective="berlin")],
        dispatch="",
    )
    errors = validate_orders(orders, game_map, corps, control)
    assert any("berlin" in e for e in errors)


def test_unreachable_objective_is_an_error():
    game_map, corps, control = setup()
    # vyazma is 3 highway hops behind enemy-held smolensk: out of reach this turn
    orders = CommanderOrders(
        commander="guderian",
        orders=[CorpsOrder(corps_id="xxiv_pz", posture="attack", objective="vyazma")],
        dispatch="",
    )
    errors = validate_orders(orders, game_map, corps, control)
    assert any("vyazma" in e for e in errors)


def test_attack_requires_objective():
    game_map, corps, control = setup()
    orders = CommanderOrders(
        commander="guderian",
        orders=[CorpsOrder(corps_id="xxiv_pz", posture="attack", objective=None)],
        dispatch="",
    )
    errors = validate_orders(orders, game_map, corps, control)
    assert errors


def test_fallback_orders_defend_in_place_for_all_own_corps():
    _, corps, _ = setup()
    fb = fallback_orders("guderian", corps)
    assert {o.corps_id for o in fb.orders} == {"xxiv_pz", "xlvi_pz"}
    assert all(o.posture == "defend" for o in fb.orders)


def test_orders_serialization_round_trip():
    orders = CommanderOrders(
        commander="guderian",
        orders=[CorpsOrder(corps_id="xxiv_pz", posture="attack", objective="minsk")],
        dispatch="Forward!",
    )
    assert CommanderOrders.from_dict(orders.to_dict()) == orders
