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
FATIGUE_RISE = 2   # exhaustion sets in faster...
FATIGUE_FALL = 1   # ...than it lifts


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


def _fatigue_target(state: GameState, commander_id: str) -> int:
    """How worn this commander's formations actually are, 0-10.

    A formation is only as fresh as its most depleted resource, so each corps
    counts by ``min(organization, supply)``: full cohesion is worth little
    without fuel, and full depots are worth little to a broken corps.

    This replaces a counter that added 1 for moving-or-fighting and subtracted 1
    for resting. In an offensive nobody rests, so it ratcheted to the ceiling in
    lockstep and told you nothing about who was actually in trouble.
    """
    corps = [c for c in state.corps_for(commander_id) if not c.is_destroyed]
    if not corps:
        return 0
    condition = sum(min(c.organization, c.supply) for c in corps) / len(corps)
    return round((100 - condition) / 10)


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
    """Evolve every commander's dynamic (confidence/fatigue/relationship) from
    this turn's outcomes. Both sides are played by the model, so both sides
    feel their war - running this for the player's side alone left enemy
    dossiers pinned at their factory values for a whole campaign.

    ``relationship`` means standing with whoever this commander answers to: the
    player for his own commanders, their own high command for the enemy's. Only
    the former can be warmed by a SIGNAL, because only he has that channel.

    Psychological only - never touches the engine. Deterministic: the signalling
    roll is seeded and commanders are visited in id order."""
    rng = rng or random.Random(state.seed * 7907 + report.turn)
    conf: dict[str, int] = defaultdict(int)
    rel: dict[str, int] = defaultdict(int)
    for combat in report.combats:
        won = combat["outcome"] == "defender_retreated"
        # An encircled defender still standing is not a repulse: the ring is
        # being tightened. Scoring it as one had commanders lose confidence and
        # patience for winning, and the trapped defender gain them for dying.
        pocket = combat["outcome"] == "pocket_holding"
        for cid in combat["attackers"]:
            cmd = _commander_of(state, cid)
            if cmd is None:
                continue
            if won and combat["encircled"]:
                conf[cmd] += 2
                rel[cmd] += 1
            elif won or pocket:
                conf[cmd] += 1
                rel[cmd] += 1
            else:
                conf[cmd] -= 1   # repulsed: shaken, and men spent for nothing
                rel[cmd] -= 1
        for cid in combat["defenders"]:
            cmd = _commander_of(state, cid)
            if cmd is None:
                continue
            if pocket:
                conf[cmd] -= 1   # cut off and being reduced, not holding a line
            else:
                conf[cmd] += -2 if won else 1   # lost the position, or held it
            if won or pocket:
                # Losing ground your superior told you to hold costs standing
                # with him. Merely holding earns nothing: that was the job.
                rel[cmd] -= 1

    for cid in sorted(dossiers):
        dossier = dossiers[cid]
        dyn = dossier.dynamic
        dc = max(-CONF_CAP, min(CONF_CAP, conf.get(cid, 0)))
        dyn["confidence"] = _clamp(dyn.get("confidence", 5) + dc)

        target = _fatigue_target(state, cid)
        worn = dyn.get("fatigue", 0)
        if worn < target:
            worn = min(target, worn + FATIGUE_RISE)
        elif worn > target:
            worn = max(target, worn - FATIGUE_FALL)
        dyn["fatigue"] = _clamp(worn)

        dr = max(-REL_CAP, min(REL_CAP, rel.get(cid, 0)))
        # The warming roll models the player's personal attention, so it applies
        # only to commanders who can actually receive a SIGNAL from him.
        if dossier.side == player_side and _signalled_this_turn(state, cid, report.turn):
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
        pocket = combat["outcome"] == "pocket_holding"

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
            elif pocket:
                summary = (
                    f"Attacked {region}: the defenders are encircled with no line of "
                    f"retreat; the pocket is being reduced (their losses "
                    f"{combat['defender_losses']}, own {combat['attacker_losses']})."
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
            elif pocket:
                summary = (
                    f"Encircled at {region}: thrown back with no line of retreat, the "
                    f"pocket is being reduced (losses {combat['defender_losses']})."
                )
            else:
                summary = (
                    f"Defended {region}: held against attack "
                    f"(losses {combat['defender_losses']})."
                )
            dossiers[commander].add_record(report.turn, summary)
