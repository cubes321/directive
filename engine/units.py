"""Corps: the maneuver unit of the game.

All numbers are 0-100 scales. `strength` is manpower/equipment, `organization`
is cohesion (drops in combat, recovers at rest), `supply` is fuel/ammo state
set by the supply system each turn.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

DESTROYED_THRESHOLD = 5


@dataclass
class Corps:
    id: str
    name: str
    side: str  # axis | soviet
    kind: str  # panzer | motorized | infantry
    location: str  # region id
    commander: str  # commander id
    strength: int = 100
    organization: int = 100
    supply: int = 100
    experience: int = 50

    @property
    def is_destroyed(self) -> bool:
        return self.strength < DESTROYED_THRESHOLD

    def take_losses(self, strength: int = 0, organization: int = 0) -> None:
        self.strength = max(0, self.strength - strength)
        self.organization = max(0, self.organization - organization)

    def recover(self, organization: int = 0, strength: int = 0) -> None:
        self.organization = min(100, self.organization + organization)
        self.strength = min(100, self.strength + strength)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Corps:
        return cls(**data)
