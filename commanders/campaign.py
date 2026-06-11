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
from dataclasses import dataclass, field
from pathlib import Path

from commanders.dossier import Dossier, load_dossiers
from commanders.intent import soviet_directives
from commanders.llm import LMStudioClient
from commanders.orchestrator import gather_orders
from commanders.records import update_track_records
from commanders.scripted import scripted_orders
from engine.scenario import load_scenario
from engine.state import GameState
from engine.turn import TurnReport, resolve_turn
from engine.victory import check_victory

STARTING_POLITICAL_CAPITAL = 10
DISMISSAL_BASE_COST = 2
BENCH_ROLE = "(awaiting command)"


@dataclass
class TurnResult:
    report: TurnReport
    dispatches: list[dict]
    victory: dict | None = None


@dataclass
class Campaign:
    state: GameState
    dossiers: dict[str, Dossier]
    client: LMStudioClient | None = None
    player_side: str = "axis"
    political_capital: int = STARTING_POLITICAL_CAPITAL

    @classmethod
    def new(cls, data_dir: Path, client: LMStudioClient | None = None) -> Campaign:
        return cls(
            state=load_scenario(data_dir),
            dossiers=load_dossiers(data_dir),
            client=client,
        )

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

    async def play_turn(self, player_directives: dict[str, str]) -> TurnResult:
        if check_victory(self.state) is not None:
            raise ValueError("the campaign is over")
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
        return TurnResult(
            report=report, dispatches=dispatches, victory=check_victory(self.state)
        )

    def dismissal_cost(self, commander_id: str) -> int:
        return DISMISSAL_BASE_COST + self.dossiers[commander_id].traits.get("ego", 5) // 3

    def dismiss(self, commander_id: str, replacement_id: str) -> int:
        dismissed = self.dossiers.get(commander_id)
        replacement = self.dossiers.get(replacement_id)
        if dismissed is None or replacement is None:
            raise ValueError("unknown commander")
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
    def load(cls, path: Path, client: LMStudioClient | None = None) -> Campaign:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            state=GameState.from_dict(payload["state"]),
            dossiers={d["id"]: Dossier.from_dict(d) for d in payload["dossiers"]},
            client=client,
            player_side=payload.get("player_side", "axis"),
            political_capital=payload.get("political_capital", STARTING_POLITICAL_CAPITAL),
        )
