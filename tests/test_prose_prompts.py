"""The prose prompts - unprompted signals, SIGNAL replies, the staff report.

Playtest 2026-09-30 (qwen3.5-9b, then eight models): the orders prompt was
clean, but the prose prompts left slots the model filled with its own
defaults. Pop-ups and SIGNAL replies named no recipient ("To Commander
Busse", "My Lord", "Field Marshal Bock, Berlin"). Every model, up to 122B,
read "losses 41" as 41 men.
"""

import json
from pathlib import Path

import httpx

from commanders.campaign import Campaign
from commanders.dossier import load_dossiers
from commanders.llm import LMStudioClient
from commanders.prompts import _addressee_block, build_system_prompt
from commanders.records import update_track_records
from engine.scenario import load_scenario
from engine.turn import TurnReport

DATA_DIR = Path(__file__).parent.parent / "data"


def _capturing_campaign(reply: str = "Smolensk holds, Herr Feldmarschall.") -> tuple[Campaign, list]:
    captured: list = []
    campaign = Campaign.new(DATA_DIR)

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    campaign.client = LMStudioClient(model="test", transport=httpx.MockTransport(respond))
    return campaign, captured


def _system(request: dict) -> str:
    return next(m["content"] for m in request["messages"] if m["role"] == "system")


# --- who is reading ------------------------------------------------------------

def test_the_orders_prompt_still_names_the_dispatch_reader():
    dossier = load_dossiers(DATA_DIR)["guderian"]
    assert "WHO IS READING YOUR DISPATCH" in build_system_prompt(dossier)


def test_a_signal_names_its_reader_as_a_signal():
    block = _addressee_block(load_dossiers(DATA_DIR)["guderian"], reading="signal")
    assert block.startswith("WHO IS READING YOUR SIGNAL")
    assert "von Bock" in block


async def test_an_unprompted_signal_is_addressed_to_von_bock():
    campaign, captured = _capturing_campaign()
    await campaign._one_communique("guderian", [])
    assert "WHO IS READING YOUR SIGNAL: Generalfeldmarschall Fedor von Bock" in _system(captured[0])


async def test_a_signal_reply_is_addressed_to_von_bock():
    campaign, captured = _capturing_campaign()
    await campaign.converse("guderian", "Report your intentions.")
    assert "WHO IS READING YOUR SIGNAL: Generalfeldmarschall Fedor von Bock" in _system(captured[0])


# --- losses have a unit ----------------------------------------------------------

def _battle(state, outcome: str) -> TurnReport:
    ours = state.corps_for("guderian")[0]
    theirs = state.corps_for("pavlov")[0]
    return TurnReport(turn=1, combats=[{
        "region": theirs.location, "terrain": "clear",
        "attackers": [ours.id], "defenders": [theirs.id],
        "odds": 3.0, "attacker_losses": 4, "defender_losses": 41,
        "outcome": outcome, "encircled": False,
    }])


def test_staff_facts_give_losses_in_strength_points():
    campaign = Campaign.new(DATA_DIR)
    for outcome in ("defender_retreated", "defender_held", "pocket_holding"):
        facts = " ".join(campaign._staff_facts(_battle(campaign.state, outcome)))
        assert "4 strength points" in facts, outcome
        assert "41 strength points" in facts, outcome


def test_track_records_give_losses_in_strength_points():
    # The track record is quoted in every persona prompt, so a bare number
    # there leaks "men" into dispatches and signals as well.
    for outcome in ("defender_retreated", "defender_held", "pocket_holding"):
        state, dossiers = load_scenario(DATA_DIR), load_dossiers(DATA_DIR)
        update_track_records(state, _battle(state, outcome), dossiers)
        for cid in ("guderian", "pavlov"):
            summary = dossiers[cid].track_record[-1]["summary"]
            numbers = [w for w in summary.replace("(", " ").split() if w.strip(",.)").isdigit()]
            assert numbers, (outcome, cid, summary)
            assert "strength points" in summary, (outcome, cid, summary)
