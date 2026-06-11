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
    assert len(result.dispatches) == 9
    assert {d["commander"] for d in result.dispatches} >= {"guderian", "zhukov"}
    # dispatches also recorded in state for the UI
    assert len(campaign.state.dispatches) == 9


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


def test_dismissal_blocked_without_capital():
    campaign = Campaign.new(DATA_DIR)
    campaign.political_capital = 2
    with pytest.raises(ValueError, match="political capital"):
        campaign.dismiss("guderian", "schmidt")
