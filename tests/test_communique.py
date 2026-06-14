import random
from pathlib import Path

from commanders.communique import salient_events, select_communique_authors
from commanders.dossier import load_dossiers
from engine.scenario import load_scenario
from engine.turn import TurnReport

DATA_DIR = Path(__file__).parent.parent / "data"


def setup():
    state = load_scenario(DATA_DIR)
    dossiers = load_dossiers(DATA_DIR)
    return state, dossiers


def victory_report():
    # guderian's XXIV Panzer carries Minsk (a victory-point city)
    return TurnReport(
        turn=2,
        combats=[
            {
                "region": "minsk",
                "attackers": ["xxiv_pz"],
                "defenders": ["sov_13a"],
                "odds": 6.0,
                "attacker_losses": 5,
                "defender_losses": 60,
                "outcome": "defender_retreated",
                "encircled": False,
            }
        ],
    )


def test_salient_events_reports_victory_city_capture():
    state, _ = setup()
    events = salient_events(state, victory_report(), "axis")
    assert "guderian" in events
    text = " ".join(events["guderian"]).lower()
    assert "minsk" in text
    assert "objective" in text  # flagged as a key objective (VP city)


def test_salient_events_reports_supply_crisis():
    state, _ = setup()
    for c in state.corps_for("strauss"):
        c.supply = 10
    events = salient_events(state, TurnReport(turn=2), "axis")
    assert "strauss" in events
    assert any("supply" in line.lower() for line in events["strauss"])


def test_salient_events_empty_for_quiet_commander():
    state, _ = setup()
    events = salient_events(state, victory_report(), "axis")
    assert "weichs" not in events  # nothing happened to weichs


def test_no_author_when_chance_is_zero():
    state, dossiers = setup()
    authors = select_communique_authors(
        state, dossiers, victory_report(), "axis",
        random.Random(1), base_chance=0.0, max_count=1,
    )
    assert authors == []


def test_one_author_when_chance_is_one():
    state, dossiers = setup()
    authors = select_communique_authors(
        state, dossiers, TurnReport(turn=2), "axis",
        random.Random(1), base_chance=1.0, max_count=1,
    )
    assert len(authors) == 1
    cid, salient = authors[0]
    assert dossiers[cid].side == "axis"


def test_salient_commander_is_favored():
    # across many seeds, the commander with a salient victory should win the
    # selection far more often than a flat draw among the 5 active axis commanders
    state, dossiers = setup()
    wins = 0
    trials = 200
    for seed in range(trials):
        authors = select_communique_authors(
            state, dossiers, victory_report(), "axis",
            random.Random(seed), base_chance=1.0, max_count=1,
        )
        if authors[0][0] == "guderian":
            wins += 1
    assert wins > trials * 0.4  # far above the ~1/9 a flat draw would give


def test_selection_is_deterministic_per_seed():
    state, dossiers = setup()
    a = select_communique_authors(state, dossiers, victory_report(), "axis",
                                  random.Random(7), base_chance=1.0, max_count=1)
    b = select_communique_authors(state, dossiers, victory_report(), "axis",
                                  random.Random(7), base_chance=1.0, max_count=1)
    assert a == b


def test_only_player_side_commanders_selected():
    state, dossiers = setup()
    for seed in range(20):
        authors = select_communique_authors(
            state, dossiers, TurnReport(turn=2), "axis",
            random.Random(seed), base_chance=1.0, max_count=1,
        )
        for cid, _ in authors:
            assert dossiers[cid].side == "axis"
