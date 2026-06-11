"""Turn outcomes -> dossier track records.

Each combat is summarized once for the attacking commander and once for the
defending commander, in their own terms. These lines feed back into future
system prompts, so commanders remember their war.
"""

from __future__ import annotations

from commanders.dossier import Dossier
from engine.state import GameState
from engine.turn import TurnReport


def _commander_of(state: GameState, corps_id: str) -> str | None:
    corps = state.corps.get(corps_id)
    return corps.commander if corps else None


def update_track_records(
    state: GameState, report: TurnReport, dossiers: dict[str, Dossier]
) -> None:
    for combat in report.combats:
        region = state.game_map.regions[combat["region"]].name
        won = combat["outcome"] == "defender_retreated"

        for commander in {_commander_of(state, cid) for cid in combat["attackers"]}:
            if commander not in dossiers:
                continue
            if won and combat["encircled"]:
                summary = (
                    f"Attacked {region}: position carried, the defenders were "
                    f"encircled and destroyed."
                )
            elif won:
                summary = (
                    f"Attacked {region}: position carried, enemy thrown back "
                    f"(own losses {combat['attacker_losses']})."
                )
            else:
                summary = (
                    f"Attacked {region}: assault repulsed "
                    f"(own losses {combat['attacker_losses']})."
                )
            dossiers[commander].add_record(report.turn, summary)

        for commander in {_commander_of(state, cid) for cid in combat["defenders"]}:
            if commander not in dossiers:
                continue
            if won and combat["encircled"]:
                summary = f"Defended {region}: position overrun, formations encircled and lost."
            elif won:
                summary = (
                    f"Defended {region}: forced to retreat "
                    f"(losses {combat['defender_losses']})."
                )
            else:
                summary = (
                    f"Defended {region}: held against attack "
                    f"(losses {combat['defender_losses']})."
                )
            dossiers[commander].add_record(report.turn, summary)
