from pathlib import Path

from commanders.scripted import scripted_orders
from engine.orders import validate_orders
from engine.scenario import load_scenario

DATA_DIR = Path(__file__).parent.parent / "data"


def test_advancer_orders_are_valid():
    s = load_scenario(DATA_DIR)
    orders = scripted_orders(s, "guderian", stance="advance", goal="moscow")
    assert validate_orders(orders, s.game_map, list(s.corps.values()), s.control) == []
    # panzer corps at brest should be heading somewhere, not sitting still
    assert any(o.posture in ("attack", "advance") for o in orders.orders)


def test_defender_holds_everything():
    s = load_scenario(DATA_DIR)
    orders = scripted_orders(s, "pavlov", stance="defend")
    assert validate_orders(orders, s.game_map, list(s.corps.values()), s.control) == []
    assert all(o.posture == "defend" for o in orders.orders)
    assert len(orders.orders) == 4  # pavlov's four armies


def test_advancer_rests_starved_corps():
    s = load_scenario(DATA_DIR)
    for c in s.corps_for("guderian"):
        c.supply = 10
    orders = scripted_orders(s, "guderian", stance="advance", goal="moscow")
    assert all(o.posture == "reserve" for o in orders.orders)
