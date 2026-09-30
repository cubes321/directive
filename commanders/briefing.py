"""Situation briefings: the fog-filtered text a commander reasons over.

Everything spatial is expressed in place names with machine-usable region ids
in brackets, because the order schema wants ids back. Staff options are
engine-computed legal moves the model may adopt or ignore - the "B + staff
net" architecture.
"""

from __future__ import annotations

from commanders.intel import format_intel_lines
from engine.fog import visible_enemy_contacts
from engine.movement import movement_points, reachable
from engine.state import GameState
from engine.turn import STACKING_LIMIT

MAX_OPTIONS_PER_CORPS = 3


def _region_label(state: GameState, region_id: str) -> str:
    return f"{state.game_map.regions[region_id].name} [id: {region_id}]"


def _is_full(state: GameState, region_id: str, side: str) -> bool:
    """A region already holding the stacking limit of friendly corps has no room
    for another this week - a move there would bounce."""
    return sum(
        1 for c in state.corps_at(region_id) if not c.is_destroyed and c.side == side
    ) >= STACKING_LIMIT


def _front_distances(state: GameState, side: str) -> dict[str, int]:
    """Hops from every region to the nearest enemy-held one: 0 is enemy ground,
    1 the front line, more is depth behind it. Empty when the enemy holds
    nothing, so there is no front to measure from."""
    enemy_held = [r for r, s in state.control.items() if s != side]
    return state.game_map.distances_from(enemy_held) if enemy_held else {}


def _depth_note(region_id: str, here: int | None, to_front: dict[str, int]) -> str:
    """Where a reachable region lies relative to the front, and - for friendly
    ground - whether going there takes this corps away from the enemy.

    Without this the range list was flat and alphabetical: a persona told to
    "bypass" the enemy picked a familiar name, and 9b Guderian drove back to
    Siedlce, Slutsk and Minsk while reporting a deep flanking move."""
    depth = to_front.get(region_id)
    if depth is None:
        return ""
    if depth == 0:
        return " (enemy-held)"
    # no commas: the range line itself is comma-separated
    where = "on the front line" if depth == 1 else f"{depth} regions behind the front"
    away = "; a move away from the enemy" if here is not None and depth > here else ""
    return f" (ours: {where}{away})"


def _range_label(state: GameState, region_id: str, side: str,
                 here: int | None = None, to_front: dict[str, int] | None = None) -> str:
    label = _region_label(state, region_id)
    if _is_full(state, region_id, side):
        label += " (FULL - no room)"
    return label + _depth_note(region_id, here, to_front or {})


def _corps_status(state: GameState, corps) -> str:
    notes = []
    if corps.supply < 40:
        notes.append("supply critical")
    elif corps.supply < 70:
        notes.append("supply strained")
    if corps.organization < 50:
        notes.append("badly disorganized")
    if corps.max_strength < 100:
        notes.append(f"cadre worn: can never be rebuilt past {corps.max_strength}")
    note = f" ({', '.join(notes)})" if notes else ""
    return (
        f"- {corps.name} [{corps.id}], {corps.kind}, at {_region_label(state, corps.location)}: "
        f"strength {corps.strength}/{corps.max_strength}, "
        f"organization {corps.organization}/100, "
        f"supply {corps.supply}/100{note}"
    )


def _contact_line(state: GameState, region_id: str, reports: list[dict]) -> str:
    units = ", ".join(
        f"{r['kind']} formation, around {r['estimated_strength']} strength" for r in reports
    )
    return f"- {_region_label(state, region_id)}: {units}"


def _closing_move(state: GameState, corps, in_range: dict[str, int]) -> str | None:
    """The reachable friendly region that gets this corps closest to the enemy.

    Without this, a corps whose every reachable region is already ours drew no
    move option at all - its staff could only say "hold current position", and
    it did, for turns on end. The bias got worse the more ground you took.
    """
    to_front = _front_distances(state, corps.side)
    here = to_front.get(corps.location)
    if here is None:
        return None
    closer = [
        r for r in sorted(in_range)
        if to_front.get(r, here) < here and not _is_full(state, r, corps.side)
    ]
    return min(closer, key=lambda r: (to_front[r], r)) if closer else None


def _staff_options(state: GameState, corps, contacts: dict[str, list[dict]]) -> list[str]:
    options: list[str] = []
    enemy_held = {r for r, side in state.control.items() if side != corps.side}
    in_range = reachable(
        state.game_map, corps.location, movement_points(corps, state.weather), blocked=enemy_held
    )
    # attacks on spotted enemies first, then forward moves into enemy ground
    for region_id in sorted(in_range, key=lambda r: (r not in contacts, in_range[r])):
        if len(options) >= MAX_OPTIONS_PER_CORPS - 1:
            break
        if region_id in contacts:
            options.append(
                f"attack {_region_label(state, region_id)} - defended by "
                + ", ".join(
                    f"~{r['estimated_strength']} strength {r['kind']}" for r in contacts[region_id]
                )
            )
        elif region_id in enemy_held:
            options.append(f"advance to {_region_label(state, region_id)} (no known enemy)")
    if not options:
        closing = _closing_move(state, corps, in_range)
        if closing:
            options.append(
                f"close up toward the front at {_region_label(state, closing)}"
            )
    if corps.supply < 70 or corps.organization < 70:
        options.append("hold in reserve to recover organization and supply")
    else:
        options.append("hold current position")
    return options


def build_briefing(state: GameState, commander: str) -> str:
    own = [c for c in state.corps_for(commander) if not c.is_destroyed]
    side = own[0].side if own else "axis"
    contacts = visible_enemy_contacts(state, side)
    directive = state.directives.get(
        commander, "No specific directive. Act according to the general situation."
    )

    lines: list[str] = []
    weather_note = {
        "mud": " The rasputitsa: roads are swamps, movement is halved and attacks flounder.",
        "snow": " Deep winter: movement is slow and unwinterized troops fight at a severe disadvantage.",
    }.get(state.weather, "")
    lines.append(f"SITUATION BRIEFING - {state.date.isoformat()} (turn {state.turn})")
    lines.append(f"Weather: {state.weather}.{weather_note}")
    lines.append("")
    lines.append("THEATER DIRECTIVE FROM YOUR COMMANDER:")
    lines.append(f'"{directive}"')
    lines.append("")
    recent_exchange = [
        line
        for line in state.conversations.get(commander, [])
        if line["turn"] >= state.turn - 1
    ][-6:]
    if recent_exchange:
        lines.append("RECENT EXCHANGES WITH YOUR COMMANDER-IN-CHIEF (weigh them in your decisions):")
        # dated, and his own pop-ups marked as such: undated, they read as live
        # and he kept re-arguing a city that had fallen weeks before
        for line in recent_exchange:
            if line["role"] == "player":
                speaker = "C-in-C"
            elif line.get("unprompted"):
                speaker = "you (unprompted signal)"
            else:
                speaker = "you"
            lines.append(f'  week {line["turn"]}, {speaker}: "{line["text"]}"')
        lines.append("")
    lines.append("YOUR FORCES:")
    for corps in own:
        lines.append(_corps_status(state, corps))
    lines.append("")
    lines.append("ENEMY CONTACTS (estimates from reconnaissance; there may be more):")
    if contacts:
        for region_id in sorted(contacts):
            lines.append(_contact_line(state, region_id, contacts[region_id]))
    else:
        lines.append("- No confirmed enemy contacts.")
    decrypt = state.intel.get(side)
    if decrypt:
        lines.append("")
        lines.append(
            "SIGNALS INTELLIGENCE (decrypt of last week's enemy traffic - "
            "believed accurate):"
        )
        lines.extend(format_intel_lines(state, decrypt))
    lines.append("")
    lines.append("STAFF OPTIONS (your staff's suggestions; you may order otherwise):")
    for corps in own:
        lines.append(f"For {corps.name} [{corps.id}]:")
        for option in _staff_options(state, corps, contacts):
            lines.append(f"  * {option}")
        enemy_held = {r for r, s in state.control.items() if s != corps.side}
        in_range = reachable(
            state.game_map, corps.location, movement_points(corps, state.weather), blocked=enemy_held
        )
        to_front = _front_distances(state, corps.side)
        here = to_front.get(corps.location)
        # front first: a list that opens with the rear invites a retreat
        by_depth = sorted(in_range, key=lambda r: (to_front.get(r, 0), r))
        lines.append(
            "  In range this week: "
            + (", ".join(_range_label(state, r, corps.side, here, to_front) for r in by_depth)
               or "(nowhere)")
        )
    return "\n".join(lines)
