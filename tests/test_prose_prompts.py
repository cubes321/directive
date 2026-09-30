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


# --- the staff report works from the whole week, and only from it ---------------
#
# _staff_facts gave the chief of staff combat losses, starving corps and the
# weather - nothing that went well - then asked "what worries the staff" and for
# "one recommendation". On qwen3.5-9b he recommended halting in 15 of 15
# reports, and invented air support and enemy reserves to justify it.

def _enemy_region(campaign: Campaign) -> str:
    return sorted(r for r, s in campaign.state.control.items() if s != campaign.player_side)[0]


def _own_region(campaign: Campaign) -> str:
    return sorted(r for r, s in campaign.state.control.items() if s == campaign.player_side)[0]


def test_staff_facts_report_ground_taken_this_week():
    campaign = Campaign.new(DATA_DIR)
    before = dict(campaign.state.control)
    taken = _enemy_region(campaign)
    campaign.state.control[taken] = campaign.player_side
    facts = campaign._staff_facts(TurnReport(turn=1), control_before=before)
    name = campaign.state.game_map.regions[taken].name
    assert f"Ground taken this week: {name}." in facts


def test_staff_facts_report_ground_lost_this_week():
    campaign = Campaign.new(DATA_DIR)
    before = dict(campaign.state.control)
    lost = _own_region(campaign)
    campaign.state.control[lost] = "soviet"
    facts = campaign._staff_facts(TurnReport(turn=1), control_before=before)
    assert f"Ground lost this week: {campaign.state.game_map.regions[lost].name}." in facts


def test_staff_facts_list_taken_ground_in_a_stable_order():
    campaign = Campaign.new(DATA_DIR)
    before = dict(campaign.state.control)
    enemy = sorted(r for r, s in before.items() if s != campaign.player_side)[:3]
    for region in reversed(enemy):
        campaign.state.control[region] = campaign.player_side
    line = next(f for f in campaign._staff_facts(TurnReport(turn=1), control_before=before)
                if f.startswith("Ground taken"))
    names = [campaign.state.game_map.regions[r].name for r in enemy]
    assert line == f"Ground taken this week: {', '.join(sorted(names))}."


def test_staff_facts_without_a_before_picture_say_nothing_about_ground():
    campaign = Campaign.new(DATA_DIR)
    facts = " ".join(campaign._staff_facts(TurnReport(turn=1)))
    assert "Ground" not in facts


def test_staff_facts_give_the_standing_of_each_live_okh_objective():
    campaign = Campaign.new(DATA_DIR)
    facts = campaign._staff_facts(TurnReport(turn=1))
    line = next(f for f in facts if "Close the Bialystok-Minsk pocket" in f)
    assert "week 4" in line and "Minsk" in line and "not yet taken" in line
    assert not any("Smolensk, the gate to Moscow" in f for f in facts)  # not yet issued


def test_a_held_objective_is_provisional_until_its_deadline():
    # OKH scores holding the target AT the deadline; the staff must not tell
    # the player the job is done in week 2.
    campaign = Campaign.new(DATA_DIR)
    campaign.state.control["minsk"] = campaign.player_side
    line = next(f for f in campaign._staff_facts(TurnReport(turn=2))
                if "Close the Bialystok-Minsk pocket" in f)
    assert "in our hands" in line and "hold it through week 4" in line


async def test_the_staff_prompt_confines_the_report_to_the_facts():
    campaign, captured = _capturing_campaign(reply="Assessment.")
    await campaign._staff_report(TurnReport(turn=1))
    system = _system(captured[0])
    assert "only from the events listed" in system
    assert "strength points, not men" in system
    assert "press on, consolidate or halt" in system


async def test_a_played_turn_tells_the_staff_what_ground_changed_hands():
    # No client: the staff dispatch is the fact list itself, so what end_turn
    # handed _staff_facts is visible in it.
    campaign = Campaign.new(DATA_DIR)
    before = dict(campaign.state.control)
    result = await campaign.play_turn({})
    staff = next(d for d in result.dispatches if d["commander"] == "staff")["text"]
    changed = sorted(r for r, s in campaign.state.control.items() if before.get(r) != s)
    assert changed, "the opening turn should move the line"
    assert "Ground taken this week" in staff or "Ground lost this week" in staff


def test_a_met_objective_past_its_deadline_reads_as_achieved_not_live():
    campaign = Campaign.new(DATA_DIR)
    campaign.state.control["minsk"] = campaign.player_side
    next(o for o in campaign.state.objectives if o["target"] == "minsk")["status"] = "met"
    line = next(f for f in campaign._staff_facts(TurnReport(turn=6))
                if "Close the Bialystok-Minsk pocket" in f)
    assert "achieved" in line


# --- the staff argues both sides before it decides -------------------------------
#
# Wording alone never moved the halt: 29/30 on qwen3.5-9b across weeks 3, 6 and
# 10, including week 3 with Minsk taken and a 67:1 pocket. What moved it was
# the decision's shape: a schema that makes the model write the case for
# pressing on, then the case for halting, and only then the verdict, plus a
# burden of proof on halting. Verdicts, two runs of 10 per week pooled
# (press on / consolidate / halt): week 3 19/1/0, week 6 13/7/0, week 10
# 7/13/0. Schema alone was 8/12/0, 1/19/0, 0/19/1: it traded one fixed
# verdict for another, which is why the burden text is there.

def _staff_campaign(*replies, status: int = 200) -> tuple[Campaign, list]:
    captured: list = []
    campaign = Campaign.new(DATA_DIR)
    queue = list(replies)

    def respond(request):
        body = json.loads(request.content)
        captured.append(body)
        if status != 200 and "response_format" in body:
            return httpx.Response(status, json={"error": {"message": "response_format unsupported"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": queue.pop(0)}}]})

    campaign.client = LMStudioClient(model="test", transport=httpx.MockTransport(respond))
    return campaign, captured


def _assessment(report="Minsk is ours. Recommendation: press on to the Berezina.",
                verdict="press_on") -> str:
    return json.dumps({"case_for_pressing_on": "Minsk fell cheaply.",
                       "case_for_halting": "Molodechno cost 8.",
                       "recommendation": verdict, "report": report})


async def test_the_staff_decides_after_arguing_both_cases():
    campaign, captured = _staff_campaign(_assessment())
    await campaign._staff_report(TurnReport(turn=1))
    fmt = captured[0]["response_format"]
    assert fmt["type"] == "json_schema"
    props = fmt["json_schema"]["schema"]["properties"]
    # the order is the mechanism: the verdict is decoded after both cases
    assert list(props) == ["case_for_pressing_on", "case_for_halting", "recommendation", "report"]
    assert props["recommendation"]["enum"] == ["press_on", "consolidate", "halt"]


async def test_a_halt_must_name_the_facts_that_force_it():
    campaign, captured = _staff_campaign(_assessment())
    await campaign._staff_report(TurnReport(turn=1))
    system = _system(captured[0])
    assert "Recommend a halt only where the listed facts show" in system


async def test_the_player_sees_only_the_report():
    campaign, _ = _staff_campaign(_assessment(report="Minsk is ours. Press on."))
    assert await campaign._staff_report(TurnReport(turn=1)) == "Minsk is ours. Press on."


async def test_a_fenced_assessment_is_still_read():
    # Moonshot's json_schema is not strict: fences and preambles arrive
    campaign, _ = _staff_campaign("Here it is:\n```json\n" + _assessment(report="Hold.") + "\n```")
    assert await campaign._staff_report(TurnReport(turn=1)) == "Hold."


async def test_a_plain_prose_reply_is_shown_as_it_came():
    campaign, _ = _staff_campaign("Minsk has fallen. The staff recommends pressing on.")
    text = await campaign._staff_report(TurnReport(turn=1))
    assert text == "Minsk has fallen. The staff recommends pressing on."


async def test_an_empty_reply_falls_back_to_the_fact_list():
    campaign, _ = _staff_campaign("")
    text = await campaign._staff_report(TurnReport(turn=1))
    assert text.startswith("Weekly staff assessment:")


async def test_a_backend_that_refuses_the_schema_still_gets_a_staff_report():
    # A turn must never fail over the staff report: retry once as plain prose.
    campaign, captured = _staff_campaign("Minsk has fallen. Press on.", status=400)
    text = await campaign._staff_report(TurnReport(turn=1))
    assert text == "Minsk has fallen. Press on."
    assert ["response_format" in c for c in captured] == [True, False]
    assert "Reply as JSON" not in _system(captured[1])
