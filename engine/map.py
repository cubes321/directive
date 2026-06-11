"""Named-location region graph: the game map.

Regions are nodes keyed by id; edges carry road quality ("highway", "minor",
"none") and whether a rail line runs along them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    terrain: str  # clear | forest | marsh | urban | river_line
    victory_points: int = 0


@dataclass(frozen=True)
class Edge:
    a: str
    b: str
    road: str  # highway | minor | none
    rail: bool


@dataclass
class GameMap:
    regions: dict[str, Region] = field(default_factory=dict)
    _edges: dict[frozenset[str], Edge] = field(default_factory=dict)
    _adjacency: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> GameMap:
        m = cls()
        for r in data["regions"]:
            region = Region(
                id=r["id"],
                name=r["name"],
                terrain=r["terrain"],
                victory_points=r.get("victory_points", 0),
            )
            m.regions[region.id] = region
            m._adjacency[region.id] = []
        for e in data["edges"]:
            a, b = e["between"]
            for end in (a, b):
                if end not in m.regions:
                    raise ValueError(f"edge references unknown region: {end}")
            edge = Edge(a=a, b=b, road=e["road"], rail=e["rail"])
            m._edges[frozenset((a, b))] = edge
            m._adjacency[a].append(b)
            m._adjacency[b].append(a)
        return m

    def neighbors(self, region_id: str) -> list[str]:
        return self._adjacency[region_id]

    def edge(self, a: str, b: str) -> Edge:
        return self._edges[frozenset((a, b))]
