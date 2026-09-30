import json
from pathlib import Path

import httpx
import pytest

from commanders.briefing import build_briefing
from commanders.campaign import Campaign
from commanders.llm import LMStudioClient

DATA_DIR = Path(__file__).parent.parent / "data"


def text_response(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def make_campaign(reply="Minsk first, Herr Feldmarschall - then the Dnieper."):
    campaign = Campaign.new(DATA_DIR)
    campaign.client = LMStudioClient(
        model="test", transport=httpx.MockTransport(lambda r: text_response(reply))
    )
    return campaign


async def test_converse_returns_reply_and_stores_thread():
    campaign = make_campaign()
    reply = await campaign.converse("guderian", "What is your assessment of the axis of advance?")
    assert "Minsk" in reply
    thread = campaign.state.conversations["guderian"]
    assert [m["role"] for m in thread] == ["player", "commander"]
    assert thread[0]["text"].startswith("What is your assessment")
    assert thread[0]["turn"] == 1


async def test_conversation_history_is_sent_to_the_model():
    campaign = make_campaign()
    captured = []

    def responder(request):
        captured.append(json.loads(request.content))
        return text_response("Understood.")

    campaign.client = LMStudioClient(model="test", transport=httpx.MockTransport(responder))
    await campaign.converse("guderian", "Hold at the Berezina until Kluge closes up.")
    await campaign.converse("guderian", "And do not cross without my order.")
    roles = [m["role"] for m in captured[1]["messages"]]
    assert roles.count("assistant") == 1  # earlier reply included as context
    assert "Berezina" in json.dumps(captured[1]["messages"])


async def test_conversation_feeds_next_briefing():
    campaign = make_campaign()
    await campaign.converse("guderian", "I expect you to screen the Pripyat flank.")
    briefing = build_briefing(campaign.state, "guderian")
    assert "EXCHANGES WITH" in briefing
    assert "Pripyat flank" in briefing


async def test_converse_rejects_enemy_or_unknown_commanders():
    campaign = make_campaign()
    with pytest.raises(ValueError):
        await campaign.converse("zhukov", "Comrade, how goes it?")
    with pytest.raises(ValueError):
        await campaign.converse("nobody", "Hello?")


async def test_converse_without_client_gives_stub_reply():
    campaign = Campaign.new(DATA_DIR)  # no client
    reply = await campaign.converse("guderian", "Report your situation.")
    assert reply  # deterministic acknowledgement, still stored
    assert campaign.state.conversations["guderian"][-1]["role"] == "commander"


async def test_conversations_survive_save_round_trip(tmp_path):
    campaign = make_campaign()
    await campaign.converse("guderian", "Speed above all.")
    path = tmp_path / "save.json"
    campaign.save(path)
    loaded = Campaign.load(path)
    assert loaded.state.conversations["guderian"] == campaign.state.conversations["guderian"]


# The echo loop (tests/test_communique_echo.py) came from replaying old pop-ups
# as bare assistant turns - undated, unbounded in age - which a model copies.
# A SIGNAL reply replays too. Only this week's exchange is a live conversation;
# everything older reaches him through the briefing's dated exchange block.

def _capturing(campaign):
    captured = []

    def responder(request):
        captured.append(json.loads(request.content))
        return text_response("Understood.")

    campaign.client = LMStudioClient(model="test", transport=httpx.MockTransport(responder))
    return captured


async def test_an_earlier_unprompted_signal_is_not_replayed_as_a_chat_turn():
    campaign = make_campaign()
    captured = _capturing(campaign)
    campaign.state.turn = 5
    campaign.state.conversations["guderian"] = [
        {"turn": 4, "role": "commander", "text": "Baranovichi is a trap!", "unprompted": True},
    ]
    await campaign.converse("guderian", "Report your intentions.")
    roles = [m["role"] for m in captured[0]["messages"]]
    assert roles == ["system", "user"]


async def test_this_weeks_unprompted_signal_is_not_a_chat_turn_either():
    # He sent it unasked; replayed as an assistant turn with no question
    # before it, it is the copy template itself.
    campaign = make_campaign()
    captured = _capturing(campaign)
    campaign.state.conversations["guderian"] = [
        {"turn": 1, "role": "commander", "text": "Give me fuel!", "unprompted": True},
    ]
    await campaign.converse("guderian", "You will have it.")
    assert [m["role"] for m in captured[0]["messages"]] == ["system", "user"]
    assert "Give me fuel!" in captured[0]["messages"][0]["content"]  # dated, in the briefing


async def test_an_exchange_from_weeks_ago_does_not_reach_the_model():
    campaign = make_campaign()
    captured = _capturing(campaign)
    campaign.state.turn = 6
    campaign.state.conversations["guderian"] = [
        {"turn": 2, "role": "player", "text": "Hold the Berezina bridges."},
        {"turn": 2, "role": "commander", "text": "The bridges will hold."},
    ]
    await campaign.converse("guderian", "Where are you now?")
    assert "Berezina" not in json.dumps(captured[0]["messages"])
