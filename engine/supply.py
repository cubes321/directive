"""Supply: trace from sources through friendly territory.

Rail edges whose both ends are friendly carry supply for free; every other
edge is a truck leg. One truck leg from the railhead is free, each further leg
costs 25 supply. Corps that cannot trace at all are isolated and decay by 40
per turn toward zero.
"""

from __future__ import annotations

import heapq

from engine.map import GameMap
from engine.units import Corps

TRUCK_LEG_PENALTY = 25
FREE_TRUCK_LEGS = 1
CONNECTED_FLOOR = 20
ISOLATION_DECAY = 40


def _truck_legs_from_sources(
    game_map: GameMap, control: dict[str, str], side: str, sources: list[str]
) -> dict[str, int]:
    """Minimum truck legs to reach each friendly region from any source."""
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
            cost = 0 if edge.rail else 1
            if legs + cost < best.get(nxt, 1 << 30):
                best[nxt] = legs + cost
                heapq.heappush(queue, (legs + cost, nxt))
    return best


def compute_supply(
    game_map: GameMap,
    control: dict[str, str],
    sources: list[str],
    corps_list: list[Corps],
) -> dict[str, int]:
    """New supply value per corps id. Does not mutate the corps."""
    result: dict[str, int] = {}
    legs_by_side: dict[str, dict[str, int]] = {}
    for corps in corps_list:
        if corps.side not in legs_by_side:
            legs_by_side[corps.side] = _truck_legs_from_sources(
                game_map, control, corps.side, sources
            )
        legs = legs_by_side[corps.side].get(corps.location)
        if legs is None:
            result[corps.id] = max(0, corps.supply - ISOLATION_DECAY)
        else:
            penalty = TRUCK_LEG_PENALTY * max(0, legs - FREE_TRUCK_LEGS)
            result[corps.id] = max(CONNECTED_FLOOR, 100 - penalty)
    return result
