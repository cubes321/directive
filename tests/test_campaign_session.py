import json
from pathlib import Path

import httpx
import pytest

from commanders.campaign import Campaign
from commanders.llm import LMStudioClient
from commanders.scripted import scripted_orders

DATA_DIR = Path(__file__).parent.parent / "data"


def scripted_as_model(campaign):
    """Mock transport that answers as whichever commander was prompted,
    using the scripted policy - a deterministic stand-in for the LLM."""
    role_to_id = {d.role: d.id for d in campaign.dossiers.values()}

    def responder(request):
        body = json.loads(request.content)
        if "response_format" not in body:  # staff report / conversation: plain text
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "Staff assessment: the front advances."}}]},
            )
        system = body["messages"][0]["content"]
        commander = next(
            cid for role, cid in role_to_id.items() if role != "(awaiting command)" and f"commanding {role}" in system
        )
        side = campaign.dossiers[commander].side
        if side == "axis":
            orders = scripted_orders(campaign.state, commander, stance="advance", goal="moscow")
        else:
            orders = scripted_orders(campaign.state, commander, stance="defend")
        payload = orders.to_dict()
        payload["dispatch"] = f"{commander} reporting: orders issued."
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )

    return httpx.MockTransport(responder)


def make_campaign():
    campaign = Campaign.new(DATA_DIR)
    campaign.client = LMStudioClient(model="test", transport=scripted_as_model(campaign))
    return campaign


async def test_play_turn_runs_all_nine_commanders():
    campaign = make_campaign()
    result = await campaign.play_turn({"guderian": "Take Minsk."})
    assert campaign.state.turn == 2
    commander_dispatches = [
        d for d in result.dispatches if d["commander"] not in ("staff", "okh")
    ]
    assert len(commander_dispatches) == 9
    assert {d["commander"] for d in result.dispatches} >= {"guderian", "zhukov", "staff"}
    # this turn's dispatches are recorded in state (which also holds the opening
    # OKH directive issued at game start)
    assert all(d in campaign.state.dispatches for d in result.dispatches)
    assert any(d["commander"] == "okh" for d in campaign.state.dispatches)


async def test_soviet_commanders_get_stavka_directives():
    campaign = make_campaign()
    await campaign.play_turn({})
    assert "Stavka" in campaign.state.directives["zhukov"]


async def test_combat_outcomes_feed_track_records():
    campaign = make_campaign()
    await campaign.play_turn({"guderian": "Attack toward Minsk."})
    recorded = [d for d in campaign.dossiers.values() if d.track_record]
    assert recorded, "expected at least one commander to remember turn 1"


async def test_save_and_load_round_trip(tmp_path):
    campaign = make_campaign()
    await campaign.play_turn({"guderian": "Forward."})
    campaign.political_capital = 7
    path = tmp_path / "save.json"
    campaign.save(path)
    loaded = Campaign.load(path)
    assert loaded.state.to_dict() == campaign.state.to_dict()
    assert loaded.political_capital == 7
    assert loaded.dossiers["guderian"].track_record == campaign.dossiers["guderian"].track_record


def test_prose_from_reply_unwraps_accidental_json():
    from commanders.campaign import prose_from_reply

    # plain prose is returned unchanged
    assert prose_from_reply("The panzers must not halt.") == "The panzers must not halt."
    # a model that lapses into order-JSON: pull the human-facing field
    blob = '{"orders": [], "dispatch": "Forward!", "signal": "My fuel is gone.", "reasoning": "x"}'
    assert prose_from_reply(blob) == "My fuel is gone."
    # dispatch is used when there is no signal field
    assert prose_from_reply('{"orders": [], "dispatch": "Forward!"}') == "Forward!"
    # JSON without a usable text field falls back to the raw string
    weird = '{"foo": 1}'
    assert prose_from_reply(weird) == weird


async def test_communique_fires_and_is_stored_and_answerable():
    campaign = make_campaign()
    campaign.communique_chance = 1.0  # force one this turn
    result = await campaign.play_turn({})
    assert len(result.communiques) == 1
    c = result.communiques[0]
    assert c["text"] and c["name"]
    cid = c["commander"]
    # stored as an unprompted commander line in his conversation thread
    thread = campaign.state.conversations[cid]
    assert thread[-1]["role"] == "commander"
    assert thread[-1]["unprompted"] is True
    # and the player can answer it through the normal channel
    reply = await campaign.converse(cid, "Understood. Hold your flank.")
    assert reply
    assert campaign.state.conversations[cid][-2]["text"] == "Understood. Hold your flank."


async def test_no_communique_when_chance_zero():
    campaign = make_campaign()
    campaign.communique_chance = 0.0
    result = await campaign.play_turn({})
    assert result.communiques == []


async def test_communique_without_client_still_produces_text():
    campaign = Campaign.new(DATA_DIR)  # no client
    campaign.communique_chance = 1.0
    result = await campaign.play_turn({})
    assert len(result.communiques) == 1
    assert result.communiques[0]["text"]


async def test_unprompted_flag_survives_save_round_trip(tmp_path):
    campaign = make_campaign()
    campaign.communique_chance = 1.0
    await campaign.play_turn({})
    path = tmp_path / "save.json"
    campaign.save(path)
    loaded = Campaign.load(path)
    assert loaded.state.conversations == campaign.state.conversations
    assert any(
        line.get("unprompted")
        for thread in loaded.state.conversations.values()
        for line in thread
    )


async def test_turn_ends_with_a_chief_of_staff_report():
    campaign = make_campaign()
    result = await campaign.play_turn({"guderian": "Forward."})
    staff = [d for d in result.dispatches if d["commander"] == "staff"]
    assert len(staff) == 1
    assert staff[0]["text"]
    # the staff report is recorded for the inbox, after the commanders' dispatches
    assert any(d["commander"] == "staff" for d in campaign.state.dispatches)


async def test_staff_report_without_llm_summarizes_battles():
    campaign = Campaign.new(DATA_DIR)  # no client -> deterministic summary
    result = await campaign.play_turn({})
    staff = next(d for d in result.dispatches if d["commander"] == "staff")
    combats = result.report.combats
    if combats:
        region = combats[0]["region"]
        name = campaign.state.game_map.regions[region].name
        assert name in staff["text"]


async def test_play_turn_evolves_morale_and_it_persists(tmp_path):
    campaign = make_campaign()
    for cid in campaign.active_commanders(campaign.player_side):
        campaign.dossiers[cid].dynamic["fatigue"] = 5  # known baseline
    await campaign.play_turn({})
    fatigues = [campaign.dossiers[cid].dynamic["fatigue"]
                for cid in campaign.active_commanders(campaign.player_side)]
    assert any(f != 5 for f in fatigues)  # morale moved for someone
    path = tmp_path / "save.json"
    campaign.save(path)
    reloaded = Campaign.load(path)
    any_cid = campaign.active_commanders(campaign.player_side)[0]
    assert reloaded.dossiers[any_cid].dynamic == campaign.dossiers[any_cid].dynamic


async def test_play_turn_writes_a_turn_log_when_dir_set(tmp_path):
    campaign = Campaign.new(DATA_DIR, turn_log_dir=tmp_path)  # no client is fine
    await campaign.play_turn({})
    logs = list(tmp_path.glob("turn*.json"))
    assert logs, "expected a per-turn telemetry file"
    data = json.loads(logs[0].read_text(encoding="utf-8"))
    assert data["turn"] == 1
    assert "combats" in data
    assert any(u["side"] == "axis" for u in data["units"])


async def test_no_turn_log_written_without_a_dir(tmp_path):
    campaign = Campaign.new(DATA_DIR)  # turn_log_dir defaults to None
    await campaign.play_turn({})
    assert not list(tmp_path.glob("turn*.json"))


async def test_transition_turn_briefs_on_current_weather_not_last_turns():
    # Turn 16 is the clear->mud transition. The briefing (and thus order
    # validation) must reflect THIS turn's weather, or a commander plans on
    # clear-weather movement that resolution then executes under mud.
    campaign = Campaign.new(DATA_DIR)
    campaign.state.turn = 16
    campaign.state.weather = "clear"  # stale value carried from turn 15
    briefings = []
    role_to_id = {d.role: d.id for d in campaign.dossiers.values()}

    def responder(request):
        body = json.loads(request.content)
        if "response_format" not in body:
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        system = body["messages"][0]["content"]
        briefings.append(body["messages"][1]["content"])
        commander = next(
            cid for role, cid in role_to_id.items()
            if role != "(awaiting command)" and f"commanding {role}" in system
        )
        payload = scripted_orders(campaign.state, commander, stance="defend").to_dict()
        payload["dispatch"] = "ok"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    campaign.client = LMStudioClient(model="t", transport=httpx.MockTransport(responder))
    await campaign.play_turn({})
    assert briefings, "expected at least one briefing"
    assert all("Weather: mud" in b for b in briefings)


def _active_capture(target, **kw):
    base = dict(id="t1", kind="capture", title="Take it", detail="",
                issued_turn=1, deadline_turn=4, target=target,
                reward=3, penalty=3, status="active")
    base.update(kw)
    return base


async def test_meeting_an_objective_banks_standing_and_posts_okh_dispatch():
    campaign = make_campaign()
    campaign.state.objectives = [_active_capture("warsaw")]  # already axis-held
    before = campaign.political_capital
    result = await campaign.play_turn({})
    assert campaign.political_capital == before + 3
    assert campaign.state.objectives[0]["status"] == "met"
    assert any(d["commander"] == "okh" for d in result.dispatches)


async def test_failing_an_objective_costs_standing():
    campaign = make_campaign()
    campaign.state.turn = 5  # past the deadline
    campaign.state.objectives = [_active_capture("moscow", deadline_turn=4)]
    before = campaign.political_capital
    await campaign.play_turn({})
    assert campaign.political_capital == before - 3
    assert campaign.state.objectives[0]["status"] == "failed"


def test_decline_diversion_costs_decline_penalty():
    campaign = Campaign.new(DATA_DIR)
    campaign.state.objectives = [dict(id="d1", kind="divert", title="South", detail="",
                                      issued_turn=1, deadline_turn=6, target="gomel",
                                      reward=5, penalty=5, decline_penalty=2, status="pending")]
    before = campaign.political_capital
    campaign.decide_diversion("d1", accept=False)
    assert campaign.state.objectives[0]["status"] == "declined"
    assert campaign.political_capital == before - 2


def test_accept_diversion_makes_it_a_live_objective():
    campaign = Campaign.new(DATA_DIR)
    campaign.state.objectives = [dict(id="d1", kind="divert", title="South", detail="",
                                      issued_turn=1, deadline_turn=6, target="gomel",
                                      reward=5, penalty=5, decline_penalty=2, status="pending")]
    before = campaign.political_capital
    campaign.decide_diversion("d1", accept=True)
    assert campaign.state.objectives[0]["status"] == "accepted"
    assert campaign.political_capital == before  # accepting costs nothing up front


def test_deciding_a_non_pending_objective_is_rejected():
    campaign = Campaign.new(DATA_DIR)
    campaign.state.objectives = [_active_capture("minsk")]
    with pytest.raises(ValueError):
        campaign.decide_diversion("t1", accept=True)


async def test_running_out_of_standing_relieves_the_player():
    campaign = make_campaign()
    campaign.political_capital = 1
    campaign.state.turn = 5
    campaign.state.objectives = [_active_capture("moscow", deadline_turn=4, penalty=3)]
    result = await campaign.play_turn({})
    assert campaign.political_capital <= 0
    assert result.victory is not None
    assert result.victory["kind"] == "relieved"
    with pytest.raises(ValueError, match="over"):
        await campaign.play_turn({})


async def test_taking_moscow_ends_the_game():
    campaign = make_campaign()
    # stage guderian's panzers at the gates with the garrison destroyed
    for cid in ("xxiv_pz", "xlvi_pz", "xlvii_pz"):
        campaign.state.corps[cid].location = "mozhaisk"
    campaign.state.control["mozhaisk"] = "axis"
    campaign.state.corps["sov_49a"].take_losses(strength=100)
    result = await campaign.play_turn({})
    assert result.victory is not None
    assert result.victory["winner"] == "axis"
    with pytest.raises(ValueError, match="over"):
        await campaign.play_turn({})


def test_dismissal_costs_political_capital_and_reassigns_corps():
    campaign = Campaign.new(DATA_DIR)
    cost = campaign.dismiss("guderian", "schmidt")
    assert cost == 2 + 9 // 3  # base + ego scaling
    assert campaign.political_capital == 10 - cost
    assert all(c.commander == "schmidt" for c in campaign.state.corps_for("schmidt"))
    assert campaign.state.corps_for("guderian") == []
    assert any("relieved" in r["summary"].lower() for r in campaign.dossiers["guderian"].track_record)


def test_dismissal_requires_benched_same_side_replacement():
    campaign = Campaign.new(DATA_DIR)
    with pytest.raises(ValueError):
        campaign.dismiss("guderian", "hoth")  # hoth already has a command
    with pytest.raises(ValueError):
        campaign.dismiss("guderian", "rokossovsky")  # wrong side


def test_dismissing_a_commander_cools_the_remaining_ones():
    campaign = Campaign.new(DATA_DIR)
    hoth_before = campaign.dossiers["hoth"].dynamic["relationship"]
    campaign.dismiss("guderian", "schmidt")  # relieve a peer
    assert campaign.dossiers["hoth"].dynamic["relationship"] == hoth_before - 1
    # the enemy side is untouched
    assert campaign.dossiers["pavlov"].dynamic["relationship"] == 5


def test_dismissal_blocked_without_capital():
    campaign = Campaign.new(DATA_DIR)
    campaign.political_capital = 2
    with pytest.raises(ValueError, match="political capital"):
        campaign.dismiss("guderian", "schmidt")


def test_cannot_dismiss_an_enemy_commander():
    # The player commands the Axis; personnel actions must not reach across the
    # front to reshuffle the Soviet order of battle (both are Soviet here).
    campaign = Campaign.new(DATA_DIR)
    before = campaign.political_capital
    with pytest.raises(ValueError, match="your own"):
        campaign.dismiss("pavlov", "rokossovsky")
    assert campaign.political_capital == before
    assert all(c.commander == "pavlov" for c in campaign.state.corps_for("pavlov"))
