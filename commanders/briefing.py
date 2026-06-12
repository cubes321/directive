"""Situation briefings: the fog-filtered text a commander reasons over.

Everything spatial is expressed in place names with machine-usable region ids
in brackets, because the order schema wants ids back. Staff options are
engine-computed legal moves the model may adopt or ignore - the "B + staff
net" architecture.
"""

from __future__ import annotations

from engine.fog import visible_enemy_contacts
from engine.movement import movement_points, reachable
from engine.state import GameState

MAX_OPTIONS_PER_CORPS = 3


def _region_label(state: GameState, region_id: str) -> str:
    return f"{state.game_map.regions[region_id].name} [id: {region_id}]"


def _corps_status(state: GameState, corps) -> str:
    notes = []
    if corps.supply < 40:
        notes.append("supply critical")
    elif corps.supply < 70:
        notes.append("supply strained")
    if corps.organization < 50:
        notes.append("badly disorganized")
    note = f" ({', '.join(notes)})" if notes else ""
    return (
        f"- {corps.name} [{corps.id}], {corps.kind}, at {_region_label(state, corps.location)}: "
        f"strength {corps.strength}/100, organization {corps.organization}/100, "
        f"supply {corps.supply}/100{note}"
    )


def _contact_line(state: GameState, region_id: str, reports: list[dict]) -> str:
    units = ", ".join(
        f"{r['kind']} formation, around {r['estimated_strength']} strength" for r in reports
    )
    return f"- {_region_label(state, region_id)}: {units}"


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
        for line in recent_exchange:
            speaker = "C-in-C" if line["role"] == "player" else "You"
            lines.append(f'  {speaker}: "{line["text"]}"')
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
        lines.append(
            "  In range this week: "
            + (", ".join(_region_label(state, r) for r in sorted(in_range)) or "(nowhere)")
        )
    return "\n".join(lines)
