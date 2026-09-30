"""The unprompted-communique echo loop (playtest 2026-09-30).

Guderian sent the same pop-up word for word four weeks running, still arguing
about taking Baranovichi long after it fell. Two causes: every earlier
communique was replayed to the model as a back-to-back assistant turn (no
dates, no age limit), which a model copies; and nothing stopped a copy
reaching the player.
"""

import json
from pathlib import Path

import httpx

from commanders.briefing import build_briefing
from commanders.campaign import Campaign
from commanders.communique import is_echo
from commanders.llm import LMStudioClient
from engine.turn import TurnReport

DATA_DIR = Path(__file__).parent.parent / "data"

OLD_RANT = (
    "To the Theater Commander: Do not tell me to grind through Orsha for two armies "
    "that can be cut off! My tanks are not infantry; they do not march into defensive "
    "belts. I am bypassing Orsha and striking hard toward Mogilev, smashing the Soviet "
    "rear before they can react. Speed is my only shield."
)
FRESH = (
    "Smolensk is ours again, Herr Feldmarschall. Give me three days of fuel and I will "
    "have XLVI on the Vyazma road before the Soviets have counted their dead."
)


def _campaign(reply: str, captured: list | None = None) -> Campaign:
    campaign = Campaign.new(DATA_DIR)

    def respond(request):
        if captured is not None:
            captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    campaign.client = LMStudioClient(model="test", transport=httpx.MockTransport(respond))
    campaign.communique_chance = 1.0
    return campaign


def _thread(campaign: Campaign, commander: str, lines: list[tuple[int, str, str]]) -> None:
    campaign.state.conversations[commander] = [
        {"turn": t, "role": role, "text": text, **({"unprompted": True} if role == "commander" else {})}
        for t, role, text in lines
    ]


def _every_axis_commander_said(campaign: Campaign, text: str) -> None:
    # whichever commander the dice pick, he has said this before
    for cid in campaign.active_commanders("axis"):
        _thread(campaign, cid, [(campaign.state.turn - 1, "commander", text)])


# --- the guard -----------------------------------------------------------------

def test_a_verbatim_repeat_is_an_echo():
    assert is_echo(OLD_RANT, [OLD_RANT])


def test_a_lightly_edited_repeat_is_an_echo():
    edited = OLD_RANT.replace("Mogilev", "Smolensk").replace("To the Theater Commander: ", "")
    assert is_echo(edited, [OLD_RANT])


def test_a_new_message_in_the_same_voice_is_not_an_echo():
    assert not is_echo(FRESH, [OLD_RANT])


def test_quoting_a_whole_earlier_line_inside_a_longer_reply_is_an_echo():
    padded = OLD_RANT + " And I will say it again until you listen to me, Herr Feldmarschall."
    assert is_echo(padded, [OLD_RANT])


def test_mentioning_a_short_earlier_order_is_not_an_echo():
    assert not is_echo(FRESH, ["Smolensk is ours.", "Take Smolensk."])


def test_nothing_to_echo_is_not_an_echo():
    assert not is_echo(FRESH, [])
    assert not is_echo("", [OLD_RANT])


# --- the campaign path ------------------------------------------------------------

async def test_an_echoed_communique_never_reaches_the_player():
    campaign = _campaign(reply=OLD_RANT)
    campaign.state.turn = 5
    _every_axis_commander_said(campaign, OLD_RANT)
    before = {cid: len(t) for cid, t in campaign.state.conversations.items()}
    assert await campaign._communiques(TurnReport(turn=5)) == []
    after = {cid: len(t) for cid, t in campaign.state.conversations.items()}
    assert after == before  # and it is not written into the thread either


async def test_a_communique_that_parrots_the_theater_directive_is_dropped():
    # qwen3.6-35b opened a pop-up with the player's own directive to him,
    # "Heinz: Minsk is three hundred kilometres BEHIND the front..." - the
    # directive is quoted in the briefing, and the model spoke in its voice.
    directive = (
        "Heinz: Minsk is three hundred kilometres BEHIND the front. You pulled XLVI and "
        "XLVII out of Smolensk and a single Soviet army walked in."
    )
    campaign = _campaign(reply=directive)
    for cid in campaign.active_commanders("axis"):
        campaign.state.directives[cid] = directive
    assert await campaign._communiques(TurnReport(turn=1)) == []


async def test_a_fresh_communique_still_goes_through():
    campaign = _campaign(reply=FRESH)
    campaign.state.turn = 5
    _every_axis_commander_said(campaign, OLD_RANT)
    sent = await campaign._communiques(TurnReport(turn=5))
    assert len(sent) == 1
    assert sent[0]["text"] == FRESH


async def test_earlier_signals_are_not_replayed_as_chat_turns():
    # Back-to-back assistant turns of his own old pop-ups were the copy
    # template. What was said reaches him as dated context, not as turns.
    captured: list = []
    campaign = _campaign(reply=FRESH, captured=captured)
    campaign.state.turn = 5
    _thread(campaign, "guderian", [
        (4, "player", "Take Smolensk."),
        (4, "commander", "Smolensk will fall."),
        (4, "commander", OLD_RANT),
    ])
    await campaign._one_communique("guderian", [])
    roles = [m["role"] for m in captured[0]["messages"]]
    assert roles == ["system", "user"]


async def test_a_stale_line_does_not_reach_the_communique_prompt():
    captured: list = []
    campaign = _campaign(reply=FRESH, captured=captured)
    campaign.state.turn = 11
    # nine weeks old: the Baranovichi argument that ran for four pop-ups
    _thread(campaign, "guderian", [(2, "player", "Hold the Berezina bridges until relieved.")])
    await campaign._one_communique("guderian", [])
    assert "Berezina" not in json.dumps(captured[0]["messages"])


def test_the_briefing_dates_each_exchange_and_marks_unprompted_signals():
    campaign = Campaign.new(DATA_DIR)
    campaign.state.turn = 5
    _thread(campaign, "guderian", [
        (4, "player", "Take Smolensk."),
        (5, "commander", OLD_RANT),
    ])
    text = build_briefing(campaign.state, "guderian")
    block = text.split("RECENT EXCHANGES")[1].split("YOUR FORCES")[0]
    assert 'week 4, C-in-C: "Take Smolensk."' in block
    assert "week 5, you (unprompted signal)" in block
