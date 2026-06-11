"""Weather: the 1941 calendar that defeated an army group.

Weekly turns from 22 June. Clear summer until the end of September, the
October rasputitsa (mud), then the freeze from mid-November. Movement and
combat modifiers are consumed by movement.py and combat.py.
"""

from __future__ import annotations

MUD_FIRST_TURN = 16   # early October
SNOW_FIRST_TURN = 22  # mid November

# movement-point multipliers
MOVEMENT_FACTOR = {"clear": 1.0, "mud": 0.5, "snow": 0.75}

# combat-power multipliers per (weather, side); the axis lacks winter kit
COMBAT_FACTOR = {
    ("mud", "axis"): 0.6,
    ("mud", "soviet"): 0.75,
    ("snow", "axis"): 0.65,
    ("snow", "soviet"): 0.9,
}


def weather_for_turn(turn: int) -> str:
    if turn >= SNOW_FIRST_TURN:
        return "snow"
    if turn >= MUD_FIRST_TURN:
        return "mud"
    return "clear"


def combat_factor(weather: str, side: str) -> float:
    return COMBAT_FACTOR.get((weather, side), 1.0)
