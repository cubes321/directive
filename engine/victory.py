"""Victory conditions for the Army Group Center campaign.

Checked after each turn's resolution:
- Axis takes Moscow at any point: decisive axis victory.
- Axis army destroyed: decisive soviet victory.
- Otherwise, at the end of the final turn (early December), count objective
  points: a serious haul is a marginal axis win, anything less means the
  front held and the soviets win.
"""

from __future__ import annotations

from engine.state import GameState

FINAL_TURN = 24
MARGINAL_AXIS_VP = 18
COLLAPSE_FRACTION = 0.2  # of nominal (100/corps) strength


def _axis_vp(state: GameState) -> int:
    return sum(
        r.victory_points
        for r in state.game_map.regions.values()
        if state.control.get(r.id) == "axis"
    )


def check_victory(state: GameState) -> dict | None:
    if state.control.get("moscow") == "axis":
        return {
            "winner": "axis",
            "kind": "decisive",
            "reason": "Moscow has fallen. The Soviet state is decapitated.",
        }
    axis_corps = [c for c in state.corps.values() if c.side == "axis"]
    axis_strength = sum(c.strength for c in axis_corps)
    if axis_strength < COLLAPSE_FRACTION * 100 * len(axis_corps):
        return {
            "winner": "soviet",
            "kind": "decisive",
            "reason": "Army Group Center has been destroyed in the field.",
        }
    if state.turn > FINAL_TURN:
        vp = _axis_vp(state)
        if vp >= MARGINAL_AXIS_VP:
            return {
                "winner": "axis",
                "kind": "marginal",
                "reason": f"Winter ends the campaign with {vp} objective points in "
                          f"German hands - a deep but indecisive advance.",
            }
        return {
            "winner": "soviet",
            "kind": "marginal",
            "reason": f"The front held. {vp} objective points were not worth the blood.",
        }
    return None
