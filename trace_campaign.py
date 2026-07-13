"""Debug trace: watch the scripted campaign unfold turn by turn."""

from pathlib import Path

from commanders.scripted import scripted_orders
from engine.scenario import load_scenario
from engine.turn import resolve_turn

DATA_DIR = Path(__file__).parent / "data"

state = load_scenario(DATA_DIR)
for _ in range(24):
    orders = {}
    for cmd in ["guderian", "hoth", "kluge", "strauss", "weichs"]:
        orders[cmd] = scripted_orders(state, cmd, stance="advance", goal="moscow")
    for cmd in ["pavlov", "timoshenko", "konev", "zhukov"]:
        orders[cmd] = scripted_orders(state, cmd, stance="defend")
    report = resolve_turn(state, orders)

    axis_locs = sorted({c.location for c in state.living_corps() if c.side == "axis"})
    axis_str = sum(c.strength for c in state.corps.values() if c.side == "axis")
    sov_str = sum(c.strength for c in state.corps.values() if c.side == "soviet")
    sov_alive = sum(1 for c in state.living_corps() if c.side == "soviet")
    print(f"T{report.turn:2} axis@{','.join(axis_locs)} | str A:{axis_str} S:{sov_str} alive S:{sov_alive}")
    for c in report.combats:
        print(f"    combat {c['region']}: odds {c['odds']} -> {c['outcome']}"
              f" (A-{c['attacker_losses']}/D-{c['defender_losses']})"
              f"{' ENCIRCLED' if c['encircled'] else ''}")
