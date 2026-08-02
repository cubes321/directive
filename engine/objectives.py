"""OKH objectives: timed demands that drive the campaign and put the player's
standing at stake.

Pure over GameState (control + turn), like the other engine modules — no LLM,
no political-capital knowledge. ``advance_objectives`` mutates the objective
statuses on the state and returns the events of this turn; the campaign layer
turns ``capital_delta`` into standing changes and OKH dispatches.

Objective lifecycle:
    scheduled --(issued_turn reached)--> active (capture) or pending (divert)
    active/accepted --(target taken)--> met
    met --(target lost, still inside the deadline)--> active/accepted, reward returned
    active/accepted --(deadline passed)--> failed
    pending --(deadline passed undecided)--> auto_declined

``met`` is only final once the deadline has passed with the target still held:
holding it *at the deadline* is what OKH asked for. Before then it is provisional,
so an objective cannot be banked by touching the place for one week. Either way,
giving up ground you had taken costs ``LOST_GROUND_PENALTY`` on top - losing a
place reads worse at OKH than never having reached it - so take-then-lose is
strictly worse than never taking it. After the deadline the achievement itself
still stands and the reward is never clawed back; only the smaller sting applies,
charged once.

The player's decision on a diversion (pending -> accepted | declined) is applied
by the campaign, not here.
"""

from __future__ import annotations

from engine.state import GameState

CLOSED = {"failed", "declined", "auto_declined"}
# Extra sting for giving up ground you had already taken, on top of handing back
# the reward. Losing a place you captured reads worse at OKH than never having
# got there, so take-then-lose must cost more than never taking it.
LOST_GROUND_PENALTY = 2


def _issue_text(obj: dict) -> str:
    if obj["kind"] == "divert":
        return (
            f"OKH: {obj['title']}. A diversion from the main axis — accept or "
            f"decline. (deadline week {obj['deadline_turn']})"
        )
    return f"OKH directive: {obj['title']} — to be achieved by week {obj['deadline_turn']}."


def issue_due_objectives(state: GameState) -> list[dict]:
    """Flip scheduled objectives to active/pending once their turn arrives.
    Run at game start and on load so newly-due objectives are visible and
    diversions are decidable before the turn is resolved. Idempotent."""
    events: list[dict] = []
    for obj in state.objectives:
        if obj["status"] == "scheduled" and state.turn >= obj["issued_turn"]:
            obj["status"] = "pending" if obj["kind"] == "divert" else "active"
            events.append(
                {"id": obj["id"], "type": "issued", "capital_delta": 0, "text": _issue_text(obj)}
            )
    return events


def advance_objectives(state: GameState, player_side: str) -> list[dict]:
    """Issue, complete and fail objectives for this turn. Returns events,
    each ``{id, type, capital_delta, text}``."""
    events = issue_due_objectives(state)
    for obj in state.objectives:
        if obj["status"] in CLOSED:
            continue

        if obj["status"] == "met":
            held = state.control.get(obj["target"]) == player_side
            if held:
                continue
            if state.turn <= obj["deadline_turn"]:
                # provisional: you have not delivered until the deadline
                obj["status"] = "accepted" if obj["kind"] == "divert" else "active"
                cost = obj["reward"] + LOST_GROUND_PENALTY
                events.append({
                    "id": obj["id"], "type": "reopened", "capital_delta": -cost,
                    "text": f"{obj['title']} — the objective has been lost again. OKH "
                            f"withdraws its approval and marks the ground given up "
                            f"(-{cost} standing).",
                })
            elif not obj.get("loss_reported"):
                obj["loss_reported"] = True
                events.append({
                    "id": obj["id"], "type": "lost",
                    "capital_delta": -LOST_GROUND_PENALTY,
                    "text": f"OKH notes with displeasure that "
                            f"{state.game_map.regions[obj['target']].name} has been lost "
                            f"after being secured. The objective stands achieved, but your "
                            f"rear is no longer your own (-{LOST_GROUND_PENALTY} standing).",
                })
            continue

        # resolve live objectives
        if obj["status"] in ("active", "accepted"):
            if state.control.get(obj["target"]) == player_side:
                obj["status"] = "met"
                events.append({
                    "id": obj["id"], "type": "met", "capital_delta": obj["reward"],
                    "text": f"Objective achieved — {obj['title']}. OKH is pleased "
                            f"(+{obj['reward']} standing).",
                })
            elif state.turn > obj["deadline_turn"]:
                obj["status"] = "failed"
                events.append({
                    "id": obj["id"], "type": "failed", "capital_delta": -obj["penalty"],
                    "text": f"Objective failed — {obj['title']}. OKH is displeased "
                            f"(-{obj['penalty']} standing).",
                })
        elif obj["status"] == "pending" and state.turn > obj["deadline_turn"]:
            penalty = obj.get("decline_penalty", 0)
            obj["status"] = "auto_declined"
            events.append({
                "id": obj["id"], "type": "auto_declined", "capital_delta": -penalty,
                "text": f"You let OKH's demand lapse — {obj['title']} "
                        f"(-{penalty} standing).",
            })
    return events
