"""WEGO turn resolution.

Order of operations each turn:
  1. Uncontested moves (both sides, deterministic corps-id order)
  2. Combats, grouped by target region
  3. Recovery for corps that neither moved nor fought
  3b. Marching wastage for every corps whose location changed
  4. Supply tick
  5. The Moscow clock
  6. Turn counter

Simultaneity is approximated: moves into regions without living enemy corps
happen first; everything else is a combat.

Key rules:
- At most STACKING_LIMIT corps per region. Moves that would overfill bounce;
  after a won combat only as many attackers advance as fit; retreats require
  room, and a defender with nowhere to go surrenders (encirclement).
- A retreating defender loses at most half its current strength. A defender with
  nowhere to go is encircled and takes POCKET_LOSS instead, so a full-strength
  formation needs three assaults to reduce and the other side has turns in which
  to attempt relief. Containing a pocket without assaulting it costs it nothing.
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
from engine.units import DESTROYED_THRESHOLD, Corps
from engine.weather import weather_for_turn

STACKING_LIMIT = 3
RESERVE_ORG_RECOVERY = 20
RESERVE_STR_RECOVERY = 5
REST_ORG_RECOVERY = 10
# Strength lost per assault by a corps caught in a pocket with no line of
# retreat. Sized so a full-strength formation takes three assaults to reduce -
# roughly the ten days Bialystok-Minsk held out - while an already-spent one
# collapses at the first push. A pocket that is merely contained and never
# assaulted takes nothing: masking a Kessel costs the encircling side time,
# which is the historical trade.
POCKET_LOSS = 34

# Marching wears an army out even where nobody is shooting: breakdowns,
# straggling, sick horses, boots. Staying inside your railhead costs nothing;
# every step of supply shortfall costs, and the weather multiplies it. This is
# what makes the campaign harder as it gets further from the rail net, rather
# than harder on a date in the calendar.
WASTAGE_SUPPLY_STEP = 25
WASTAGE_WEATHER = {"clear": 1.0, "mud": 2.0, "snow": 2.5}
# Crossing three regions in a bound is harder on an army than crossing one, so
# each region beyond the first adds this much again. It scales the shortfall
# cost rather than standing alone: a lunge inside your own railhead is still
# free, and only outrunning supply makes distance hurt.
LUNGE_PENALTY = 0.33
# How far from its depot a blocked reinforcement will detrain instead.
SPILL_RADIUS = 3


def march_wastage(corps: Corps, weather: str, hops: int = 1) -> int:
    """Strength a marching corps loses to non-combat wastage this turn."""
    shortfall = max(0, 100 - corps.supply)
    lunge = 1.0 + LUNGE_PENALTY * max(0, hops - 1)
    return round(
        shortfall / WASTAGE_SUPPLY_STEP * WASTAGE_WEATHER.get(weather, 1.0) * lunge
    )


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

    # Snapshot every corps' location before anything moves - including before
    # reinforcements spawn, so a corps arriving this turn is simply absent
    # from the snapshot rather than compared against its own arrival point.
    # Wastage is charged at step 3b to any living corps whose location has
    # since diverged from this snapshot, however it moved: uncontested march,
    # combat advance, or retreat. A corps missing from the snapshot (just
    # arrived) or whose location is unchanged (stayed put, or bounced) pays
    # nothing.
    locations_before_turn = {cid: c.location for cid, c in state.corps.items()}

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
            outcome = "defender_retreated"
        elif result.defender_retreats:
            # Routed, but with no line of retreat to take: a pocket. Distinct
            # from a repulse - the attacker is winning, just not finished. They
            # read identically before, so reducing a Kessel was reported to the
            # player (and written into the attacker's record) as a failed assault.
            outcome = "pocket_holding"
        else:
            outcome = "defender_held"

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
                "outcome": outcome,
                "encircled": result.defender_retreats
                and all(c.is_destroyed for c in defenders),
                "attacker_details": attacker_details,
                "defender_details": defender_details,
            }
        )

    # 3. Recovery for corps that neither moved nor fought
    moved = {
        m["corps"] for m in report.movements
        if not m.get("bounced") and not m.get("delayed")
    }
    for corps in state.living_corps():
        if corps.id in fought or corps.id in moved:
            continue
        if corps.supply < CONNECTED_FLOOR:
            continue  # refitting takes stores, not just rest: a cut-off corps rots
        if postures.get(corps.id) == "reserve":
            corps.recover(organization=RESERVE_ORG_RECOVERY, strength=RESERVE_STR_RECOVERY)
        else:
            corps.recover(organization=REST_ORG_RECOVERY)

    # 3b. Marching wastage. Charge every living corps whose location actually
    # changed this turn - uncontested moves, combat advances, and retreats
    # alike - against the snapshot taken before the turn began. A corps
    # absent from the snapshot just arrived and pays nothing; one whose
    # location is unchanged (stood still, or bounced off a full region) pays
    # nothing either.
    marched = {
        cid for cid, corps in state.corps.items()
        if not corps.is_destroyed
        and cid in locations_before_turn
        and corps.location != locations_before_turn[cid]
    }
    for corps_id in sorted(marched):
        corps = state.corps[corps_id]
        origin = locations_before_turn[corps_id]
        hops = state.game_map.distances_from([origin]).get(corps.location, 1)
        # Floored so wastage can never deliver the killing blow: step 2 already
        # wrote a combat report (outcome, encircled, defender_losses) assuming
        # this corps survived, and five downstream readers (the battle report,
        # _staff_facts, update_track_records, update_morale, the communiqué
        # trigger) trust that story. Wastage wears an army out, never finishes it.
        loss = min(
            march_wastage(corps, state.weather, hops), corps.strength - DESTROYED_THRESHOLD
        )
        if loss > 0:
            corps.take_losses(strength=loss, organization=loss * 2)

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

    # 5. The Moscow clock. A capital only counts when you can keep it.
    if state.control.get("moscow") == "axis":
        state.moscow_held_turns += 1
    else:
        state.moscow_held_turns = 0

    state.turn += 1
    return report


def _has_room(state: GameState, region_id: str, side: str) -> bool:
    """Friendly ground with space for another corps."""
    if state.control.get(region_id) != side:
        return False
    occupants = [c for c in state.corps_at(region_id) if not c.is_destroyed]
    return len(occupants) < STACKING_LIMIT


def _spill_region(state: GameState, scheduled: str, side: str) -> str | None:
    """Where a reinforcement detrains when it cannot detrain at its depot.

    An army that finds its railhead full or overrun gets off the train short of
    it; it does not wait in a siding for the rest of the war. Nearest friendly
    region with room, ties broken by id so the choice is deterministic.
    """
    hops = state.game_map.distances_from([scheduled])
    reachable_room = [
        r for r, distance in hops.items()
        if distance <= SPILL_RADIUS and _has_room(state, r, side)
    ]
    return min(reachable_room, key=lambda r: (hops[r], r)) if reachable_room else None


def _arrive_reinforcements(state: GameState, report: TurnReport) -> None:
    """Spawn scheduled corps at their railhead, or at the nearest friendly
    ground with room if the railhead is full or overrun. Only a corps with
    nowhere at all to detrain stays pending, and it says so."""
    still_pending = []
    for entry in state.reinforcements:
        corps_data = entry["corps"]
        side, location = corps_data["side"], corps_data["location"]
        due = entry["turn"] <= state.turn
        if not due:
            still_pending.append(entry)
            continue

        arrival = location if _has_room(state, location, side) else _spill_region(
            state, location, side
        )
        if arrival is not None:
            corps = Corps.from_dict({**corps_data, "location": arrival})
            state.corps[corps.id] = corps
            movement = {"corps": corps.id, "to": arrival, "arrived": True}
            if arrival != location:
                movement["diverted_from"] = location
            report.movements.append(movement)
        else:
            # Nowhere within reach is ours: the corps genuinely cannot detrain.
            # It never spawns and nothing else records that this turn happened
            # to it, so make the miss visible rather than silent.
            still_pending.append(entry)
            report.movements.append(
                {"corps": corps_data["id"], "to": location, "delayed": True}
            )
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
