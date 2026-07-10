"""Order schema and validation: the contract between commanders and the engine.

Validation returns human-readable error strings; the LLM layer quotes them back
to the model for one repair attempt before falling back to ``fallback_orders``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.map import GameMap
from engine.movement import movement_points, reachable
from engine.units import Corps

POSTURES = ("attack", "advance", "defend", "reserve")


@dataclass(frozen=True)
class CorpsOrder:
    corps_id: str
    posture: str  # attack | advance | defend | reserve
    objective: str | None  # region id; required for attack/advance


@dataclass(frozen=True)
class CommanderOrders:
    commander: str
    orders: tuple[CorpsOrder, ...]
    dispatch: str  # in-character report to the theater commander
    reasoning: str = ""

    def __init__(self, commander, orders, dispatch, reasoning=""):
        object.__setattr__(self, "commander", commander)
        object.__setattr__(self, "orders", tuple(orders))
        object.__setattr__(self, "dispatch", dispatch)
        object.__setattr__(self, "reasoning", reasoning)

    def to_dict(self) -> dict:
        return {
            "commander": self.commander,
            "orders": [
                {"corps_id": o.corps_id, "posture": o.posture, "objective": o.objective}
                for o in self.orders
            ],
            "dispatch": self.dispatch,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CommanderOrders:
        return cls(
            commander=data["commander"],
            orders=[CorpsOrder(**o) for o in data["orders"]],
            dispatch=data.get("dispatch", ""),
            reasoning=data.get("reasoning", ""),
        )


def _order_errors(
    order: CorpsOrder,
    commander: str,
    by_id: dict[str, Corps],
    game_map: GameMap,
    control: dict[str, str],
    weather: str = "clear",
) -> list[str]:
    corps = by_id.get(order.corps_id)
    if corps is None:
        return [f"unknown corps: {order.corps_id}"]
    if corps.commander != commander:
        return [f"{order.corps_id} is not under {commander}'s command"]
    if order.posture not in POSTURES:
        return [f"{order.corps_id}: unknown posture '{order.posture}' (use one of {POSTURES})"]
    if order.posture in ("attack", "advance"):
        if order.objective is None:
            return [f"{order.corps_id}: posture '{order.posture}' needs an objective"]
        if order.objective not in game_map.regions:
            return [f"{order.corps_id}: unknown region '{order.objective}'"]
        enemy_held = {r for r, side in control.items() if side != corps.side}
        in_range = reachable(
            game_map, corps.location, movement_points(corps, weather), blocked=enemy_held
        )
        if order.objective != corps.location and order.objective not in in_range:
            return [
                f"{order.corps_id}: objective '{order.objective}' is out of reach "
                f"this turn from {corps.location}"
            ]
    return []


def validate_orders(
    orders: CommanderOrders,
    game_map: GameMap,
    corps_list: list[Corps],
    control: dict[str, str],
    weather: str = "clear",
) -> list[str]:
    """Empty list means valid. Each error is phrased for an LLM repair prompt."""
    errors: list[str] = []
    by_id = {c.id: c for c in corps_list}
    own_living = {
        c.id for c in corps_list if c.commander == orders.commander and not c.is_destroyed
    }
    unordered = own_living - {o.corps_id for o in orders.orders}
    for corps_id in sorted(unordered):
        errors.append(f"no order given for {corps_id}; every corps needs an order")
    seen: set[str] = set()
    for corps_id in [o.corps_id for o in orders.orders]:
        if corps_id in seen:
            errors.append(
                f"{corps_id} was given more than one order; issue exactly one per corps"
            )
        seen.add(corps_id)
    for order in orders.orders:
        errors.extend(
            _order_errors(order, orders.commander, by_id, game_map, control, weather)
        )
    return errors


def salvage_orders(
    orders: CommanderOrders,
    game_map: GameMap,
    corps_list: list[Corps],
    control: dict[str, str],
    weather: str = "clear",
) -> CommanderOrders:
    """Best-effort repair: keep individually valid orders, defuse the rest to
    'defend', and fill in any corps that got no order. The dispatch survives,
    so a commander's voice isn't lost to one bad objective."""
    by_id = {c.id: c for c in corps_list}
    own_living = {
        c.id for c in corps_list if c.commander == orders.commander and not c.is_destroyed
    }
    salvaged: dict[str, CorpsOrder] = {}
    for order in orders.orders:
        if order.corps_id not in own_living or order.corps_id in salvaged:
            continue
        if _order_errors(order, orders.commander, by_id, game_map, control, weather):
            salvaged[order.corps_id] = CorpsOrder(order.corps_id, "defend", None)
        else:
            salvaged[order.corps_id] = order
    for corps_id in own_living - set(salvaged):
        salvaged[corps_id] = CorpsOrder(corps_id, "defend", None)
    return CommanderOrders(
        commander=orders.commander,
        orders=[salvaged[cid] for cid in sorted(salvaged)],
        dispatch=orders.dispatch,
        reasoning=orders.reasoning,
    )


def fallback_orders(commander: str, corps_list: list[Corps]) -> CommanderOrders:
    """Safe default when a commander fails to produce valid orders: hold in place."""
    own = [c for c in corps_list if c.commander == commander]
    return CommanderOrders(
        commander=commander,
        orders=[CorpsOrder(corps_id=c.id, posture="defend", objective=None) for c in own],
        dispatch="(No new orders received; formations holding their positions.)",
    )
