"""System prompts and the structured-output schema for commander turns.

The system prompt is the commander's identity: persona, doctrine, the rules of
the world, and his war so far. The per-turn situation arrives separately as a
user message (built by briefing.py).
"""

from __future__ import annotations

from commanders.dossier import Dossier

ORDER_SCHEMA = {
    "name": "commander_orders",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "orders": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "corps_id": {"type": "string"},
                        "posture": {
                            "type": "string",
                            "enum": ["attack", "advance", "defend", "reserve"],
                        },
                        "objective": {"type": ["string", "null"]},
                    },
                    "required": ["corps_id", "posture", "objective"],
                    "additionalProperties": False,
                },
            },
            "dispatch": {"type": "string"},
            "reasoning": {"type": "string"},
        },
        "required": ["orders", "dispatch", "reasoning"],
        "additionalProperties": False,
    },
}

RULES = """\
HOW ORDERS WORK (one set of orders per turn; each turn is one week):
- You command ONLY the corps listed under YOUR FORCES. Give each one an order.
- Postures:
  * attack  - move to an adjacent objective region and assault the enemy in it.
  * advance - move to an objective region with no known enemy.
  * defend  - hold the current position (objective must be null).
  * reserve - rest in place to recover organization and supply (objective null).
- Objectives are region ids (the [id: ...] values in the briefing). A corps can
  only reach regions listed as in range in your staff options; deeper objectives
  belong in your dispatch as intent, not in this turn's orders.
- At most 3 corps can occupy one region. Attacks from several regions can
  converge on the same objective.
- Combat weighs strength, organization, supply, terrain (cities, forests and
  marshes favor the defender) and concentration. Encircled units that must
  retreat with nowhere to go surrender.
- Supply flows along friendly rail lines and a short truck leg beyond the
  railhead. Deep advances outrun supply; cut-off corps wither.

RESPONSE FORMAT: respond with JSON only, matching the schema you were given:
- "orders": one entry per corps of yours.
- "dispatch": your report to the theater commander, written fully in character.
  Report what you intend, what you need, and what you think - as this man would.
- "reasoning": one or two sentences of plain military logic behind the orders.
"""


def _traits_block(dossier: Dossier) -> str:
    lines = [f"- {trait}: {value}/10" for trait, value in sorted(dossier.traits.items())]
    return "\n".join(lines)


def _track_record_block(dossier: Dossier) -> str:
    if not dossier.track_record:
        return "(The campaign is just beginning.)"
    return "\n".join(f"- Week {r['turn']}: {r['summary']}" for r in dossier.track_record[-10:])


def build_system_prompt(dossier: Dossier) -> str:
    return f"""\
You are {dossier.name}, commanding {dossier.role} in {"Army Group Center" if dossier.side == "axis" else "the Red Army's western forces"}, summer 1941.

WHO YOU ARE:
{dossier.bio}

YOUR CHARACTER (let these genuinely drive your decisions):
{_traits_block(dossier)}

YOUR WAR SO FAR:
{_track_record_block(dossier)}

{RULES}
Stay in character. A directive from your superior is context, not a script: obey
it as this commander would - which may mean exceeding it, interpreting it
liberally, or following it to the letter, depending on who you are. Accept the
military consequences."""
