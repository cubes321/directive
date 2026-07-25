"""WEGO turn resolution.

Order of operations each turn:
  1. Uncontested moves (both sides, deterministic corps-id order)
  2. Combats, grouped by target region
  3. Organization recovery for resting corps
  4. Supply tick
  5. Turn counter

Simultaneity is approximated: moves into regions without living enemy corps
happen first; everything else is a combat.

Key rules:
- At most STACKING_LIMIT corps per region. Moves that would overfill bounce;
  after a won combat only as many attackers advance as fit; retreats require
  room, and a defender with nowhere to go surrenders (encirclement).
- A retreating defender loses at most half its current strength. A defender with
  nowhere to go is encircled and takes POCKET_LOSS instead: a pocket is reduced
  over turns, so a full-strength formation survives the first blow and the other
  side has a turn in which to attempt relief.
- A region only changes hands when no living defender is still standing on it.
- Combat losses are distributed point by point round-robin so totals are
  conserved (no rounding away in large stacks).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from engine.combat import power_breakdown, resolve_combat
from engine.orders import CommanderOrders
from engine.state import GameState
from engine.supply import (
    CONNECTED_FLOOR,
    RAILHEAD_SPEED,
    advance_railhead,
    compute_supply,
    default_railhead_on_load,
)
from engine.units import Corps
from engine.weather import weather_for_turn

STACKING_LIMIT = 3
RESERVE_ORG_RECOVERY = 20
RESERVE_STR_RECOVERY = 5
REST_ORG_RECOVERY = 10
# Strength lost by a corps caught in a pocket with no line of retreat. Enough to
# wreck a full-strength formation and finish an already-spent one, so the ring
# still kills - but over turns, leaving room for a relief attempt.
POCKET_LOSS = 50


@dataclass
class TurnReport:
    turn: int
    movements: list[dict] = field(default_factory=list)
    combats: list[dict] = field(default_factory=list)


def _distribute_losses(
    corps_list: list[Corps], strength: int, organization: int
) -> tuple[int, int]:
    """Spread loss points one at a time, round-robin, skipping any corps already
    drained to zero so points are never absorbed by a destroyed corps (which
    would report more casualties than were actually applied). Returns the totals
    actually applied - never more than the force could absorb."""
    def _apply(amount: int, attr: str) -> int:
        applied = 0
        able = [c for c in corps_list if getattr(c, attr) > 0]
        while applied < amount and able:
            for corps in list(able):
                if applied >= amount:
                    break
                corps.take_losses(**{attr: 1})
                applied += 1
                if getattr(corps, attr) <= 0:
                    able.remove(corps)
        return applied

    return _apply(strength, "strength"), _apply(organization, "organization")


def resolve_turn(state: GameState, all_orders: dict[str, CommanderOrders]) -> TurnReport:
    report = TurnReport(turn=state.turn)
    state.weather = weather_for_turn(state.turn)
    rng = random.Random(state.seed * 1000 + state.turn)

    _arrive_reinforcements(state, report)

    postures: dict[str, str] = {}
    destinations: dict[str, str] = {}
    for orders in all_orders.values():
        for o in orders.orders:
            corps = state.corps.get(o.corps_id)
            if corps is None or corps.is_destroyed:
                continue
            postures[o.corps_id] = o.posture
            if o.posture in ("attack", "advance") and o.objective and o.objective != corps.location:
                destinations[o.corps_id] = o.objective

    def living_enemies_in(region: str, side: str) -> list[Corps]:
        return [c for c in state.corps_at(region) if not c.is_destroyed and c.side != side]

    def friendly_count(region: str, side: str) -> int:
        return sum(
            1 for c in state.corps_at(region) if not c.is_destroyed and c.side == side
        )

    # 1. Uncontested moves
    for corps_id in sorted(destinations):
        corps = state.corps[corps_id]
        dest = destinations[corps_id]
        if living_enemies_in(dest, corps.side):
            continue  # that's a combat, handled below
        if friendly_count(dest, corps.side) >= STACKING_LIMIT:
            report.movements.append({"corps": corps_id, "to": dest, "bounced": True})
        else:
            corps.location = dest
            state.control[dest] = corps.side
            report.movements.append({"corps": corps_id, "to": dest, "contested": False})
        del destinations[corps_id]

    # 2. Combats, grouped by target region
    fought: set[str] = set()
    by_target: dict[str, list[str]] = {}
    for corps_id, dest in sorted(destinations.items()):
        by_target.setdefault(dest, []).append(corps_id)

    for region, attacker_ids in sorted(by_target.items()):
        attackers = [state.corps[cid] for cid in attacker_ids]
        defenders = living_enemies_in(region, attackers[0].side)
        if not defenders:  # defenders vanished earlier this turn
            for corps in attackers:
                if friendly_count(region, corps.side) < STACKING_LIMIT:
                    corps.location = region
                    state.control[region] = corps.side
            continue
        terrain = state.game_map.regions[region].terrain
        result = resolve_combat(
            attackers, defenders, terrain=terrain, rng=rng, weather=state.weather
        )
        # Snapshot the fighters' power breakdown BEFORE losses are applied - this
        # is the only point the combat-time stats survive (telemetry).
        attacker_details = [power_breakdown(c) for c in attackers]
        defender_details = [power_breakdown(c) for c in defenders]
        fought.update(c.id for c in attackers + defenders)

        applied_attacker_losses, _ = _distribute_losses(
            attackers, result.attacker_losses, result.attacker_org_losses
        )

        applied_defender_losses = 0
        if result.defender_retreats:
            org_share = result.defender_org_losses // len(defenders)
            for corps in defenders:
                before = corps.strength
                retreat_to = _retreat_region(state, region, corps.side)
                if retreat_to is None:
                    # Encircled. This used to erase the corps outright at any
                    # strength, so a fresh formation went from untouched to gone
                    # in one resolution with no turn in which relief was possible.
                    # Reduce the pocket instead: heavy losses now, collapse later
                    # if the ring holds.
                    corps.take_losses(strength=POCKET_LOSS, organization=100)
                else:
                    share = result.defender_losses // len(defenders)
                    corps.take_losses(
                        strength=min(share, corps.strength // 2),  # rout, not annihilation
                        organization=org_share,
                    )
                    corps.location = retreat_to
                applied_defender_losses += before - corps.strength
        else:
            applied_defender_losses, _ = _distribute_losses(
                defenders, result.defender_losses, result.defender_org_losses
            )

        # Report what actually happened, not what was computed: a defender ordered
        # to retreat that had nowhere to go and survived is still sitting on the
        # ground. The region only changes hands once none of them are left on it.
        defenders_gone = not [
            c for c in defenders if not c.is_destroyed and c.location == region
        ]
        if defenders_gone:
            for corps in attackers:
                if not corps.is_destroyed and friendly_count(region, corps.side) < STACKING_LIMIT:
                    corps.location = region
            state.control[region] = attackers[0].side

        report.combats.append(
            {
                "region": region,
                "terrain": terrain,
                "attackers": attacker_ids,
                "defenders": [c.id for c in defenders],
                "odds": round(result.odds, 2),
                "attacker_losses": applied_attacker_losses,
                "defender_losses": applied_defender_losses,
                "outcome": "defender_retreated" if defenders_gone else "defender_held",
                "encircled": result.defender_retreats
                and all(c.is_destroyed for c in defenders),
                "attacker_details": attacker_details,
                "defender_details": defender_details,
            }
        )

    # 3. Recovery for corps that neither moved nor fought
    moved = {m["corps"] for m in report.movements if not m.get("bounced")}
    for corps in state.living_corps():
        if corps.id in fought or corps.id in moved:
            continue
        if corps.supply < CONNECTED_FLOOR:
            continue  # refitting takes stores, not just rest: a cut-off corps rots
        if postures.get(corps.id) == "reserve":
            corps.recover(organization=RESERVE_ORG_RECOVERY, strength=RESERVE_STR_RECOVERY)
        else:
            corps.recover(organization=REST_ORG_RECOVERY)

    # 4. Supply tick, per side: advance the railhead, then trace supply over it
    living = state.living_corps()
    for side, sources in state.supply_sources.items():
        if side in state.railheads:
            converted = set(state.railheads[side])
        else:  # a save predating the railhead system: reconstruct a fair lag
            converted = default_railhead_on_load(state.game_map, state.control, side, sources)
        converted = advance_railhead(
            state.game_map, state.control, side, converted, RAILHEAD_SPEED
        )
        state.railheads[side] = sorted(converted)
        side_corps = [c for c in living if c.side == side]
        for cid, value in compute_supply(
            state.game_map, state.control, sources, side_corps, converted
        ).items():
            state.corps[cid].supply = value

    state.turn += 1
    return report


def _arrive_reinforcements(state: GameState, report: TurnReport) -> None:
    """Spawn scheduled corps whose railhead is still friendly and has room;
    anything blocked stays pending and is retried next turn."""
    still_pending = []
    for entry in state.reinforcements:
        corps_data = entry["corps"]
        side, location = corps_data["side"], corps_data["location"]
        occupants = [c for c in state.corps_at(location) if not c.is_destroyed]
        arrivable = (
            entry["turn"] <= state.turn
            and state.control.get(location) == side
            and len(occupants) < STACKING_LIMIT
        )
        if arrivable:
            corps = Corps.from_dict(corps_data)
            state.corps[corps.id] = corps
            report.movements.append({"corps": corps.id, "to": location, "arrived": True})
        else:
            still_pending.append(entry)
    state.reinforcements = still_pending


def _retreat_region(state: GameState, region: str, side: str) -> str | None:
    """First friendly, enemy-free neighbor with room (alphabetical); None = encircled."""
    for neighbor in sorted(state.game_map.neighbors(region)):
        if state.control.get(neighbor) != side:
            continue
        occupants = [c for c in state.corps_at(neighbor) if not c.is_destroyed]
        if any(c.side != side for c in occupants):
            continue
        if len(occupants) >= STACKING_LIMIT:
            continue
        return neighbor
    return None
