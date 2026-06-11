from engine.orders import CommanderOrders, CorpsOrder
from engine.state import GameState
from engine.turn import resolve_turn


def state_data():
    # west -- center -- east -- far_east (all highway+rail)
    # axis: 2 panzer corps at west; soviet: 1 weak corps at east
    return {
        "map": {
            "regions": [
                {"id": r, "name": r.title(), "terrain": "clear"}
                for r in ["west", "center", "east", "far_east"]
            ],
            "edges": [
                {"between": ["west", "center"], "road": "highway", "rail": True},
                {"between": ["center", "east"], "road": "highway", "rail": True},
                {"between": ["east", "far_east"], "road": "highway", "rail": True},
            ],
        },
        "corps": [
            {"id": "ax1", "name": "Ax1", "side": "axis", "kind": "panzer",
             "location": "west", "commander": "guderian"},
            {"id": "ax2", "name": "Ax2", "side": "axis", "kind": "panzer",
             "location": "west", "commander": "guderian"},
            {"id": "sv1", "name": "Sv1", "side": "soviet", "kind": "infantry",
             "location": "east", "commander": "pavlov", "strength": 30, "organization": 30},
        ],
        "control": {"west": "axis", "center": "soviet", "east": "soviet", "far_east": "soviet"},
        "supply_sources": {"axis": ["west"], "soviet": ["far_east"]},
        "turn": 1,
        "seed": 42,
    }


def orders(*corps_orders, commander="guderian"):
    return {
        commander: CommanderOrders(
            commander=commander, orders=list(corps_orders), dispatch=""
        )
    }


def test_advance_into_empty_enemy_region_flips_control():
    s = GameState.from_dict(state_data())
    resolve_turn(s, orders(CorpsOrder("ax1", "advance", "center")))
    assert s.corps["ax1"].location == "center"
    assert s.control["center"] == "axis"


def test_turn_counter_increments():
    s = GameState.from_dict(state_data())
    resolve_turn(s, {})
    assert s.turn == 2


def test_overwhelming_attack_takes_region_and_mauls_defender():
    s = GameState.from_dict(state_data())
    # both panzer corps strike the weak soviet corps via center first
    resolve_turn(s, orders(
        CorpsOrder("ax1", "attack", "center"),
        CorpsOrder("ax2", "attack", "center"),
    ))
    report = resolve_turn(s, orders(
        CorpsOrder("ax1", "attack", "east"),
        CorpsOrder("ax2", "attack", "east"),
    ))
    assert s.control["east"] == "axis"
    assert s.corps["ax1"].location == "east"
    assert s.corps["sv1"].location == "far_east"  # retreated
    assert s.corps["sv1"].strength < 30
    assert any(c["region"] == "east" for c in report.combats)


def test_repulsed_attacker_stays_put():
    data = state_data()
    data["corps"][0]["strength"] = 25  # lone weak attacker
    data["corps"][0]["organization"] = 40
    data["corps"][2].update(strength=100, organization=100, location="center")
    s = GameState.from_dict(data)
    resolve_turn(s, orders(CorpsOrder("ax1", "attack", "center")))
    assert s.corps["ax1"].location == "west"
    assert s.control["center"] == "soviet"


def test_defender_with_no_retreat_path_is_destroyed():
    data = state_data()
    # soviet corps at center, axis controls everything else around it
    data["corps"][2]["location"] = "center"
    data["control"] = {"west": "axis", "center": "soviet", "east": "axis", "far_east": "axis"}
    s = GameState.from_dict(data)
    resolve_turn(s, orders(
        CorpsOrder("ax1", "attack", "center"),
        CorpsOrder("ax2", "attack", "center"),
    ))
    assert s.corps["sv1"].is_destroyed


def test_reserve_posture_recovers_organization():
    data = state_data()
    data["corps"][0]["organization"] = 50
    s = GameState.from_dict(data)
    resolve_turn(s, orders(CorpsOrder("ax1", "reserve", None)))
    assert s.corps["ax1"].organization > 50


def test_supply_updates_after_movement():
    s = GameState.from_dict(state_data())
    resolve_turn(s, orders(CorpsOrder("ax1", "advance", "center")))
    # center is rail-connected to the axis source once captured
    assert s.corps["ax1"].supply == 100


def test_movement_respects_stacking_limit():
    data = state_data()
    # three axis corps already in center; a fourth tries to join
    data["corps"] += [
        {"id": f"ax{i}", "name": f"Ax{i}", "side": "axis", "kind": "infantry",
         "location": "center", "commander": "kluge"} for i in (3, 4, 5)
    ]
    data["control"]["center"] = "axis"
    s = GameState.from_dict(data)
    resolve_turn(s, orders(CorpsOrder("ax1", "advance", "center")))
    assert s.corps["ax1"].location == "west"  # bounced: center is full


def test_combat_losses_are_distributed_not_rounded_away():
    data = state_data()
    # strong defender so the attack is repulsed with real attacker losses
    data["corps"][2].update(strength=100, organization=100, location="center")
    s = GameState.from_dict(data)
    report = resolve_turn(s, orders(
        CorpsOrder("ax1", "attack", "center"),
        CorpsOrder("ax2", "attack", "center"),
    ))
    combat = report.combats[0]
    applied = 200 - s.corps["ax1"].strength - s.corps["ax2"].strength
    assert applied == combat["attacker_losses"]  # nothing lost to rounding


def test_retreat_into_full_region_means_surrender():
    data = state_data()
    # soviet defender at center; its only friendly neighbor (east) is full
    data["corps"][2]["location"] = "center"
    data["corps"] += [
        {"id": f"sv{i}", "name": f"Sv{i}", "side": "soviet", "kind": "infantry",
         "location": "east", "commander": "pavlov"} for i in (2, 3, 4)
    ]
    data["control"] = {"west": "axis", "center": "soviet", "east": "soviet",
                       "far_east": "axis"}
    s = GameState.from_dict(data)
    resolve_turn(s, orders(
        CorpsOrder("ax1", "attack", "center"),
        CorpsOrder("ax2", "attack", "center"),
    ))
    assert s.corps["sv1"].is_destroyed


def test_resolution_is_deterministic():
    def play():
        s = GameState.from_dict(state_data())
        resolve_turn(s, orders(
            CorpsOrder("ax1", "attack", "center"),
            CorpsOrder("ax2", "attack", "center"),
        ))
        return s.to_dict()

    assert play() == play()
