"""Per-turn battle and unit telemetry: enough detail to reconstruct why a
combat went the way it did (participant stats at combat time + power breakdown)
and where every unit ended the turn. Pure over GameState/TurnReport."""

from engine.combat import combat_power, power_breakdown
from engine.orders import CommanderOrders, CorpsOrder
from engine.state import GameState
from engine.telemetry import build_turn_log, unit_stats
from engine.turn import resolve_turn


def state_data():
    # west -- center -- east -- far_east (all highway+rail)
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
    return {commander: CommanderOrders(commander=commander, orders=list(corps_orders), dispatch="")}


def test_power_breakdown_explains_the_number():
    s = GameState.from_dict(state_data())
    c = s.corps["ax1"]
    c.supply = 25
    b = power_breakdown(c)
    assert b["id"] == "ax1"
    assert b["kind"] == "panzer"
    assert b["kind_multiplier"] == 1.5
    assert b["supply"] == 25
    assert abs(b["supply_factor"] - max(0.3, 25 / 100)) < 1e-9
    assert abs(b["power"] - combat_power(c)) < 1e-6


def test_unit_stats_lists_living_corps_with_location_and_stats():
    s = GameState.from_dict(state_data())
    rows = {r["id"]: r for r in unit_stats(s)}
    assert set(rows) == {"ax1", "ax2", "sv1"}
    assert rows["ax1"]["location"] == "west"
    assert rows["ax1"]["side"] == "axis"
    assert rows["ax1"]["commander"] == "guderian"
    assert rows["sv1"]["strength"] == 30
    assert "supply" in rows["ax1"] and "organization" in rows["ax1"]


def test_combat_report_carries_participant_details_at_combat_time():
    s = GameState.from_dict(state_data())
    resolve_turn(s, orders(CorpsOrder("ax1", "attack", "center"),
                           CorpsOrder("ax2", "attack", "center")))
    report = resolve_turn(s, orders(CorpsOrder("ax1", "attack", "east"),
                                    CorpsOrder("ax2", "attack", "east")))
    fight = next(c for c in report.combats if c["region"] == "east")
    assert fight["terrain"] == "clear"
    assert {d["id"] for d in fight["attacker_details"]} == {"ax1", "ax2"}
    assert {d["id"] for d in fight["defender_details"]} == {"sv1"}
    # pre-loss: the defender's recorded strength is its full pre-combat value
    assert fight["defender_details"][0]["strength"] == 30
    assert all("power" in d and "supply" in d for d in fight["attacker_details"])


def test_build_turn_log_combines_battles_and_unit_roster():
    s = GameState.from_dict(state_data())
    report = resolve_turn(s, orders(CorpsOrder("ax1", "advance", "center")))
    log = build_turn_log(s, report)
    assert log["turn"] == report.turn
    assert "weather" in log
    assert log["combats"] == report.combats
    assert log["movements"] == report.movements
    assert any(u["id"] == "ax1" for u in log["units"])
