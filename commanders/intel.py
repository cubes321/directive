"""Signals intelligence: whose orders got decrypted this week.

Pure and seeded, like commanders/communique.py — no LLM call and no IO. The
campaign layer decides what to do with the result; this module only picks.

WEGO simultaneity means a decrypt is always of LAST week's orders: briefings are
built before this turn's enemy orders exist. That is honest, and it is what
signals intelligence actually looked like — a step behind, but revealing of an
axis of effort, which persists.
"""

from __future__ import annotations

import random

from commanders.dossier import Dossier
from engine.state import GameState

INTEL_CHANCE = 0.25
CONTACT_MULTIPLIER = 4  # you intercept the sector you are facing


def _in_contact(state: GameState, commander: str, side: str) -> bool:
    """True when any of this commander's corps stands in or beside a region
    holding a living corps of ``side``."""
    own_regions = {
        c.location for c in state.corps_for(commander) if not c.is_destroyed
    }
    for region in sorted(own_regions):  # sorted: determinism
        near = [region, *sorted(state.game_map.neighbors(region))]
        for other in near:
            if any(c.side == side and not c.is_destroyed for c in state.corps_at(other)):
                return True
    return False


def intercept(
    state: GameState,
    dossiers: dict[str, Dossier],
    side: str,
    rng: random.Random,
    *,
    chance: float = INTEL_CHANCE,
) -> dict | None:
    """One roll: what ``side`` decrypted of its enemy's traffic last week.

    Returns the enemy commander's id, name, role and full order set, or None.
    Deterministic for a given rng.
    """
    if chance <= 0 or rng.random() >= chance:
        return None
    candidates = [
        cid
        for cid in sorted(state.last_orders)  # sorted: determinism
        if cid in dossiers
        and dossiers[cid].side != side
        and any(not c.is_destroyed for c in state.corps_for(cid))
    ]
    if not candidates:
        return None
    weights = [
        CONTACT_MULTIPLIER if _in_contact(state, cid, side) else 1 for cid in candidates
    ]
    cid = rng.choices(candidates, weights=weights, k=1)[0]
    return {
        "commander": cid,
        "name": dossiers[cid].name,
        "role": dossiers[cid].role,
        "orders": [dict(o) for o in state.last_orders[cid]["orders"]],
    }


def format_intel_lines(state: GameState, hit: dict) -> list[str]:
    """The decrypt body, one line per corps. Shared by the briefing block and
    the player's inbox card so the two can never drift apart."""
    lines = [f"  {hit['name']}, {hit['role']}:"]
    for order in hit["orders"]:
        corps = state.corps.get(order["corps_id"])
        who = corps.name if corps is not None else order["corps_id"]
        posture = order.get("posture")
        objective = order.get("objective")
        if posture in ("attack", "advance") and objective:
            region = state.game_map.regions.get(objective)
            where = f"{region.name} [id: {objective}]" if region else objective
            lines.append(f"    - {who}: {posture} {where}")
        elif posture == "reserve":
            lines.append(f"    - {who}: hold in reserve")
        else:
            lines.append(f"    - {who}: hold position")
    return lines
