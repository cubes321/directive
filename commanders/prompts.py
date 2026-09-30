"""System prompts and the structured-output schema for commander turns.

The system prompt is the commander's identity: persona, doctrine, the rules of
the world, and his war so far. The per-turn situation arrives separately as a
user message (built by briefing.py).
"""

from __future__ import annotations

from copy import deepcopy

from commanders.dossier import Dossier
from engine.orders import reach_options
from engine.state import GameState

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

def _legal_destinations(state: GameState, corps) -> list[str]:
    """Every objective ``validate_orders`` would accept from this corps on a
    moving posture: its reach set, plus staying where it is (``_order_errors``
    admits ``objective == corps.location``).

    Deliberately NOT ``briefing._staff_options``. Those are capped at
    MAX_OPTIONS_PER_CORPS and ordered for a human to read; a schema built from
    them would forbid orders the validator accepts, and every such order would
    cost a repair round-trip. ``reach_options`` is the validator's own set -
    the same call ``_order_errors`` makes to phrase its rejections.

    Sorted, because these bytes go into the request body and this codebase
    never lets set iteration order reach an output.
    """
    in_range, _ = reach_options(corps, state.game_map, state.control, state.weather)
    return sorted(set(in_range) | {corps.location})


def _corps_branches(state: GameState, corps) -> list[dict]:
    """The two shapes an order for this corps may take.

    Properties are generated in the order ``corps_id -> posture -> objective``,
    which is the whole trick: a constrained decoder picks the branch from what
    it has already emitted, so the model chooses its posture freely and only
    then is the objective conditioned on that choice. Reverse the order and the
    objective would decide the posture instead.
    """
    return [
        {
            "type": "object",
            "properties": {
                "corps_id": {"const": corps.id},
                "posture": {"type": "string", "enum": ["attack", "advance"]},
                # A corps with nothing in reach still gets this branch: the enum
                # is then just its own region, which the validator accepts. An
                # empty enum would be a branch nothing can satisfy.
                "objective": {"enum": _legal_destinations(state, corps)},
            },
            "required": ["corps_id", "posture", "objective"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "corps_id": {"const": corps.id},
                "posture": {"type": "string", "enum": ["defend", "reserve"]},
                "objective": {"const": None},
            },
            "required": ["corps_id", "posture", "objective"],
            "additionalProperties": False,
        },
    ]


def dynamic_order_schema(state: GameState, commander: str) -> dict:
    """The order schema for ONE commander's turn, built from the same state the
    briefing is built from.

    ORDER_SCHEMA is static and so can only say "objective is a string or null".
    Measured against this game's captured briefings, that leaves two constraints
    unexpressed - the objective's range, and "defend and reserve take no
    objective" - and they are the model's entire remaining non-compliance.
    Branching per corps expresses both, because the legal objectives are known
    at request time.

    This narrows what a conforming backend can emit; it does not replace
    ``validate_orders``. Enforcement is a *backend* property and LM Studio has
    been observed not enforcing (fences and renamed keys arrived despite
    ``strict: true``), so the validator remains the authority and the
    repair/salvage/fallback ladder stays exactly as it is.
    """
    own = sorted(
        (c for c in state.corps_for(commander) if not c.is_destroyed), key=lambda c: c.id
    )
    if not own:
        raise ValueError(
            f"{commander} has no living corps: there is nothing to order, and an "
            f"empty oneOf is a grammar that matches nothing"
        )
    # Deep-copied from the static schema so the envelope (name, strict, the
    # dispatch/reasoning properties, required, additionalProperties) has one
    # source of truth and cannot drift; only "orders" differs.
    schema = deepcopy(ORDER_SCHEMA)
    schema["schema"]["properties"]["orders"] = {
        "type": "array",
        "items": {"oneOf": [b for corps in own for b in _corps_branches(state, corps)]},
        # Coverage - each corps ordered exactly once - is not expressible here;
        # pinning the count plus validate_orders carries it.
        "minItems": len(own),
        "maxItems": len(own),
    }
    return schema


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
- "orders": one entry per corps of yours, each with exactly the keys
  "corps_id", "posture" and "objective".
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


def _current_state_block(dossier: Dossier) -> str:
    """Prose (never numbers) describing the commander's present morale, so his
    tone, aggression, and willingness to obey respond to how the campaign and
    the player have treated him. Only salient values speak up."""
    d = dossier.dynamic
    conf, fat, rel = d.get("confidence", 5), d.get("fatigue", 0), d.get("relationship", 5)
    lines: list[str] = []
    if conf >= 8:
        lines.append("You are riding high - recent successes leave you certain of your judgment.")
    elif conf <= 2:
        lines.append("Recent reverses have shaken you; you are second-guessing yourself.")
    if fat >= 7:
        lines.append("Your formations are exhausted, stretched past the point of endurance.")
    elif fat >= 4:
        lines.append("Your formations are worn: men tired, vehicles overdue, stocks thin.")
    # Same dial, opposite psychology. A German army commander who has lost
    # patience with headquarters starts freelancing; a Red Army commander out of
    # favour with Stavka in 1941 gets more compliant, not less - Pavlov was shot
    # that July. Low relationship is the insubordination lever on one side and
    # the desperation lever on the other.
    if dossier.side == "soviet":
        if rel >= 8:
            lines.append("You stand well with Stavka; your judgment is trusted there.")
        elif rel <= 2:
            lines.append("Stavka's patience with you is exhausted. Failure now will not be "
                         "forgiven. You will attack when ordered and report success, "
                         "whatever it costs.")
    elif rel >= 8:
        lines.append("You trust the theater commander; his intent and yours run together.")
    elif rel <= 2:
        lines.append("Your patience with headquarters is worn thin; you increasingly act on "
                     "your own judgment, whatever the directive says.")
    if not lines:
        lines.append("You are steady - neither elated nor discouraged.")
    return "\n".join(lines)


def build_persona_prompt(dossier: Dossier) -> str:
    """The commander's identity only — no order-format rules. Use this for
    conversational output (communiqués, signal chats); embedding the order
    RULES there biases the model toward emitting order-JSON instead of prose."""
    theater = "Army Group Center" if dossier.side == "axis" else "the Red Army's western forces"
    return f"""\
You are {dossier.name}, commanding {dossier.role} in {theater}, summer 1941.

WHO YOU ARE:
{dossier.bio}

YOUR CHARACTER (let these genuinely drive your decisions):
{_traits_block(dossier)}

YOUR WAR SO FAR:
{_track_record_block(dossier)}

YOUR CURRENT STATE:
{_current_state_block(dossier)}"""


def _addressee_block(dossier: Dossier) -> str:
    """Name the man reading the dispatch.

    "Your report to the theater commander" named no one, so the model invented a
    salutation each turn. The Red Army side converged on "Comrade <rank>" (that
    phrase is over-determined for 1941), while the German side had no anchor at
    all and scattered over nine forms - twice landing on "Comrade Field Marshal".
    Both sides also reported straight past the player to the head of state
    ("Mein Fuehrer", "Stalin!"), which is worse: the player IS the recipient.

    Invoking Hitler or Stalin in the body stays explicitly allowed - Zhukov
    raging at Stavka is the good kind of insubordination, and this block must
    not tune that away.
    """
    if dossier.side == "axis":
        return (
            "WHO IS READING YOUR DISPATCH: Generalfeldmarschall Fedor von Bock, "
            "commanding Army Group Center - your immediate superior. Address him "
            "as a German officer of 1941 addresses his army group commander. "
            "Speak of Berlin and the Fuehrer as you like, but you are not "
            "writing to them."
        )
    return (
        "WHO IS READING YOUR DISPATCH: the Stavka representative commanding your "
        "direction - your immediate superior. Address him as a Red Army officer "
        "of 1941 addresses his front commander. Speak of the Kremlin and Stalin "
        "as you like, but you are not writing to them."
    )


def build_system_prompt(dossier: Dossier) -> str:
    return f"""\
{build_persona_prompt(dossier)}

{_addressee_block(dossier)}

{RULES}
Stay in character. A directive from your superior is context, not a script: obey
it as this commander would - which may mean exceeding it, interpreting it
liberally, or following it to the letter, depending on who you are. Accept the
military consequences."""
