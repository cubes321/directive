from engine.orders import CommanderOrders, CorpsOrder
from engine.state import GameState
from engine.turn import _distribute_losses, resolve_turn
from engine.units import Corps


def _corps(cid, strength=100, organization=100, supply=100):
    return Corps(id=cid, name=cid.upper(), side="axis", kind="infantry",
                 location="x", commander="c", strength=strength,
                 organization=organization, supply=supply)


def test_distribute_losses_never_wastes_points_on_destroyed_corps():
    small, big = _corps("s", strength=5), _corps("b", strength=100)
    applied_str, _ = _distribute_losses([small, big], 20, 0)
    # all 20 land on living corps: 5 finish the small one, 15 fall on the big one
    assert applied_str == 20
    assert (5 - small.strength) + (100 - big.strength) == 20
    assert small.strength == 0


def test_distribute_losses_reports_only_what_can_be_applied():
    a, b = _corps("a", strength=5), _corps("b", strength=3)
    applied_str, _ = _distribute_losses([a, b], 20, 0)
    assert applied_str == 8  # only 8 strength points existed to remove


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


def test_encircled_corps_at_full_strength_is_mauled_not_erased():
    # A pocket used to kill outright at ANY strength: two full panzer corps at
    # Yelnya went from untouched to gone in one resolution, with no turn in which
    # the player could relieve them. A strong formation must survive the first
    # blow, badly hurt, and only collapse if the ring holds.
    data = state_data()
    data["corps"][2].update(location="center", strength=100, organization=100)
    data["control"] = {"west": "axis", "center": "soviet", "east": "axis", "far_east": "axis"}
    s = GameState.from_dict(data)
    attack = orders(CorpsOrder("ax1", "attack", "center"), CorpsOrder("ax2", "attack", "center"))

    for assault in (1, 2):
        resolve_turn(s, attack)
        assert not s.corps["sv1"].is_destroyed, f"collapsed on assault {assault}"
        assert s.corps["sv1"].strength < 100         # but bleeding every time
        assert s.corps["sv1"].location == "center"   # nowhere to go: still in the bag
        assert s.control["center"] == "soviet"       # and the ground is still theirs

    resolve_turn(s, attack)
    assert s.corps["sv1"].is_destroyed               # third assault reduces the pocket


def test_reducing_a_pocket_is_not_reported_as_a_repulse():
    # The region does not change hands while a live defender stands on it, which
    # is right - but that was reported as outcome "defender_held", i.e. exactly
    # the same as being thrown back. A real game showed a 62:1 assault that cost
    # the attacker 1 and the defender 34 rendered to the player as "Assault
    # repulsed", so he fed in more corps for three turns running.
    data = state_data()
    data["corps"][2].update(location="center", strength=100, organization=100)
    data["control"] = {"west": "axis", "center": "soviet", "east": "axis", "far_east": "axis"}
    s = GameState.from_dict(data)
    report = resolve_turn(s, orders(
        CorpsOrder("ax1", "attack", "center"), CorpsOrder("ax2", "attack", "center"),
    ))
    combat = report.combats[0]
    assert combat["outcome"] == "pocket_holding"
    assert combat["defender_losses"] > combat["attacker_losses"]


def test_a_genuine_repulse_is_still_a_repulse():
    # regression: an ordinary failed attack must not be dressed up as a pocket
    data = state_data()
    data["corps"][0].update(strength=25, organization=40)
    data["corps"][2].update(strength=100, organization=100, location="center")
    s = GameState.from_dict(data)
    report = resolve_turn(s, orders(CorpsOrder("ax1", "attack", "center")))
    assert report.combats[0]["outcome"] == "defender_held"


def test_contained_pocket_is_not_destroyed_by_containment_alone():
    # Historically a Kessel that was merely masked held out for weeks. Losses
    # come from assaulting it, so a turn without an attack costs the pocket
    # nothing - the encircling side pays in time instead.
    data = state_data()
    data["corps"][2].update(location="center", strength=100, organization=100)
    data["control"] = {"west": "axis", "center": "soviet", "east": "axis", "far_east": "axis"}
    s = GameState.from_dict(data)
    for _ in range(5):
        resolve_turn(s, orders(CorpsOrder("ax1", "defend", None)))
    assert not s.corps["sv1"].is_destroyed
    assert s.corps["sv1"].strength == 100


def test_reserve_posture_recovers_organization():
    data = state_data()
    data["corps"][0]["organization"] = 50
    s = GameState.from_dict(data)
    resolve_turn(s, orders(CorpsOrder("ax1", "reserve", None)))
    assert s.corps["ax1"].organization > 50


def test_cut_off_corps_cannot_refit_itself():
    # Recovery is rest AND resupply. A corps with no supply was still rebuilding
    # organization: in a real game xlvi_pz went org 82 -> 100 at supply 0, inside
    # a pocket, the turn before it died.
    data = state_data()
    data["corps"][0].update(organization=50, supply=0)
    s = GameState.from_dict(data)
    resolve_turn(s, orders(CorpsOrder("ax1", "reserve", None)))
    assert s.corps["ax1"].organization == 50


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


def test_marching_inside_your_supply_costs_nothing():
    from engine.turn import march_wastage
    c = _corps("c")           # supply defaults to 100
    assert march_wastage(c, "clear") == 0


def test_wastage_grows_with_the_supply_shortfall():
    from engine.turn import march_wastage
    assert march_wastage(_corps("a", supply=75), "clear") == 1
    assert march_wastage(_corps("b", supply=20), "clear") == 3
    assert march_wastage(_corps("c", supply=0), "clear") == 4


def test_wastage_is_worse_in_mud_and_snow():
    from engine.turn import march_wastage
    outrun = dict(supply=20)
    assert march_wastage(_corps("a", **outrun), "mud") == 6
    assert march_wastage(_corps("b", **outrun), "snow") == 8


def test_a_corps_that_marched_past_its_railhead_bleeds():
    data = state_data()
    data["corps"][0]["supply"] = 20
    data["control"]["center"] = "axis"     # empty friendly ground: an uncontested move
    s = GameState.from_dict(data)
    before = s.corps["ax1"].strength
    resolve_turn(s, orders(CorpsOrder("ax1", "advance", "center")))
    assert s.corps["ax1"].strength < before
    assert s.corps["ax1"].damage_taken > 0   # and it lowers the ceiling


def test_a_corps_that_stayed_put_does_not_waste_away():
    # The cost of standing still is the ground you are not taking, not blood.
    # This is also what keeps a contained pocket alive.
    data = state_data()
    s = GameState.from_dict(data)
    s.corps["ax1"].supply = 0
    before = s.corps["ax1"].strength
    resolve_turn(s, orders(CorpsOrder("ax1", "defend", None)))
    assert s.corps["ax1"].strength == before


def test_advancing_after_winning_combat_pays_wastage():
    # Location changes here via the "defenders_gone" advance inside the combat
    # branch, never through report.movements - the set that used to be charged
    # for wastage never saw this corps at all.
    from engine.turn import march_wastage

    data = state_data()
    data["corps"][0]["supply"] = 20  # attacker outrunning its railhead
    data["corps"][2].update(strength=10, organization=10, location="center")
    s = GameState.from_dict(data)
    before = s.corps["ax1"].strength
    report = resolve_turn(s, orders(CorpsOrder("ax1", "attack", "center")))

    combat = report.combats[0]
    assert combat["outcome"] != "defender_held"  # the weak defender broke
    assert s.corps["ax1"].location == "center"  # attacker advanced

    expected_wastage = march_wastage(_corps("x", supply=20), "clear")
    assert expected_wastage > 0
    assert before - s.corps["ax1"].strength == combat["attacker_losses"] + expected_wastage


def test_retreating_from_lost_combat_pays_wastage():
    # Location changes via the retreat branch, also never recorded in
    # report.movements.
    from engine.turn import march_wastage

    data = state_data()
    data["corps"][2].update(location="center", supply=20)  # weak, starved defender
    s = GameState.from_dict(data)
    before = s.corps["sv1"].strength
    report = resolve_turn(s, orders(
        CorpsOrder("ax1", "attack", "center"),
        CorpsOrder("ax2", "attack", "center"),
    ))

    combat = report.combats[0]
    assert combat["outcome"] == "defender_retreated"
    assert s.corps["sv1"].location == "east"  # retreated, did not vanish

    expected_wastage = march_wastage(_corps("x", supply=20), "clear")
    assert expected_wastage > 0
    assert before - s.corps["sv1"].strength == combat["defender_losses"] + expected_wastage


def test_bounced_corps_pays_no_wastage():
    # Regression: a corps that failed to squeeze into a full region never
    # actually moved, so it must not be charged even if it is starving.
    data = state_data()
    data["corps"] += [
        {"id": f"ax{i}", "name": f"Ax{i}", "side": "axis", "kind": "infantry",
         "location": "center", "commander": "kluge"} for i in (3, 4, 5)
    ]
    data["control"]["center"] = "axis"
    data["corps"][0]["supply"] = 0
    s = GameState.from_dict(data)
    before = s.corps["ax1"].strength
    resolve_turn(s, orders(CorpsOrder("ax1", "advance", "center")))
    assert s.corps["ax1"].location == "west"  # bounced
    assert s.corps["ax1"].strength == before


def test_newly_arrived_reinforcement_pays_no_wastage():
    # Regression: a reinforcement spawning this turn has not marched anywhere
    # and must not be charged, no matter what supply value it spawns with.
    data = state_data()
    data["reinforcements"] = [{
        "turn": 1,
        "corps": {"id": "ax9", "name": "Ax9", "side": "axis", "kind": "infantry",
                  "location": "west", "commander": "kluge", "supply": 0},
    }]
    s = GameState.from_dict(data)
    resolve_turn(s, {})
    assert s.corps["ax9"].strength == 100
