import httpx
import pytest

from server.app import app, get_session


@pytest.fixture
async def api(tmp_path):
    session = get_session()
    session.reset(save_path=tmp_path / "campaign.json", use_llm=False,
                  logs_root=tmp_path / "logs")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_new_game_scopes_logs_to_a_run_dir(tmp_path):
    session = get_session()
    session.reset(save_path=tmp_path / "c.json", use_llm=False, logs_root=tmp_path / "logs")
    campaign = session.new_game()
    runs = list((tmp_path / "logs").glob("run-*"))
    assert len(runs) == 1, "one run directory per game"
    await campaign.play_turn({})
    assert (runs[0] / "turns" / "turn01.json").exists()  # telemetry lands in the run dir


async def test_new_game_returns_snapshot(api):
    r = await api.post("/api/game/new")
    assert r.status_code == 200
    snap = r.json()
    assert snap["turn"] == 1
    assert snap["date"] == "1941-06-22"
    assert snap["political_capital"] == 10
    assert any(reg["id"] == "moscow" for reg in snap["regions"])
    assert all("x" in reg and "y" in reg for reg in snap["regions"])
    # player sees own corps, not soviet internals
    own_sides = {c["commander"] for c in snap["corps"]}
    assert "guderian" in own_sides
    assert not any(c["id"].startswith("sov_") for c in snap["corps"])


async def test_snapshot_exposes_supply_legs(api):
    snap = (await api.post("/api/game/new")).json()
    legs = snap["supply_legs"]
    assert isinstance(legs, dict)
    assert any(v == 0 for v in legs.values())  # rear source sits on the railhead
    region_ids = {r["id"] for r in snap["regions"]}
    assert all(k in region_ids and isinstance(v, int) and v >= 0 for k, v in legs.items())


async def test_okh_opening_directive_appears_in_dispatches(api):
    # OKH's opening objective is stored at game start; it must reach the
    # player-visible DISPATCHES inbox, not be filtered out like the enemy's.
    snap = (await api.post("/api/game/new")).json()
    assert any(d["commander"] == "okh" for d in snap["dispatches"])


async def test_directives_are_stored(api):
    await api.post("/api/game/new")
    r = await api.post("/api/game/directives", json={"guderian": "Take Minsk."})
    assert r.status_code == 200
    snap = (await api.get("/api/game")).json()
    assert snap["directives"]["guderian"] == "Take Minsk."


async def test_end_turn_advances_and_returns_dispatches(api):
    await api.post("/api/game/new")
    r = await api.post("/api/game/end-turn")
    assert r.status_code == 200
    snap = r.json()
    assert snap["turn"] == 2
    assert snap["dispatches"]
    assert snap["last_report"] is not None
    assert any(d["commander"] == "staff" for d in snap["dispatches"])
    assert not any(d["commander"] == "zhukov" for d in snap["dispatches"])


async def test_dismiss_endpoint_validates(api):
    await api.post("/api/game/new")
    bad = await api.post("/api/game/dismiss", json={"commander": "guderian", "replacement": "hoth"})
    assert bad.status_code == 400
    good = await api.post("/api/game/dismiss", json={"commander": "guderian", "replacement": "schmidt"})
    assert good.status_code == 200
    assert good.json()["political_capital"] < 10


async def test_briefing_endpoint(api):
    await api.post("/api/game/new")
    r = await api.get("/api/game/briefing/guderian")
    assert r.status_code == 200
    assert "SITUATION BRIEFING" in r.json()["briefing"]


async def test_snapshot_survives_save_with_stale_map_data(api):
    # saves embed map_data; older saves may lack presentation fields like x/y
    session = get_session()
    session.new_game()
    for region in session.campaign.state.map_data["regions"]:
        region.pop("x", None)
        region.pop("y", None)
    snap = (await api.get("/api/game")).json()
    moscow = next(r for r in snap["regions"] if r["id"] == "moscow")
    assert isinstance(moscow["x"], (int, float))


async def test_snapshot_exposes_active_objectives_with_countdown(api):
    await api.post("/api/game/new")
    snap = (await api.get("/api/game")).json()
    assert snap["objectives"], "expected the opening OKH objective to be visible"
    minsk = next(o for o in snap["objectives"] if o["id"] == "take_minsk")
    assert minsk["status"] == "active"
    assert minsk["turns_left"] == minsk["deadline_turn"] - snap["turn"]
    # not-yet-issued objectives stay hidden
    assert not any(o["id"] == "take_moscow" for o in snap["objectives"])


async def test_objective_decision_endpoint(api):
    await api.post("/api/game/new")
    session = get_session()
    # force a pending diversion to decide on
    session.campaign.state.objectives.append({
        "id": "divert_test", "kind": "divert", "title": "South", "detail": "",
        "issued_turn": 1, "deadline_turn": 9, "target": "gomel",
        "reward": 5, "penalty": 5, "decline_penalty": 2, "status": "pending",
    })
    before = session.campaign.political_capital
    r = await api.post("/api/game/objective", json={"id": "divert_test", "accept": False})
    assert r.status_code == 200
    assert r.json()["political_capital"] == before - 2
    # deciding it again is rejected
    bad = await api.post("/api/game/objective", json={"id": "divert_test", "accept": True})
    assert bad.status_code == 400


async def test_relieved_verdict_surfaces_in_snapshot(api):
    await api.post("/api/game/new")
    session = get_session()
    session.campaign.political_capital = 0
    snap = (await api.get("/api/game")).json()
    assert snap["victory"]["kind"] == "relieved"
    r = await api.post("/api/game/end-turn")
    assert r.status_code == 409


async def test_snapshot_exposes_player_railhead(api):
    snap = (await api.post("/api/game/new")).json()
    assert isinstance(snap["railhead"], list)
    # the pre-war network is converted; nothing captured yet is
    assert "warsaw" in snap["railhead"]
    assert "smolensk" not in snap["railhead"]
    # only the player's own regions, never enemy supply network
    assert not any(r == "moscow" for r in snap["railhead"])


async def test_new_game_has_no_communiques(api):
    snap = (await api.post("/api/game/new")).json()
    assert snap["communiques"] == []


async def test_end_turn_surfaces_communique(api):
    await api.post("/api/game/new")
    session = get_session()
    session.campaign.communique_chance = 1.0  # force one
    snap = (await api.post("/api/game/end-turn")).json()
    assert len(snap["communiques"]) == 1
    assert snap["communiques"][0]["text"]
    # a fresh game clears it again
    snap2 = (await api.post("/api/game/new")).json()
    assert snap2["communiques"] == []


async def test_snapshot_reports_weather_and_victory(api):
    await api.post("/api/game/new")
    snap = (await api.get("/api/game")).json()
    assert snap["weather"] == "clear"
    assert snap["victory"] is None
    session = get_session()
    session.campaign.state.control["moscow"] = "axis"
    snap = (await api.get("/api/game")).json()
    assert snap["victory"]["winner"] == "axis"
    r = await api.post("/api/game/end-turn")
    assert r.status_code == 409


async def test_converse_endpoint_round_trip(api):
    await api.post("/api/game/new")
    r = await api.post(
        "/api/game/converse",
        json={"commander": "guderian", "message": "Where will you strike first?"},
    )
    assert r.status_code == 200
    assert r.json()["reply"]
    snap = (await api.get("/api/game")).json()
    thread = snap["conversations"]["guderian"]
    assert thread[0]["role"] == "player"
    assert thread[1]["role"] == "commander"
    bad = await api.post(
        "/api/game/converse", json={"commander": "zhukov", "message": "Comrade?"}
    )
    assert bad.status_code == 400


async def test_game_state_persists_across_session_reload(api, tmp_path):
    await api.post("/api/game/new")
    await api.post("/api/game/end-turn")
    session = get_session()
    session.reload()
    snap = (await api.get("/api/game")).json()
    assert snap["turn"] == 2
