"""Turn outcomes -> dossier track records.

Each combat is summarized once for the attacking commander and once for the
defending commander, in their own terms. These lines feed back into future
system prompts, so commanders remember their war.
"""

from __future__ import annotations

import random
from collections import defaultdict

from commanders.dossier import Dossier
from engine.state import GameState
from engine.turn import TurnReport

SIGNAL_BASE_CHANCE = 0.6
SIGNAL_EGO_WEIGHT = 0.05
SIGNAL_MIN_CHANCE = 0.05
SIGNAL_MAX_CHANCE = 0.9
CONF_CAP = 3   # max confidence swing per turn
REL_CAP = 2    # max relationship swing per turn, before the signal roll


def _commander_of(state: GameState, corps_id: str) -> str | None:
    corps = state.corps.get(corps_id)
    return corps.commander if corps else None


def _clamp(value: int) -> int:
    return max(0, min(10, value))


def _signal_warm_chance(ego: int) -> float:
    """Odds a SIGNAL warms a commander: the proud (high ego) rarely move to
    words alone; steadier commanders respond to attention."""
    return max(SIGNAL_MIN_CHANCE,
               min(SIGNAL_MAX_CHANCE, SIGNAL_BASE_CHANCE - SIGNAL_EGO_WEIGHT * ego))


def _signalled_this_turn(state: GameState, commander_id: str, turn: int) -> bool:
    return any(
        line.get("role") == "player" and line.get("turn") == turn
        for line in state.conversations.get(commander_id, [])
    )


def update_morale(
    state: GameState,
    report: TurnReport,
    dossiers: dict[str, Dossier],
    player_side: str,
    rng: random.Random | None = None,
    _force_roll: float | None = None,
) -> None:
    """Evolve each player-side commander's dynamic (confidence/fatigue/
    relationship) from this turn's outcomes and whether the player signalled
    him. Psychological only - never touches the engine. Deterministic: the
    signalling roll is seeded and commanders are visited in id order."""
    rng = rng or random.Random(state.seed * 7907 + report.turn)
    moved = {m["corps"] for m in report.movements
             if not m.get("bounced") and not m.get("arrived")}

    conf: dict[str, int] = defaultdict(int)
    rel: dict[str, int] = defaultdict(int)
    fought: set[str] = set()
    for combat in report.combats:
        won = combat["outcome"] == "defender_retreated"
        for cid in combat["attackers"]:
            cmd = _commander_of(state, cid)
            if cmd is None:
                continue
            fought.add(cmd)
            if won and combat["encircled"]:
                conf[cmd] += 2
                rel[cmd] += 1
            elif won:
                conf[cmd] += 1
                rel[cmd] += 1
            else:
                conf[cmd] -= 1   # repulsed: shaken, and men spent for nothing
                rel[cmd] -= 1
        for cid in combat["defenders"]:
            cmd = _commander_of(state, cid)
            if cmd is None:
                continue
            fought.add(cmd)
            conf[cmd] += -2 if won else 1   # lost the position, or held it

    for cid in sorted(dossiers):
        dossier = dossiers[cid]
        if dossier.side != player_side:
            continue
        dyn = dossier.dynamic
        dc = max(-CONF_CAP, min(CONF_CAP, conf.get(cid, 0)))
        dyn["confidence"] = _clamp(dyn.get("confidence", 5) + dc)

        commander_moved = any(_commander_of(state, x) == cid for x in moved)
        dyn["fatigue"] = _clamp(dyn.get("fatigue", 0) + (1 if (cid in fought or commander_moved) else -1))

        dr = max(-REL_CAP, min(REL_CAP, rel.get(cid, 0)))
        if _signalled_this_turn(state, cid, report.turn):
            chance = _signal_warm_chance(dossier.traits.get("ego", 5))
            roll = _force_roll if _force_roll is not None else rng.random()
            if roll < chance:
                dr += 1
        dyn["relationship"] = _clamp(dyn.get("relationship", 5) + dr)


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
