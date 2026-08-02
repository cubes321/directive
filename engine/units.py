"""Corps: the maneuver unit of the game.

All numbers are 0-100 scales. `strength` is manpower/equipment, `organization`
is cohesion (drops in combat, recovers at rest), `supply` is fuel/ammo state
set by the supply system each turn.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields

DESTROYED_THRESHOLD = 5
# A formation ground down can be rebuilt, but never to what it was: some of
# each loss is cadre - the officers and specialists that cannot be replaced by
# drafts. Derived from CUMULATIVE damage, never decremented per loss event,
# because _distribute_losses delivers combat damage one point at a time.
CADRE_LOSS_FRACTION = 0.25
MIN_CADRE = 40


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
    damage_taken: int = 0  # cumulative strength lost, ever

    @property
    def is_destroyed(self) -> bool:
        return self.strength < DESTROYED_THRESHOLD

    @property
    def max_strength(self) -> int:
        """The most this corps can ever be rebuilt to."""
        return max(MIN_CADRE, 100 - round(self.damage_taken * CADRE_LOSS_FRACTION))

    def take_losses(self, strength: int = 0, organization: int = 0) -> None:
        applied = min(self.strength, max(0, strength))
        self.strength -= applied
        self.damage_taken += applied
        self.organization = max(0, self.organization - organization)

    def recover(self, organization: int = 0, strength: int = 0) -> None:
        self.organization = min(100, self.organization + organization)
        self.strength = min(self.max_strength, self.strength + strength)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["max_strength"] = self.max_strength  # derived: for the UI and telemetry
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Corps:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
