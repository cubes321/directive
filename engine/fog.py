"""Fog of war: what each side knows about the enemy.

Recon range is one region: enemy corps are spotted when they sit in a region
adjacent to (or shared with) a region containing friendly corps. Spotted
strength is reported in bands of 25, never exactly.
"""

from __future__ import annotations

from engine.state import GameState

ESTIMATE_BAND = 25


def _estimate(strength: int) -> int:
    return max(ESTIMATE_BAND, round(strength / ESTIMATE_BAND) * ESTIMATE_BAND)


def visible_enemy_contacts(state: GameState, side: str) -> dict[str, list[dict]]:
    """Region id -> contact reports visible to ``side`` this turn."""
    own_locations = {c.location for c in state.living_corps() if c.side == side}
    visible: set[str] = set(own_locations)
    for loc in own_locations:
        visible.update(state.game_map.neighbors(loc))

    contacts: dict[str, list[dict]] = {}
    for corps in state.living_corps():
        if corps.side == side or corps.location not in visible:
            continue
        contacts.setdefault(corps.location, []).append(
            {
                "kind": corps.kind,
                "estimated_strength": _estimate(corps.strength),
            }
        )
    return contacts
