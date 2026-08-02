"""Replay a recorded campaign's orders against the engine.

The scripted policy in ``commanders/scripted.py`` is a poor stand-in for real
play: measured across a full campaign it never makes a multi-hop bound, never
counterattacks, and takes roughly a quarter of the combat damage an LLM game
does. Tuning against it misleads - a rules change that looked like a marginal
axis win on the scripted trace produced a rout in play.

This replays the actual decisions nine LLM commanders made in a recorded run,
so a rules change can be asked the sharper question: *holding every command
decision fixed, how would this real game have gone?* It costs no tokens and
runs in milliseconds.

**Fidelity caveat.** Once the rules change, the campaign diverges from the one
that was recorded, and a recorded order starts referring to a situation that no
longer exists. Those orders go through the same validate/salvage net the live
game uses, and the replay reports how many were salvaged each turn. Early turns
are faithful; a turn with a high salvage count is telling you the replay has
drifted, and its numbers should be read as indicative rather than exact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from engine.orders import CommanderOrders, salvage_orders, validate_orders
from engine.state import GameState
from engine.turn import TurnReport, resolve_turn


def load_recorded_orders(campaign_dir: Path) -> dict[int, dict[str, CommanderOrders]]:
    """Every commander's orders from a recorded run, keyed by turn then id.

    Reads the turn and commander from the file's contents rather than its name,
    and skips any log entry that carries no usable order block (a fallback turn,
    or a staff/conversation call logged alongside the orders).
    """
    by_turn: dict[int, dict[str, CommanderOrders]] = {}
    for path in sorted(Path(campaign_dir).glob("turn*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        block = entry.get("orders")
        if not block or not block.get("orders"):
            continue
        by_turn.setdefault(entry["turn"], {})[entry["commander"]] = (
            CommanderOrders.from_dict(block)
        )
    return by_turn


def _snapshot(state: GameState, turn: int, salvaged: int, report: TurnReport) -> dict:
    """The per-turn line a tuning pass wants, captured while it is true."""
    living = state.living_corps()
    axis = [c for c in living if c.side == "axis"]
    soviet = [c for c in living if c.side == "soviet"]
    return {
        "turn": turn,
        "axis": sum(c.strength for c in axis),
        "soviet": sum(c.strength for c in soviet),
        "axis_corps": len(axis),
        "salvaged": salvaged,
        "moscow": state.control.get("moscow"),
        "moscow_held_turns": state.moscow_held_turns,
        "min_ceiling": min((c.max_strength for c in axis), default=0),
        "combats": len(report.combats),
    }


@dataclass
class ReplayResult:
    turns: int = 0
    salvaged: dict[int, int] = field(default_factory=dict)  # turn -> orders repaired
    reports: list[TurnReport] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)  # per-turn, see _snapshot

    @property
    def fidelity(self) -> float:
        """Share of commander-turns replayed exactly as recorded, 0.0-1.0."""
        total = sum(len(r.movements) > -1 for r in self.reports)  # one per turn
        repaired = sum(self.salvaged.values())
        commander_turns = total * 9 or 1
        return max(0.0, 1.0 - repaired / commander_turns)


def replay(state: GameState, recorded: dict[int, dict[str, CommanderOrders]],
           turns: int | None = None) -> ReplayResult:
    """Play the recorded orders forward, repairing any that no longer fit."""
    result = ReplayResult()
    for turn in sorted(recorded):
        if turns is not None and result.turns >= turns:
            break
        corps_list = list(state.corps.values())
        for_turn: dict[str, CommanderOrders] = {}
        repaired = 0
        for cid, orders in sorted(recorded[turn].items()):
            problems = validate_orders(
                orders, state.game_map, corps_list, state.control, state.weather
            )
            if problems:
                orders = salvage_orders(
                    orders, state.game_map, corps_list, state.control, state.weather
                )
                repaired += 1
            for_turn[cid] = orders
        report = resolve_turn(state, for_turn)
        result.reports.append(report)
        result.salvaged[turn] = repaired
        result.history.append(_snapshot(state, turn, repaired, report))
        result.turns += 1
    return result
