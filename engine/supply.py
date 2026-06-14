"""Supply: trace from sources through friendly territory, gated by the railhead.

Captured enemy rail is NOT usable until your railhead converts it (different
gauge — the historical Barbarossa bottleneck). Supply flows for free only over
*converted* rail; everything beyond — captured-but-unconverted rail, or roads —
is a truck leg, and each leg past the railhead costs supply. The railhead
converts a limited number of regions per turn (RAILHEAD_SPEED), so a fast
advance outruns its supply and a pause lets it catch up.

``compute_supply`` accepts an optional ``converted`` set; without it, all
friendly rail is treated as free (legacy behaviour, used by older tests).
"""

from __future__ import annotations

import heapq
from collections import deque

from engine.map import GameMap
from engine.units import Corps

TRUCK_LEG_PENALTY = 25
FREE_TRUCK_LEGS = 0  # every region beyond the converted railhead costs supply
CONNECTED_FLOOR = 20
ISOLATION_DECAY = 40

RAILHEAD_SPEED = 1  # regions the railhead converts per turn
PREWAR_RAILHEAD_DEPTH = 2  # rail depth assumed already converted at the rear
LOAD_LAG = 2  # how far behind the front the railhead sits when migrating a save


def _rail_depth(
    game_map: GameMap, control: dict[str, str], side: str, sources: list[str]
) -> dict[str, int]:
    """Rail-hop depth from any source, over friendly-held rail edges only."""
    depth = {s: 0 for s in sources if control.get(s) == side}
    queue = deque(depth)
    while queue:
        here = queue.popleft()
        for nxt in game_map.neighbors(here):
            if control.get(nxt) != side or nxt in depth:
                continue
            if game_map.edge(here, nxt).rail:
                depth[nxt] = depth[here] + 1
                queue.append(nxt)
    return depth


def initial_railhead(
    game_map: GameMap, control: dict[str, str], side: str, sources: list[str]
) -> set[str]:
    """The pre-war rail network: every friendly region rail-reachable from a
    source at scenario start (when only home territory is held)."""
    return set(_rail_depth(game_map, control, side, sources))


def default_railhead_on_load(
    game_map: GameMap, control: dict[str, str], side: str, sources: list[str]
) -> set[str]:
    """Reconstruct a plausible railhead for a save that predates this system:
    converted up to LOAD_LAG hops behind the deepest held rail."""
    depth = _rail_depth(game_map, control, side, sources)
    if not depth:
        return set()
    threshold = max(PREWAR_RAILHEAD_DEPTH, max(depth.values()) - LOAD_LAG)
    return {r for r, d in depth.items() if d <= threshold}


def advance_railhead(
    game_map: GameMap, control: dict[str, str], side: str,
    converted: set[str], speed: int,
) -> set[str]:
    """Convert up to ``speed`` more friendly-held regions, crawling outward
    along rail from the current railhead. Regions lost to the enemy fall out."""
    result = {r for r in converted if control.get(r) == side}
    added = 0
    # breadth-first along held rail from the existing railhead
    frontier = deque(result)
    while frontier and added < speed:
        here = frontier.popleft()
        for nxt in sorted(game_map.neighbors(here)):
            if added >= speed:
                break
            if nxt in result or control.get(nxt) != side:
                continue
            if game_map.edge(here, nxt).rail:
                result.add(nxt)
                frontier.append(nxt)
                added += 1
    return result


def _truck_legs_from_sources(
    game_map: GameMap, control: dict[str, str], side: str,
    sources: list[str], converted: set[str] | None,
) -> dict[str, int]:
    """Minimum truck legs to reach each friendly region. Movement between two
    converted rail-linked regions is free; everything else is one leg."""
    best: dict[str, int] = {}
    queue: list[tuple[int, str]] = []
    for s in sources:
        if control.get(s) == side:
            best[s] = 0
            heapq.heappush(queue, (0, s))
    while queue:
        legs, here = heapq.heappop(queue)
        if legs > best.get(here, 1 << 30):
            continue
        for nxt in game_map.neighbors(here):
            if control.get(nxt) != side:
                continue
            edge = game_map.edge(here, nxt)
            if converted is None:
                free = edge.rail
            else:
                free = edge.rail and here in converted and nxt in converted
            cost = 0 if free else 1
            if legs + cost < best.get(nxt, 1 << 30):
                best[nxt] = legs + cost
                heapq.heappush(queue, (legs + cost, nxt))
    return best


def compute_supply(
    game_map: GameMap,
    control: dict[str, str],
    sources: list[str],
    corps_list: list[Corps],
    converted: set[str] | None = None,
) -> dict[str, int]:
    """New supply value per corps id. Does not mutate the corps."""
    result: dict[str, int] = {}
    legs_by_side: dict[str, dict[str, int]] = {}
    for corps in corps_list:
        if corps.side not in legs_by_side:
            legs_by_side[corps.side] = _truck_legs_from_sources(
                game_map, control, corps.side, sources, converted
            )
        legs = legs_by_side[corps.side].get(corps.location)
        if legs is None:
            result[corps.id] = max(0, corps.supply - ISOLATION_DECAY)
        else:
            penalty = TRUCK_LEG_PENALTY * max(0, legs - FREE_TRUCK_LEGS)
            result[corps.id] = max(CONNECTED_FLOOR, 100 - penalty)
    return result
