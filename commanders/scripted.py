"""Scripted commanders: deterministic order generators.

Used as the headless test driver, the fallback opponent, and the baseline to
compare LLM commanders against. An "advance" commander pushes every corps one
step along the cheapest path to a goal region, spilling onto parallel routes
when the direct one is full; a "defend" commander holds.
"""

from __future__ import annotations

import heapq

from engine.map import GameMap
from engine.movement import move_cost, movement_points, reachable
from engine.orders import CommanderOrders, CorpsOrder
from engine.state import GameState
from engine.turn import STACKING_LIMIT

REST_SUPPLY_THRESHOLD = 30


def _distances_to(game_map: GameMap, goal: str) -> dict[str, int]:
    """Movement cost from every region to the goal, ignoring control."""
    dist = {goal: 0}
    queue = [(0, goal)]
    while queue:
        d, here = heapq.heappop(queue)
        if d > dist.get(here, 1 << 30):
            continue
        for n in game_map.neighbors(here):
            nd = d + move_cost(game_map, n, here)  # cost of travelling n -> here
            if nd < dist.get(n, 1 << 30):
                dist[n] = nd
                heapq.heappush(queue, (nd, n))
    return dist


def scripted_orders(
    state: GameState,
    commander: str,
    stance: str = "defend",
    goal: str | None = None,
) -> CommanderOrders:
    orders: list[CorpsOrder] = []
    dist = _distances_to(state.game_map, goal) if goal else {}
    planned_arrivals: dict[str, int] = {}

    for corps in state.corps_for(commander):
        if corps.is_destroyed:
            continue
        if stance != "advance" or goal is None or corps.location == goal:
            orders.append(CorpsOrder(corps.id, "defend", None))
            continue
        if corps.supply < REST_SUPPLY_THRESHOLD:
            orders.append(CorpsOrder(corps.id, "reserve", None))
            continue

        enemy_held = {r for r, side in state.control.items() if side != corps.side}
        in_range = reachable(
            state.game_map, corps.location, movement_points(corps, state.weather), blocked=enemy_held
        )
        candidates = sorted(
            (
                move_cost(state.game_map, corps.location, n) + dist.get(n, 1 << 30),
                n,
            )
            for n in state.game_map.neighbors(corps.location)
            if n in in_range and dist.get(n, 1 << 30) < dist.get(corps.location, 1 << 30)
        )
        step = None
        for _, n in candidates:
            if n in enemy_held:  # attacks don't occupy until won
                step = n
                break
            occupants = sum(
                1
                for c in state.corps_at(n)
                if not c.is_destroyed and c.side == corps.side
            )
            if occupants + planned_arrivals.get(n, 0) < STACKING_LIMIT:
                step = n
                break
        if step is None:
            orders.append(CorpsOrder(corps.id, "defend", None))
            continue
        if step in enemy_held:
            orders.append(CorpsOrder(corps.id, "attack", step))
        else:
            planned_arrivals[step] = planned_arrivals.get(step, 0) + 1
            orders.append(CorpsOrder(corps.id, "advance", step))

    return CommanderOrders(
        commander=commander,
        orders=orders,
        dispatch=f"({commander}: scripted {stance} orders.)",
    )
