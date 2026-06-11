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
- A retreating defender loses at most half its current strength; annihilation
  only happens in an encirclement.
- Combat losses are distributed point by point round-robin so totals are
  conserved (no rounding away in large stacks).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from engine.combat import resolve_combat
from engine.orders import CommanderOrders
from engine.state import GameState
from engine.supply import compute_supply
from engine.units import Corps
from engine.weather import weather_for_turn

STACKING_LIMIT = 3
RESERVE_ORG_RECOVERY = 20
RESERVE_STR_RECOVERY = 5
REST_ORG_RECOVERY = 10


@dataclass
class TurnReport:
    turn: int
    movements: list[dict] = field(default_factory=list)
    combats: list[dict] = field(default_factory=list)


def _distribute_losses(corps_list: list[Corps], strength: int, organization: int) -> None:
    """Spread loss points one at a time so the totals are applied exactly."""
    alive = [c for c in corps_list]
    for i in range(strength):
        alive[i % len(alive)].take_losses(strength=1)
    for i in range(organization):
        alive[i % len(alive)].take_losses(organization=1)


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
        fought.update(c.id for c in attackers + defenders)

        _distribute_losses(attackers, result.attacker_losses, result.attacker_org_losses)

        if result.defender_retreats:
            org_share = result.defender_org_losses // len(defenders)
            for corps in defenders:
                retreat_to = _retreat_region(state, region, corps.side)
                if retreat_to is None:
                    corps.take_losses(strength=100, organization=100)  # surrenders
                else:
                    share = result.defender_losses // len(defenders)
                    corps.take_losses(
                        strength=min(share, corps.strength // 2),  # rout, not annihilation
                        organization=org_share,
                    )
                    corps.location = retreat_to
        else:
            _distribute_losses(defenders, result.defender_losses, result.defender_org_losses)

        defenders_gone = result.defender_retreats or all(c.is_destroyed for c in defenders)
        if defenders_gone:
            for corps in attackers:
                if not corps.is_destroyed and friendly_count(region, corps.side) < STACKING_LIMIT:
                    corps.location = region
            state.control[region] = attackers[0].side

        report.combats.append(
            {
                "region": region,
                "attackers": attacker_ids,
                "defenders": [c.id for c in defenders],
                "odds": round(result.odds, 2),
                "attacker_losses": result.attacker_losses,
                "defender_losses": result.defender_losses,
                "outcome": "defender_retreated" if defenders_gone else "defender_held",
                "encircled": result.defender_retreats
                and all(c.is_destroyed for c in defenders),
            }
        )

    # 3. Recovery for corps that neither moved nor fought
    moved = {m["corps"] for m in report.movements if not m.get("bounced")}
    for corps in state.living_corps():
        if corps.id in fought or corps.id in moved:
            continue
        if postures.get(corps.id) == "reserve":
            corps.recover(organization=RESERVE_ORG_RECOVERY, strength=RESERVE_STR_RECOVERY)
        else:
            corps.recover(organization=REST_ORG_RECOVERY)

    # 4. Supply tick, per side
    living = state.living_corps()
    for side, sources in state.supply_sources.items():
        side_corps = [c for c in living if c.side == side]
        for cid, value in compute_supply(state.game_map, state.control, sources, side_corps).items():
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
