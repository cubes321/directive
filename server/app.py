"""FastAPI server: the theater commander's desk.

A single campaign session per process. The browser talks JSON; the engine and
LLM layer stay behind the Campaign object. The player only ever sees their own
side's corps plus fog-of-war contacts.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from commanders.briefing import build_briefing
from commanders.campaign import Campaign
from commanders.llm import LMStudioClient, LMStudioUnavailable
from engine.fog import visible_enemy_contacts
from engine.turn import TurnReport

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
DEFAULT_SAVE = ROOT / "server" / "saves" / "campaign.json"
DEFAULT_MODEL = "qwen/qwen3.6-35b-a3b"
DISPATCH_HISTORY_LIMIT = 60


class Session:
    """Holds the one live campaign and its configuration."""

    def __init__(self) -> None:
        self.campaign: Campaign | None = None
        self.save_path = DEFAULT_SAVE
        self.use_llm = True
        self.model = DEFAULT_MODEL
        self.last_report: TurnReport | None = None

    def _client(self) -> LMStudioClient | None:
        if not self.use_llm:
            return None
        return LMStudioClient(model=self.model, log_dir=ROOT / "logs" / "campaign")

    def reset(self, save_path: Path | None = None, use_llm: bool = True,
              model: str = DEFAULT_MODEL) -> None:
        self.campaign = None
        self.last_report = None
        self.use_llm = use_llm
        self.model = model
        if save_path is not None:
            self.save_path = Path(save_path)

    def new_game(self) -> Campaign:
        self.campaign = Campaign.new(DATA_DIR, client=self._client())
        self.last_report = None
        return self.campaign

    def reload(self) -> Campaign:
        self.campaign = Campaign.load(self.save_path, client=self._client())
        self.last_report = None
        return self.campaign

    def require_campaign(self) -> Campaign:
        if self.campaign is None:
            if self.save_path.exists():
                return self.reload()
            raise HTTPException(404, "No campaign in progress; POST /api/game/new")
        return self.campaign


_session = Session()


def get_session() -> Session:
    return _session


app = FastAPI(title="Directive")


def _report_dict(report: TurnReport | None) -> dict | None:
    if report is None:
        return None
    return {"turn": report.turn, "movements": report.movements, "combats": report.combats}


def snapshot(session: Session) -> dict:
    campaign = session.require_campaign()
    state = campaign.state
    side = campaign.player_side

    regions = []
    for r in state.map_data["regions"]:
        regions.append(
            {
                "id": r["id"],
                "name": r["name"],
                "terrain": r["terrain"],
                "victory_points": r.get("victory_points", 0),
                "x": r["x"],
                "y": r["y"],
                "control": state.control[r["id"]],
            }
        )
    edges = [
        {"a": e["between"][0], "b": e["between"][1], "road": e["road"], "rail": e["rail"]}
        for e in state.map_data["edges"]
    ]
    own_corps = [
        c.to_dict() for c in state.corps.values() if c.side == side and not c.is_destroyed
    ]
    player_commanders = []
    for cid in campaign.active_commanders(side):
        d = campaign.dossiers[cid]
        player_commanders.append(
            {
                "id": d.id,
                "name": d.name,
                "role": d.role,
                "traits": d.traits,
                "dynamic": d.dynamic,
                "track_record": d.track_record[-6:],
                "corps": [c.id for c in state.corps_for(cid) if not c.is_destroyed],
                "dismissal_cost": campaign.dismissal_cost(cid),
            }
        )
    bench = [
        {"id": campaign.dossiers[cid].id, "name": campaign.dossiers[cid].name,
         "traits": campaign.dossiers[cid].traits, "bio": campaign.dossiers[cid].bio}
        for cid in campaign.benched_commanders(side)
    ]
    own_commander_ids = {d["id"] for d in player_commanders}
    dispatches = [
        d for d in state.dispatches if d["commander"] in campaign.dossiers
        and campaign.dossiers[d["commander"]].side == side
    ][-DISPATCH_HISTORY_LIMIT:]

    vp = {"axis": 0, "soviet": 0}
    for r in regions:
        vp[r["control"]] += r["victory_points"]

    return {
        "turn": state.turn,
        "date": state.date.isoformat(),
        "weather": state.weather,
        "player_side": side,
        "political_capital": campaign.political_capital,
        "victory_points": vp,
        "regions": regions,
        "edges": edges,
        "corps": own_corps,
        "contacts": visible_enemy_contacts(state, side),
        "commanders": player_commanders,
        "bench": bench,
        "directives": {
            k: v for k, v in state.directives.items() if k in own_commander_ids
        },
        "dispatches": dispatches,
        "last_report": _report_dict(session.last_report),
    }


@app.post("/api/game/new")
async def new_game():
    get_session().new_game()
    return snapshot(get_session())


@app.get("/api/game")
async def game_state():
    return snapshot(get_session())


@app.post("/api/game/directives")
async def set_directives(directives: dict[str, str]):
    session = get_session()
    campaign = session.require_campaign()
    own = set(campaign.active_commanders(campaign.player_side))
    unknown = set(directives) - own
    if unknown:
        raise HTTPException(400, f"not your commanders: {sorted(unknown)}")
    campaign.state.directives.update(directives)
    return {"ok": True}


@app.post("/api/game/end-turn")
async def end_turn():
    session = get_session()
    campaign = session.require_campaign()
    try:
        result = await campaign.play_turn({})
    except LMStudioUnavailable as e:
        raise HTTPException(503, str(e))
    session.last_report = result.report
    campaign.save(session.save_path)
    return snapshot(session)


@app.post("/api/game/dismiss")
async def dismiss(body: dict):
    session = get_session()
    campaign = session.require_campaign()
    try:
        cost = campaign.dismiss(body["commander"], body["replacement"])
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    campaign.save(session.save_path)
    return {
        "ok": True,
        "cost": cost,
        "political_capital": campaign.political_capital,
    }


@app.get("/api/game/briefing/{commander}")
async def briefing(commander: str):
    session = get_session()
    campaign = session.require_campaign()
    if commander not in campaign.active_commanders(campaign.player_side):
        raise HTTPException(404, "not one of your active commanders")
    return {"briefing": build_briefing(campaign.state, commander)}


web_dir = ROOT / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
