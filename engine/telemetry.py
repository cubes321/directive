"""Per-turn diagnostic telemetry: a structured record of a turn's battles and
the resulting board, for balance analysis. Pure over GameState/TurnReport —
the engine builds the data; a caller decides whether to write it to disk.
"""

from __future__ import annotations

from engine.state import GameState
from engine.turn import TurnReport


def unit_stats(state: GameState) -> list[dict]:
    """End-of-turn roster: every living corps, where it is and how it stands."""
    rows = []
    for corps in sorted(state.living_corps(), key=lambda c: (c.side, c.id)):
        region = state.game_map.regions.get(corps.location)
        rows.append(
            {
                "id": corps.id,
                "name": corps.name,
                "side": corps.side,
                "commander": corps.commander,
                "location": corps.location,
                "terrain": region.terrain if region else None,
                "kind": corps.kind,
                "strength": corps.strength,
                "organization": corps.organization,
                "supply": corps.supply,
            }
        )
    return rows


def build_turn_log(state: GameState, report: TurnReport) -> dict:
    """Combine the turn's battles (with combat-time participant detail already
    on the report) and the end-of-turn unit roster into one record."""
    return {
        "turn": report.turn,
        "weather": state.weather,
        "movements": report.movements,
        "combats": report.combats,
        "units": unit_stats(state),
    }
