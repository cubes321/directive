"""Movement: movement-point budgets and Dijkstra reachability on the map graph.

Costs are paid per edge: a base cost from road quality plus a penalty from the
destination region's terrain. Enemy-held regions can be *entered* (that is an
attack) but never moved through.
"""

from __future__ import annotations

import heapq

from engine.map import GameMap
from engine.units import Corps

BASE_MP = {"panzer": 6, "motorized": 6, "infantry": 4}
ROAD_COST = {"highway": 2, "minor": 3, "none": 4}
TERRAIN_PENALTY = {"marsh": 2, "forest": 1}
LOW_SUPPLY_THRESHOLD = 25


def movement_points(corps: Corps) -> int:
    mp = BASE_MP[corps.kind]
    if corps.supply < LOW_SUPPLY_THRESHOLD:
        mp //= 2
    return mp


def move_cost(game_map: GameMap, src: str, dst: str) -> int:
    edge = game_map.edge(src, dst)
    terrain = game_map.regions[dst].terrain
    return ROAD_COST[edge.road] + TERRAIN_PENALTY.get(terrain, 0)


def reachable(
    game_map: GameMap,
    start: str,
    mp: int,
    blocked: set[str] | None = None,
) -> dict[str, int]:
    """Cheapest cost to every region reachable within ``mp``, excluding start.

    Regions in ``blocked`` may appear as destinations (attacks) but are never
    expanded through.
    """
    blocked = blocked or set()
    best: dict[str, int] = {start: 0}
    queue: list[tuple[int, str]] = [(0, start)]
    while queue:
        cost, here = heapq.heappop(queue)
        if cost > best.get(here, mp + 1) or (here in blocked and here != start):
            continue
        for nxt in game_map.neighbors(here):
            nxt_cost = cost + move_cost(game_map, here, nxt)
            if nxt_cost <= mp and nxt_cost < best.get(nxt, mp + 1):
                best[nxt] = nxt_cost
                heapq.heappush(queue, (nxt_cost, nxt))
    del best[start]
    return best
