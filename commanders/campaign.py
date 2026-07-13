"""Campaign: the stateful game session.

Owns the GameState, the dossiers (including the bench of unemployed
commanders), the player's political capital, and the turn cycle:

    player directives -> Stavka directives for the AI side ->
    gather orders (every active commander is an LLM agent) ->
    WEGO resolution -> track records -> dispatches for the inbox.

With no client attached, all commanders fall back to scripted policies, which
keeps the whole campaign playable headlessly in tests.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from commanders.briefing import build_briefing
from commanders.communique import (
    BASE_CHANCE,
    MAX_PER_TURN,
    select_communique_authors,
)
from commanders.dossier import Dossier, load_dossiers
from commanders.intent import soviet_directives
from commanders.llm import LMStudioClient
from commanders.orchestrator import gather_orders
from commanders.prompts import build_persona_prompt
from commanders.records import update_morale, update_track_records
from commanders.scripted import scripted_orders
from engine.objectives import advance_objectives, issue_due_objectives
from engine.scenario import load_scenario
from engine.state import GameState
from engine.telemetry import build_turn_log
from engine.turn import TurnReport, resolve_turn
from engine.victory import check_victory
from engine.weather import weather_for_turn

STARTING_POLITICAL_CAPITAL = 10
DISMISSAL_BASE_COST = 2
BENCH_ROLE = "(awaiting command)"


def prose_from_reply(text: str) -> str:
    """Conversational calls want prose, but a local model primed on the order
    schema can still lapse into order-JSON. If so, recover the human-facing
    line; otherwise return the text unchanged."""
    stripped = text.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return text
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return text
    if not isinstance(data, dict):
        return text
    for key in ("signal", "dispatch", "message", "communique"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return text


@dataclass
class TurnResult:
    report: TurnReport
    dispatches: list[dict]
    victory: dict | None = None
    communiques: list[dict] = field(default_factory=list)
    okh_events: list[dict] = field(default_factory=list)


RELIEVED_VERDICT = {
    "winner": "soviet",
    "kind": "relieved",
    "reason": "OKH has lost confidence in you. You are relieved of command.",
}


@dataclass
class Campaign:
    state: GameState
    dossiers: dict[str, Dossier]
    client: LMStudioClient | None = None
    player_side: str = "axis"
    political_capital: int = STARTING_POLITICAL_CAPITAL
    communique_chance: float = BASE_CHANCE
    # When set, a per-turn battle/unit telemetry file is written here each turn
    # (for balance analysis). None = off, so tests and headless runs opt in.
    turn_log_dir: Path | None = None

    @classmethod
    def new(cls, data_dir: Path, client: LMStudioClient | None = None,
            turn_log_dir: Path | None = None) -> Campaign:
        campaign = cls(
            state=load_scenario(data_dir),
            dossiers=load_dossiers(data_dir),
            client=client,
            turn_log_dir=turn_log_dir,
        )
        campaign.refresh_objectives()  # OKH's opening directive greets the player
        return campaign

    def refresh_objectives(self) -> list[dict]:
        """Issue any objectives now due (game start, on load) and post their
        OKH dispatches, so they are visible and decidable before the turn runs."""
        events = issue_due_objectives(self.state)
        for event in events:
            self.political_capital += event["capital_delta"]  # 0 for an issue
            self.state.dispatches.append(
                {"turn": self.state.turn, "commander": "okh", "text": event["text"]}
            )
        return events

    def active_commanders(self, side: str | None = None) -> list[str]:
        active = []
        for cid, dossier in self.dossiers.items():
            if side and dossier.side != side:
                continue
            if any(not c.is_destroyed for c in self.state.corps_for(cid)):
                active.append(cid)
        return sorted(active)

    def benched_commanders(self, side: str) -> list[str]:
        return sorted(
            cid
            for cid, d in self.dossiers.items()
            if d.side == side and not self.state.corps_for(cid)
        )

    def current_verdict(self) -> dict | None:
        """Campaign-level outcome: the OKH survival meter overrides the
        military verdict, so running out of standing ends the game."""
        if self.political_capital <= 0:
            return dict(RELIEVED_VERDICT)
        return check_victory(self.state)

    def decide_diversion(self, objective_id: str, accept: bool) -> dict:
        """Resolve a pending OKH diversion: accept it (it becomes a live
        objective) or decline it (immediate hit to standing)."""
        obj = next((o for o in self.state.objectives if o["id"] == objective_id), None)
        if obj is None:
            raise ValueError(f"unknown objective: {objective_id}")
        if obj["kind"] != "divert" or obj["status"] != "pending":
            raise ValueError(f"{objective_id} has no pending decision")
        if accept:
            obj["status"] = "accepted"
            return {"accepted": True, "cost": 0}
        obj["status"] = "declined"
        cost = obj.get("decline_penalty", 0)
        self.political_capital -= cost
        return {"accepted": False, "cost": cost}

    async def play_turn(self, player_directives: dict[str, str]) -> TurnResult:
        if self.current_verdict() is not None:
            raise ValueError("the campaign is over")
        # Set this turn's weather BEFORE briefings so orders are planned and
        # validated on the same conditions resolution will use (resolve_turn
        # recomputes the identical value). Otherwise a transition turn (mud at
        # 16, snow at 22) briefs on last week's weather.
        self.state.weather = weather_for_turn(self.state.turn)
        self.state.directives.update(player_directives)
        self.state.directives.update(soviet_directives(self.state))

        active = self.active_commanders()
        if self.client is not None:
            all_orders = await gather_orders(
                self.state, self.dossiers, self.client,
                llm_commanders=set(active), scripted={},
            )
        else:
            all_orders = {
                cid: scripted_orders(
                    self.state, cid,
                    stance="advance" if self.dossiers[cid].side == self.player_side else "defend",
                    goal="moscow" if self.dossiers[cid].side == self.player_side else None,
                )
                for cid in active
            }

        dispatches = [
            {"turn": self.state.turn, "commander": cid, "text": orders.dispatch}
            for cid, orders in sorted(all_orders.items())
        ]
        self.state.dispatches.extend(dispatches)

        report = resolve_turn(self.state, all_orders)
        update_track_records(self.state, report, self.dossiers)
        update_morale(self.state, report, self.dossiers, self.player_side)
        self._write_turn_log(report)

        staff_dispatch = {
            "turn": report.turn,
            "commander": "staff",
            "text": await self._staff_report(report),
        }
        self.state.dispatches.append(staff_dispatch)
        dispatches.append(staff_dispatch)

        okh_events = advance_objectives(self.state, self.player_side)
        for event in okh_events:
            self.political_capital += event["capital_delta"]
            okh_dispatch = {"turn": report.turn, "commander": "okh", "text": event["text"]}
            self.state.dispatches.append(okh_dispatch)
            dispatches.append(okh_dispatch)

        communiques = await self._communiques(report)

        return TurnResult(
            report=report,
            dispatches=dispatches,
            victory=self.current_verdict(),
            communiques=communiques,
            okh_events=okh_events,
        )

    def _write_turn_log(self, report: TurnReport) -> None:
        """Dump this turn's battle + unit telemetry for balance analysis."""
        if self.turn_log_dir is None:
            return
        self.turn_log_dir.mkdir(parents=True, exist_ok=True)
        path = self.turn_log_dir / f"turn{report.turn:02d}.json"
        path.write_text(
            json.dumps(build_turn_log(self.state, report), indent=2), encoding="utf-8"
        )

    async def _communiques(self, report: TurnReport) -> list[dict]:
        """Occasionally, a commander volunteers an unsolicited signal. Stored as
        an unprompted line in his conversation thread (so the player can reply
        and it colours his next briefing) and surfaced for the turn-start pop-up."""
        rng = random.Random(self.state.seed * 7919 + self.state.turn)
        authors = select_communique_authors(
            self.state, self.dossiers, report, self.player_side, rng,
            base_chance=self.communique_chance, max_count=MAX_PER_TURN,
        )
        out: list[dict] = []
        for cid, salient in authors:
            text = await self._one_communique(cid, salient)
            if not text:
                continue
            self.state.conversations.setdefault(cid, []).append(
                {"turn": self.state.turn, "role": "commander", "text": text, "unprompted": True}
            )
            out.append({"commander": cid, "name": self.dossiers[cid].name, "text": text})
        return out

    async def _one_communique(self, commander_id: str, salient: list[str]) -> str:
        dossier = self.dossiers[commander_id]
        situation = "; ".join(salient) if salient else "no single event stands out"
        if self.client is None:
            return f"({dossier.name} signals unprompted: {situation}.)"
        system = (
            build_persona_prompt(dossier)
            + "\n\nYou are sending an UNSOLICITED signal to your theater commander "
            "- he did not ask. Say what is on your mind as this man would: a "
            "warning, a request, a boast, a complaint, or a suggestion. Reply with "
            "the message only - plain prose, no JSON, under 120 words, in "
            "character.\n\nWHAT PROMPTS YOU NOW: "
            + situation
            + "\n\nYOUR CURRENT SITUATION:\n"
            + build_briefing(self.state, commander_id)
        )
        thread = self.state.conversations.get(commander_id, [])
        messages = [{"role": "system", "content": system}]
        for line in thread[-6:]:
            role = "user" if line["role"] == "player" else "assistant"
            messages.append({"role": role, "content": line["text"]})
        messages.append(
            {"role": "user", "content": "Send your unprompted signal now, in your own words."}
        )
        return prose_from_reply(await self.client.request_text(messages, role=commander_id))

    def _staff_facts(self, report: TurnReport) -> list[str]:
        """Player-side view of the week, as terse factual lines."""
        facts: list[str] = []
        for c in report.combats:
            region = self.state.game_map.regions[c["region"]].name
            we_attacked = self.state.corps[c["attackers"][0]].side == self.player_side
            won = c["outcome"] == "defender_retreated"
            if we_attacked:
                verdict = "position carried" if won else "assault repulsed"
                own_losses, enemy_losses = c["attacker_losses"], c["defender_losses"]
            else:
                verdict = "position lost" if won else "attack beaten off"
                own_losses, enemy_losses = c["defender_losses"], c["attacker_losses"]
            line = (
                f"{region}: {'our attack' if we_attacked else 'enemy attack'}, "
                f"{verdict} (our losses {own_losses}, theirs est. {enemy_losses})"
            )
            if c["encircled"]:
                line += "; the defenders were encircled and destroyed"
            facts.append(line)
        if not facts:
            facts.append("No major engagements this week.")
        starved = [
            c.name for c in self.state.living_corps()
            if c.side == self.player_side and c.supply < 40
        ]
        if starved:
            facts.append("Supply critical for: " + ", ".join(starved))
        if self.state.weather != "clear":
            facts.append(f"Weather: {self.state.weather}.")
        return facts

    async def _staff_report(self, report: TurnReport) -> str:
        facts = self._staff_facts(report)
        if self.client is not None:
            system = (
                "You are Generalmajor Hans von Greiffenberg, chief of staff of "
                "Army Group Center, summer 1941. Write the weekly staff assessment "
                "for Field Marshal von Bock: dry, precise, professional, under 180 "
                "words, plain text. State what happened, what it cost, what worries "
                "the staff, and one recommendation. No flattery."
            )
            user = "Events of the week:\n- " + "\n- ".join(facts)
            reply = await self.client.request_text(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                role="staff",
            )
            if reply:
                return reply
        return "Weekly staff assessment:\n- " + "\n- ".join(facts)

    async def converse(self, commander_id: str, message: str) -> str:
        """A signal exchange with one of your commanders. The thread persists
        and recent lines are quoted in his next briefing - conversations are a
        real channel of influence, not flavor."""
        if commander_id not in self.active_commanders(self.player_side):
            raise ValueError(f"{commander_id} is not one of your active commanders")
        dossier = self.dossiers[commander_id]
        thread = self.state.conversations.setdefault(commander_id, [])

        if self.client is None:
            reply = f"({dossier.name} acknowledges your signal.)"
        else:
            system = (
                build_persona_prompt(dossier)
                + "\n\nYou are now in a direct signal exchange with your theater "
                "commander. This is conversation, not an orders transmission: "
                "reply in character, in plain prose (no JSON), under 150 words. "
                "Speak your mind as this man would - what you see, what you need, "
                "what you think of his intentions.\n\nYOUR CURRENT SITUATION:\n"
                + build_briefing(self.state, commander_id)
            )
            messages = [{"role": "system", "content": system}]
            for line in thread[-8:]:
                role = "user" if line["role"] == "player" else "assistant"
                messages.append({"role": role, "content": line["text"]})
            messages.append({"role": "user", "content": message})
            reply = prose_from_reply(await self.client.request_text(messages, role=commander_id))
            if not reply:
                reply = f"({dossier.name} does not respond; the line crackles.)"

        thread.append({"turn": self.state.turn, "role": "player", "text": message})
        thread.append({"turn": self.state.turn, "role": "commander", "text": reply})
        return reply

    def dismissal_cost(self, commander_id: str) -> int:
        return DISMISSAL_BASE_COST + self.dossiers[commander_id].traits.get("ego", 5) // 3

    def dismiss(self, commander_id: str, replacement_id: str) -> int:
        dismissed = self.dossiers.get(commander_id)
        replacement = self.dossiers.get(replacement_id)
        if dismissed is None or replacement is None:
            raise ValueError("unknown commander")
        if dismissed.side != self.player_side:
            raise ValueError(f"{dismissed.name} is not one of your own commanders")
        if replacement.side != dismissed.side:
            raise ValueError(f"{replacement.name} serves the other side")
        if self.state.corps_for(replacement_id):
            raise ValueError(f"{replacement.name} already holds a command")
        cost = self.dismissal_cost(commander_id)
        if cost > self.political_capital:
            raise ValueError(
                f"not enough political capital: dismissing {dismissed.name} costs "
                f"{cost}, you have {self.political_capital}"
            )

        self.political_capital -= cost
        for corps in self.state.corps_for(commander_id):
            corps.commander = replacement_id
        replacement.role = dismissed.role
        dismissed.role = BENCH_ROLE
        dismissed.add_record(self.state.turn, "Relieved of command by the theater commander.")
        replacement.add_record(
            self.state.turn, f"Promoted to command of {replacement.role}."
        )
        if commander_id in self.state.directives:
            self.state.directives[replacement_id] = self.state.directives.pop(commander_id)
        # A relief unsettles the peers who remain in command.
        for other_id, other in self.dossiers.items():
            if (other_id not in (commander_id, replacement_id)
                    and other.side == self.player_side
                    and self.state.corps_for(other_id)):
                other.dynamic["relationship"] = max(0, other.dynamic.get("relationship", 5) - 1)
        return cost

    def save(self, path: Path) -> None:
        payload = {
            "state": self.state.to_dict(),
            "dossiers": [d.to_dict() for d in self.dossiers.values()],
            "player_side": self.player_side,
            "political_capital": self.political_capital,
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path, client: LMStudioClient | None = None,
             turn_log_dir: Path | None = None) -> Campaign:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        campaign = cls(
            state=GameState.from_dict(payload["state"]),
            dossiers={d["id"]: Dossier.from_dict(d) for d in payload["dossiers"]},
            client=client,
            player_side=payload.get("player_side", "axis"),
            political_capital=payload.get("political_capital", STARTING_POLITICAL_CAPITAL),
            turn_log_dir=turn_log_dir,
        )
        campaign.refresh_objectives()  # activate any objective now due (idempotent)
        return campaign
