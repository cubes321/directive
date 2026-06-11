"""Combat resolution: pure functions, no mutation.

``resolve_combat`` computes losses and retreat from force ratios plus a seeded
random swing; ``turn.py`` is responsible for applying the result to units.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from engine.units import Corps

KIND_MULTIPLIER = {"panzer": 1.5, "motorized": 1.2, "infantry": 1.0}
TERRAIN_DEFENSE = {"urban": 1.5, "forest": 1.3, "marsh": 1.4, "river_line": 1.4, "clear": 1.0}
RETREAT_THRESHOLD = 1.3
BASE_LOSS = 8


@dataclass(frozen=True)
class CombatResult:
    odds: float  # attacker power / defender power, before random swing
    attacker_losses: int  # strength points, total across attacking corps
    defender_losses: int
    attacker_org_losses: int
    defender_org_losses: int
    defender_retreats: bool


def combat_power(corps: Corps) -> float:
    supply_factor = max(0.3, corps.supply / 100)
    experience_factor = 0.75 + corps.experience / 200
    return (
        corps.strength
        * (corps.organization / 100)
        * KIND_MULTIPLIER[corps.kind]
        * supply_factor
        * experience_factor
    )


def resolve_combat(
    attackers: list[Corps],
    defenders: list[Corps],
    terrain: str,
    rng: random.Random,
) -> CombatResult:
    attack = sum(combat_power(c) for c in attackers)
    defense = sum(combat_power(c) for c in defenders) * TERRAIN_DEFENSE.get(terrain, 1.0)
    odds = attack / max(defense, 1.0)
    effective = odds * rng.uniform(0.8, 1.2)

    attacker_losses = min(100, round(BASE_LOSS / max(effective, 0.4)))
    defender_losses = min(100, round(BASE_LOSS * effective))
    return CombatResult(
        odds=odds,
        attacker_losses=attacker_losses,
        defender_losses=defender_losses,
        attacker_org_losses=min(100, attacker_losses * 2),
        defender_org_losses=min(100, defender_losses * 2),
        defender_retreats=effective > RETREAT_THRESHOLD,
    )
