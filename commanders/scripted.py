"""Scripted commanders: deterministic order generators.

Used as the headless test driver, the fallback opponent, and the baseline to
compare LLM commanders against. An "advance" commander pushes every corps one
step along the cheapest path to a goal region, spilling onto parallel routes
when the direct one is full; a "defend" commander holds.

Two further stances exist for *tuning*, because plain "advance" is a poor model
of how the game is really played. Measured over a full campaign against
recorded LLM runs, it never makes a multi-hop bound (0 of 118 moves, against 31
of 108 for live commanders) and takes roughly a quarter of the combat damage.
A rules change can therefore look benign on an "advance" trace and be a rout in
play - which is exactly what happened once. So:

- ``blitz``     lunges as far as movement allows and never halts to resupply,
                bracketing the reckless end of real play.
- ``methodical`` steps one region at a time and rests whenever supply dips,
                bracketing the cautious end.

Tune against both. If a change is survivable for ``blitz`` and not trivial for
``methodical``, it is likely to sit sensibly for a real commander in between.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from engine.map import GameMap
from engine.movement import move_cost, movement_points, reachable
from engine.orders import CommanderOrders, CorpsOrder
from engine.state import GameState
from engine.turn import STACKING_LIMIT

REST_SUPPLY_THRESHOLD = 30


@dataclass(frozen=True)
class Stance:
    """How far a scripted commander reaches, and when he stops to resupply."""

    lunge: bool          # consider every region in range, not just neighbours
    rest_below: int      # go into reserve when supply drops under this


STANCES = {
    # the historical default - unchanged, so existing traces stay comparable
    "advance": Stance(lunge=False, rest_below=REST_SUPPLY_THRESHOLD),
    "blitz": Stance(lunge=True, rest_below=0),
    "methodical": Stance(lunge=False, rest_below=70),
}
ADVANCING = frozenset(STANCES)


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
    profile = STANCES.get(stance)

    for corps in state.corps_for(commander):
        if corps.is_destroyed:
            continue
        if profile is None or goal is None or corps.location == goal:
            orders.append(CorpsOrder(corps.id, "defend", None))
            continue
        if corps.supply < profile.rest_below:
            orders.append(CorpsOrder(corps.id, "reserve", None))
            continue

        enemy_held = {r for r, side in state.control.items() if side != corps.side}
        in_range = reachable(
            state.game_map, corps.location, movement_points(corps, state.weather), blocked=enemy_held
        )
        # A lunging commander will take any region he can reach this week; a
        # stepping one only ever considers the region next door.
        reach = in_range if profile.lunge else {
            n: move_cost(state.game_map, corps.location, n)
            for n in state.game_map.neighbors(corps.location)
            if n in in_range
        }
        forward = [
            (n, cost) for n, cost in reach.items()
            if dist.get(n, 1 << 30) < dist.get(corps.location, 1 << 30)
        ]
        if profile.lunge:
            # Deepest progress toward the goal wins. Sorting by total path cost
            # would not work here: it is near-constant along a shortest path, so
            # every reachable step ties and the tiebreak picks a name, not a bound.
            forward.sort(key=lambda item: (dist[item[0]], item[1], item[0]))
        else:
            forward.sort(key=lambda item: (item[1] + dist.get(item[0], 1 << 30), item[0]))
        candidates = [(cost, n) for n, cost in forward]
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
