"""GameState: the serializable single source of truth.

Everything the engine needs to resolve a turn lives here; everything the LLM
layer needs is derived from here (through fog filtering). Saves are plain JSON.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from engine.map import GameMap
from engine.units import Corps

CAMPAIGN_START = datetime.date(1941, 6, 22)
DAYS_PER_TURN = 7


@dataclass
class GameState:
    game_map: GameMap
    map_data: dict
    corps: dict[str, Corps]
    control: dict[str, str]  # region id -> side
    supply_sources: dict[str, list[str]]  # side -> region ids
    turn: int = 1
    seed: int = 0
    weather: str = "clear"
    directives: dict[str, str] = field(default_factory=dict)  # commander -> text
    dispatches: list[dict] = field(default_factory=list)  # {turn, commander, text}
    reinforcements: list[dict] = field(default_factory=list)  # {turn, corps: {...}}
    conversations: dict[str, list[dict]] = field(default_factory=dict)
    # commander -> [{turn, role: player|commander, text}]

    @property
    def date(self) -> datetime.date:
        return CAMPAIGN_START + datetime.timedelta(days=(self.turn - 1) * DAYS_PER_TURN)

    def corps_for(self, commander: str) -> list[Corps]:
        return [c for c in self.corps.values() if c.commander == commander]

    def corps_at(self, region_id: str) -> list[Corps]:
        return [c for c in self.corps.values() if c.location == region_id]

    def living_corps(self) -> list[Corps]:
        return [c for c in self.corps.values() if not c.is_destroyed]

    @classmethod
    def from_dict(cls, data: dict) -> GameState:
        return cls(
            game_map=GameMap.from_dict(data["map"]),
            map_data=data["map"],
            corps={c["id"]: Corps.from_dict(c) for c in data["corps"]},
            control=dict(data["control"]),
            supply_sources={k: list(v) for k, v in data["supply_sources"].items()},
            turn=data.get("turn", 1),
            seed=data.get("seed", 0),
            weather=data.get("weather", "clear"),
            directives=dict(data.get("directives", {})),
            dispatches=list(data.get("dispatches", [])),
            reinforcements=list(data.get("reinforcements", [])),
            conversations={k: list(v) for k, v in data.get("conversations", {}).items()},
        )

    def to_dict(self) -> dict:
        return {
            "map": self.map_data,
            "corps": [c.to_dict() for c in self.corps.values()],
            "control": dict(self.control),
            "supply_sources": {k: list(v) for k, v in self.supply_sources.items()},
            "turn": self.turn,
            "seed": self.seed,
            "weather": self.weather,
            "directives": dict(self.directives),
            "dispatches": list(self.dispatches),
            "reinforcements": list(self.reinforcements),
            "conversations": {k: list(v) for k, v in self.conversations.items()},
        }
