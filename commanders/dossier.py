"""Commander dossiers: fixed personality + evolving war record.

Traits are 0-10 scales used to colour the system prompt. The track record is
an append-only log of summarized outcomes that feeds back into the prompt, so
commanders are shaped by their war. Dynamic state (confidence, fatigue,
relationship with the theater commander) shifts during the campaign.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Dossier:
    id: str
    name: str
    side: str
    role: str
    traits: dict[str, int]
    bio: str
    track_record: list[dict] = field(default_factory=list)
    dynamic: dict[str, int] = field(
        default_factory=lambda: {"confidence": 5, "fatigue": 0, "relationship": 5}
    )

    def add_record(self, turn: int, summary: str) -> None:
        self.track_record.append({"turn": turn, "summary": summary})

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "side": self.side,
            "role": self.role,
            "traits": dict(self.traits),
            "bio": self.bio,
            "track_record": list(self.track_record),
            "dynamic": dict(self.dynamic),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Dossier:
        return cls(
            id=data["id"],
            name=data["name"],
            side=data["side"],
            role=data["role"],
            traits=dict(data["traits"]),
            bio=data["bio"],
            track_record=list(data.get("track_record", [])),
            dynamic=dict(data.get("dynamic", {"confidence": 5, "fatigue": 0, "relationship": 5})),
        )


def load_dossiers(data_dir: Path) -> dict[str, Dossier]:
    raw = json.loads((data_dir / "commanders.json").read_text(encoding="utf-8"))
    return {d["id"]: Dossier.from_dict(d) for d in raw["commanders"]}
