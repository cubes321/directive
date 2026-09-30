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


def test_duplicate_orders_for_one_corps_are_rejected():
    # An LLM issuing e.g. advance then defend for the same corps must not slip
    # through: resolution would move it AND record a defend, blending the two.
    game_map, corps, control = setup()
    orders = CommanderOrders(
        commander="guderian",
        orders=[
            CorpsOrder(corps_id="xxiv_pz", posture="advance", objective="minsk"),
            CorpsOrder(corps_id="xxiv_pz", posture="defend", objective=None),
        ],
        dispatch="",
    )
    errors = validate_orders(orders, game_map, corps, control)
    assert any("xxiv_pz" in e and "one" in e.lower() for e in errors)


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


def test_out_of_reach_error_names_the_reachable_regions():
    # The rejection used to say only what was illegal. Quoted back to a cautious
    # commander that reads as "you cannot move", and he drops the advance
    # entirely instead of taking the intermediate bound - which is exactly what
    # Strauss did for four turns. Tell him where he CAN go.
    game_map, corps, control = setup()
    orders = CommanderOrders(
        commander="guderian",
        orders=[CorpsOrder(corps_id="xxiv_pz", posture="advance", objective="vyazma")],
        dispatch="",
    )
    error = next(e for e in validate_orders(orders, game_map, corps, control) if "vyazma" in e)
    assert "minsk" in error   # xxiv_pz sits at brest; minsk is one highway hop


def test_attack_requires_objective():
    game_map, corps, control = setup()
    orders = CommanderOrders(
        commander="guderian",
        orders=[CorpsOrder(corps_id="xxiv_pz", posture="attack", objective=None)],
        dispatch="",
    )
    errors = validate_orders(orders, game_map, corps, control)
    assert errors


def test_missing_objective_error_names_the_reachable_regions():
    # Same lesson as test_out_of_reach_error_names_the_reachable_regions, on the
    # branch that never learned it. With reasoning turned off, small local models
    # emit `posture: advance, objective: null` constantly (6 of 8 bad orders in
    # logs/run-20260816-163603); "needs an objective" names none, so the repair
    # answers by dropping to defend. Tell him where he CAN go.
    game_map, corps, control = setup()
    orders = CommanderOrders(
        commander="guderian",
        orders=[CorpsOrder(corps_id="xxiv_pz", posture="advance", objective=None)],
        dispatch="",
    )
    error = next(e for e in validate_orders(orders, game_map, corps, control) if "xxiv_pz" in e)
    assert "minsk" in error  # xxiv_pz sits at brest; minsk is one highway hop


def test_missing_objective_error_when_nothing_is_in_reach_says_so():
    # A corps that genuinely cannot move must not be handed an empty list of
    # alternatives - that reads as a dead end and invites a malformed retry.
    # Starving infantry in the October mud has 1 MP; every edge here costs 2.
    game_map, corps, control = setup()
    bogged = make_corps("bogged_ak", kind="infantry", supply=10)
    orders = CommanderOrders(
        commander="guderian",
        orders=[CorpsOrder(corps_id="bogged_ak", posture="advance", objective=None)],
        dispatch="",
    )
    errors = validate_orders(orders, game_map, corps + [bogged], control, weather="mud")
    error = next(e for e in errors if "bogged_ak" in e)
    assert "hold" in error.lower()


def test_ids_are_stripped_when_parsed_from_model_json():
    # Observed from qwen3.5-4b: `"objective": " velikie_luki"`. A stray space is
    # not a disagreement about strategy - it should never reach validation, let
    # alone cost a repair round-trip.
    parsed = CommanderOrders.from_dict(
        {
            "commander": "guderian",
            "orders": [
                {"corps_id": " xxiv_pz ", "posture": "attack", "objective": " minsk"},
            ],
            "dispatch": "",
        }
    )
    assert parsed.orders[0].corps_id == "xxiv_pz"
    assert parsed.orders[0].objective == "minsk"


def test_blank_objective_parses_as_none():
    # "" and "   " mean the same thing as null, and only null is handled below.
    parsed = CommanderOrders.from_dict(
        {
            "commander": "guderian",
            "orders": [{"corps_id": "xxiv_pz", "posture": "defend", "objective": "  "}],
            "dispatch": "",
        }
    )
    assert parsed.orders[0].objective is None


def test_orders_must_cover_all_living_corps():
    game_map, corps, control = setup()
    orders = CommanderOrders(
        commander="guderian",
        orders=[CorpsOrder(corps_id="xxiv_pz", posture="defend", objective=None)],
        dispatch="Only one corps ordered.",
    )
    errors = validate_orders(orders, game_map, corps, control)
    assert any("xlvi_pz" in e for e in errors)  # the unordered corps is named


def test_fallback_orders_defend_in_place_for_all_own_corps():
    _, corps, _ = setup()
    fb = fallback_orders("guderian", corps)
    assert {o.corps_id for o in fb.orders} == {"xxiv_pz", "xlvi_pz"}
    assert all(o.posture == "defend" for o in fb.orders)


def test_salvage_keeps_valid_orders_and_fills_the_rest():
    from engine.orders import salvage_orders

    game_map, corps, control = setup()
    orders = CommanderOrders(
        commander="guderian",
        orders=[
            CorpsOrder(corps_id="xxiv_pz", posture="attack", objective="minsk"),  # valid
            CorpsOrder(corps_id="xlvi_pz", posture="attack", objective="atlantis"),  # bad region
            # xlvii missing entirely -> should be filled with defend
        ],
        dispatch="Forward to Minsk!",
    )
    corps.append(make_corps("xlvii_pz", location="brest"))
    salvaged = salvage_orders(orders, game_map, corps, control)
    assert validate_orders(salvaged, game_map, corps, control) == []
    by_id = {o.corps_id: o for o in salvaged.orders}
    assert by_id["xxiv_pz"].objective == "minsk"  # the good order survived
    assert by_id["xlvi_pz"].posture == "defend"  # the bad one was defused
    assert by_id["xlvii_pz"].posture == "defend"  # the missing one was filled
    assert salvaged.dispatch == "Forward to Minsk!"  # personality preserved


def test_orders_serialization_round_trip():
    orders = CommanderOrders(
        commander="guderian",
        orders=[CorpsOrder(corps_id="xxiv_pz", posture="attack", objective="minsk")],
        dispatch="Forward!",
    )
    assert CommanderOrders.from_dict(orders.to_dict()) == orders


def test_an_order_keyed_corps_instead_of_corps_id_is_read_as_that_corps():
    # kimi-k2.6 writes "corps" for "corps_id" in every order under the per-turn
    # schema (0/30 first-try successes in the 2026-09-12 playtest): a format slip,
    # not a disagreement worth a paid repair round-trip.
    orders = CommanderOrders.from_dict({
        "commander": "guderian",
        "orders": [{"corps": " xxiv_pz", "posture": "attack", "objective": "minsk"}],
    })
    assert orders.orders[0].corps_id == "xxiv_pz"


def test_corps_id_wins_when_an_order_carries_both_keys():
    orders = CommanderOrders.from_dict({
        "commander": "guderian",
        "orders": [{"corps_id": "xxiv_pz", "corps": "xlvi_pz", "posture": "defend"}],
    })
    assert orders.orders[0].corps_id == "xxiv_pz"
