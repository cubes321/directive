"""Unprompted commander communiqués: who speaks, and why.

Pure and seeded, like engine modules and commanders/intent.py — no LLM or IO.
The campaign layer turns a selected author into an actual message via the LLM.

A commander is more likely to volunteer a signal when something notable
happened to his corps this week (a victory, an encirclement, a repulse, lost
ground, a supply crisis) and when his temperament inclines him to speak up
(high ego / initiative). Both always matter.
"""

from __future__ import annotations

import random

from commanders.dossier import Dossier
from engine.state import GameState
from engine.turn import TurnReport

BASE_CHANCE = 0.34
MAX_PER_TURN = 1
SALIENT_CHANCE_BOOST = 0.3
MAX_CHANCE = 0.85
SALIENT_MULTIPLIER = 4  # a commander with notable news strongly favored to speak
SUPPLY_CRISIS = 40


def salient_events(
    state: GameState, report: TurnReport, player_side: str
) -> dict[str, list[str]]:
    """Per player-side commander, terse lines about notable events this week."""
    events: dict[str, list[str]] = {}

    def note(commander: str, line: str) -> None:
        events.setdefault(commander, []).append(line)

    for combat in report.combats:
        region = state.game_map.regions[combat["region"]]
        won = combat["outcome"] == "defender_retreated"
        is_vp = region.victory_points > 0
        for cid in combat["attackers"]:
            corps = state.corps.get(cid)
            if corps is None or corps.side != player_side:
                continue
            if won and combat["encircled"]:
                note(corps.commander, f"encircled and destroyed the enemy at {region.name}")
            elif won:
                note(corps.commander,
                     f"carried {region.name}" + (", a key objective" if is_vp else ""))
            else:
                note(corps.commander, f"was thrown back attacking {region.name}")
        for cid in combat["defenders"]:
            corps = state.corps.get(cid)
            if corps is None or corps.side != player_side:
                continue
            if won:  # defender retreated => player lost the position
                note(corps.commander, f"lost {region.name}")
            else:
                note(corps.commander, f"held {region.name} against attack")

    for corps in state.living_corps():
        if corps.side == player_side and corps.supply < SUPPLY_CRISIS:
            note(corps.commander, f"{corps.name} is in supply crisis ({corps.supply}/100)")

    return events


def select_communique_authors(
    state: GameState,
    dossiers: dict[str, Dossier],
    report: TurnReport,
    player_side: str,
    rng: random.Random,
    *,
    base_chance: float = BASE_CHANCE,
    max_count: int = MAX_PER_TURN,
) -> list[tuple[str, list[str]]]:
    """Decide which commanders, if any, volunteer a communiqué this turn.

    Returns (commander_id, salient_lines) pairs. Deterministic for a given rng.
    """
    active = [
        cid
        for cid in sorted(dossiers)
        if dossiers[cid].side == player_side
        and any(not c.is_destroyed for c in state.corps_for(cid))
    ]
    if not active or base_chance <= 0:
        return []

    events = salient_events(state, report, player_side)
    # A salient week raises the odds, but the boost is capped so the natural
    # rate never becomes a certainty; an explicit high base_chance (tests
    # forcing 1.0) is honored as-is.
    boosted = min(base_chance + SALIENT_CHANCE_BOOST, MAX_CHANCE) if events else base_chance
    chance = max(base_chance, boosted)
    if rng.random() >= chance:
        return []

    weights = []
    for cid in active:
        traits = dossiers[cid].traits
        # temperament sets the baseline; a salient week multiplies it, so the
        # commander with news usually speaks while a quiet braggart still might
        weight = 1 + traits.get("ego", 5) + traits.get("initiative", 5)
        if cid in events:
            weight *= SALIENT_MULTIPLIER
        weights.append(weight)

    chosen: list[tuple[str, list[str]]] = []
    pool = list(active)
    pool_weights = list(weights)
    for _ in range(min(max_count, len(pool))):
        pick = rng.choices(range(len(pool)), weights=pool_weights, k=1)[0]
        cid = pool.pop(pick)
        pool_weights.pop(pick)
        chosen.append((cid, events.get(cid, [])))
    return chosen
