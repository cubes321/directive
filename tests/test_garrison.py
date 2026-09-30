"""The staff holds back a garrison (playtests 2026-09-30).

Told "keep two corps in Smolensk", Guderian and Kluge marched every corps to
Yelnya; the Soviets walked into the empty city and OKH docked 6 standing. With
free-hand orders nobody garrisoned Minsk at all. Rule: when every corps a side
has in a city (or a live OKH objective) is ordered out, none is ordered in, and
an enemy-held region borders it, the slowest of them stays behind.

Replaying the recorded games, it saved each city in the week it was lost -
Smolensk in playthrough A, Minsk in B, Minsk in last night's P2 (standing 5 ->
13). A weak phantom "security unit" instead saved none of them: every loss that
mattered was a real army marching into an empty city.
"""

from engine.orders import CommanderOrders, CorpsOrder
from engine.state import GameState
from engine.turn import resolve_turn


def _state(terrain="urban", enemy_next_door=True, extra_corps=(), objectives=()):
    # rear -- city -- front, all rail; axis holds rear and city
    data = {
        "map": {
            "regions": [
                {"id": "rear", "name": "Rear", "terrain": "clear"},
                {"id": "city", "name": "City", "terrain": terrain},
                {"id": "front", "name": "Front", "terrain": "clear"},
            ],
            "edges": [
                {"between": ["rear", "city"], "road": "highway", "rail": True},
                {"between": ["city", "front"], "road": "highway", "rail": True},
            ],
        },
        "corps": [
            {"id": "inf", "name": "Inf", "side": "axis", "kind": "infantry",
             "location": "city", "commander": "kluge"},
            {"id": "pz", "name": "Pz", "side": "axis", "kind": "panzer",
             "location": "city", "commander": "guderian"},
            *extra_corps,
        ],
        "control": {"rear": "axis", "city": "axis",
                    "front": "soviet" if enemy_next_door else "axis"},
        "supply_sources": {"axis": ["rear"], "soviet": ["front"]},
        "objectives": list(objectives),
        "turn": 1,
        "seed": 42,
    }
    return GameState.from_dict(data)


def _orders(*orders):
    by_commander: dict[str, list[CorpsOrder]] = {}
    for commander, order in orders:
        by_commander.setdefault(commander, []).append(order)
    return {c: CommanderOrders(commander=c, orders=o, dispatch="") for c, o in by_commander.items()}


def _everyone_leaves():
    return _orders(("kluge", CorpsOrder("inf", "advance", "rear")),
                   ("guderian", CorpsOrder("pz", "advance", "rear")))


def test_the_last_corps_out_of_a_city_facing_the_enemy_is_held_back():
    s = _state()
    report = resolve_turn(s, _everyone_leaves())
    assert s.corps["inf"].location == "city"
    assert s.control["city"] == "axis"
    assert {"corps": "inf", "to": "city", "held_as_garrison": True,
            "ordered_to": "rear"} in report.movements


def test_the_slowest_corps_stays_and_the_panzers_still_go():
    # Guderian's lunge is not cancelled; one infantry corps is kept behind.
    s = _state()
    resolve_turn(s, _everyone_leaves())
    assert s.corps["pz"].location == "rear"


def test_no_enemy_next_door_means_no_garrison_is_needed():
    s = _state(enemy_next_door=False)
    report = resolve_turn(s, _everyone_leaves())
    assert s.corps["inf"].location == "rear"
    assert not any(m.get("held_as_garrison") for m in report.movements)


def test_open_country_is_not_garrisoned():
    s = _state(terrain="clear")
    resolve_turn(s, _everyone_leaves())
    assert s.corps["inf"].location == "rear"


def test_a_live_okh_objective_is_garrisoned_even_in_open_country():
    # Gomel and Bryansk are OKH targets but not urban
    objective = {"id": "take_city", "title": "Take the city", "kind": "capture", "target": "city",
                 "issued_turn": 1, "deadline_turn": 4, "status": "met", "reward": 3, "penalty": 3}
    s = _state(terrain="clear", objectives=[objective])
    resolve_turn(s, _everyone_leaves())
    assert s.corps["inf"].location == "city"


def test_a_corps_that_stays_is_garrison_enough():
    s = _state()
    resolve_turn(s, _orders(("kluge", CorpsOrder("inf", "defend", None)),
                            ("guderian", CorpsOrder("pz", "advance", "rear"))))
    assert s.corps["inf"].location == "city"
    assert s.corps["pz"].location == "rear"


def test_a_relief_marching_in_lets_everyone_leave():
    relief = {"id": "relief", "name": "Relief", "side": "axis", "kind": "infantry",
              "location": "rear", "commander": "weichs"}
    s = _state(extra_corps=[relief])
    orders = _everyone_leaves()
    orders["weichs"] = CommanderOrders("weichs", [CorpsOrder("relief", "advance", "city")], "")
    resolve_turn(s, orders)
    assert s.corps["inf"].location == "rear"
    assert s.corps["relief"].location == "city"


def test_the_rule_holds_for_the_soviet_side_too():
    s = _state()
    for c in s.corps.values():
        c.side = "soviet"
    s.control.update({"rear": "soviet", "city": "soviet", "front": "axis"})
    s.supply_sources = {"soviet": ["rear"], "axis": ["front"]}
    resolve_turn(s, _everyone_leaves())
    assert s.corps["inf"].location == "city"


def test_a_held_corps_rests_like_any_corps_that_stood_still():
    s = _state()
    s.corps["inf"].organization = 50
    resolve_turn(s, _everyone_leaves())
    assert s.corps["inf"].organization > 50


# --- the commander hears about it, and so does the player -------------------------
#
# A countermanded order must reach the man whose order it was: in his war record
# (quoted in every persona prompt) and as a reason to speak up unprompted. Whether
# he protests is his character's business - nothing here tells him to.

from pathlib import Path  # noqa: E402

from commanders.campaign import Campaign  # noqa: E402
from commanders.communique import salient_events  # noqa: E402
from commanders.prompts import build_system_prompt  # noqa: E402
from commanders.records import update_track_records  # noqa: E402
from engine.turn import TurnReport  # noqa: E402

DATA_DIR = Path(__file__).parent.parent / "data"


def _held_report(campaign: Campaign) -> TurnReport:
    corps = campaign.state.corps["vii_ak"]  # Kluge's, starts at Siedlce
    corps.location = "minsk"
    return TurnReport(turn=3, movements=[
        {"corps": "vii_ak", "to": "minsk", "held_as_garrison": True, "ordered_to": "borisov"},
    ])


def test_the_countermand_goes_into_the_commanders_war_record():
    campaign = Campaign.new(DATA_DIR)
    update_track_records(campaign.state, _held_report(campaign), campaign.dossiers)
    record = campaign.dossiers["kluge"].track_record[-1]["summary"]
    assert "countermanded" in record
    assert "VII" in record and "Minsk" in record and "Borisov" in record
    assert record in build_system_prompt(campaign.dossiers["kluge"])


def test_the_countermand_gives_the_commander_something_to_say():
    campaign = Campaign.new(DATA_DIR)
    events = salient_events(campaign.state, _held_report(campaign), "axis")
    assert any("countermanded" in line and "Minsk" in line for line in events["kluge"])


def test_an_enemy_garrison_is_not_news_to_the_player():
    campaign = Campaign.new(DATA_DIR)
    report = TurnReport(turn=3, movements=[
        {"corps": "sov_4a", "to": "minsk", "held_as_garrison": True, "ordered_to": "borisov"},
    ])
    events = salient_events(campaign.state, report, "axis")
    assert not any("countermanded" in line for lines in events.values() for line in lines)
    assert not any("garrison" in f for f in campaign._staff_facts(report))


def test_the_staff_tells_the_player_whose_order_it_overrode():
    campaign = Campaign.new(DATA_DIR)
    facts = campaign._staff_facts(_held_report(campaign))
    line = next(f for f in facts if "garrison" in f)
    assert "Minsk" in line and "Borisov" in line and "Kluge" in line
