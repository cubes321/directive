"""Calibration of the authored objective schedule: a player who neglects OKH's
demands should be relieved, but only after several misses — not on the first."""

from pathlib import Path

from commanders.campaign import Campaign
from engine.objectives import advance_objectives

DATA_DIR = Path(__file__).parent.parent / "data"


def test_neglecting_objectives_relieves_you_after_several_misses():
    # Model a passive player: capture nothing, decline every diversion. Walk the
    # calendar applying objective outcomes exactly as play_turn would, and watch
    # standing bleed out.
    campaign = Campaign.new(DATA_DIR)
    misses = 0
    relieved_turn = None
    for turn in range(1, 25):
        campaign.state.turn = turn
        for event in advance_objectives(campaign.state, campaign.player_side):
            campaign.political_capital += event["capital_delta"]
            if event["capital_delta"] < 0:
                misses += 1
        for obj in campaign.state.objectives:
            if obj["status"] == "pending":
                if campaign.decide_diversion(obj["id"], accept=False)["cost"] > 0:
                    misses += 1
        if campaign.political_capital <= 0:
            relieved_turn = turn
            break

    assert relieved_turn is not None, "a player who meets nothing should be relieved"
    assert misses >= 3, "relief should take several misses, not one bad week"
    assert relieved_turn >= 5, "the player keeps command through the opening"


def test_meeting_every_objective_keeps_standing_healthy():
    # If the targets are captured on time, standing only ever rises.
    campaign = Campaign.new(DATA_DIR)
    start = campaign.political_capital
    for turn in range(1, 25):
        campaign.state.turn = turn
        # accept diversions and "capture" every objective's target
        for obj in campaign.state.objectives:
            if obj["status"] == "pending":
                campaign.decide_diversion(obj["id"], accept=True)
            if obj["status"] in ("active", "accepted"):
                campaign.state.control[obj["target"]] = campaign.player_side
        for event in advance_objectives(campaign.state, campaign.player_side):
            campaign.political_capital += event["capital_delta"]
    assert campaign.political_capital > start
    assert all(o["status"] in ("met", "scheduled") for o in campaign.state.objectives)
