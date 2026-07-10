import random
from pathlib import Path

from commanders.campaign import Campaign
from commanders.dossier import load_dossiers
from commanders.records import _signal_warm_chance, update_morale, update_track_records
from engine.scenario import load_scenario
from engine.turn import TurnReport

DATA_DIR = Path(__file__).parent.parent / "data"


def setup():
    state = load_scenario(DATA_DIR)
    dossiers = load_dossiers(DATA_DIR)
    return state, dossiers


def test_victorious_attack_recorded_for_both_commanders():
    state, dossiers = setup()
    report = TurnReport(
        turn=1,
        combats=[
            {
                "region": "baranovichi",
                "attackers": ["xxiv_pz", "xlvi_pz"],
                "defenders": ["sov_4a"],
                "odds": 10.6,
                "attacker_losses": 1,
                "defender_losses": 40,
                "outcome": "defender_retreated",
                "encircled": False,
            }
        ],
    )
    update_track_records(state, report, dossiers)
    guderian = dossiers["guderian"].track_record
    pavlov = dossiers["pavlov"].track_record
    assert len(guderian) == 1
    assert "Baranovichi" in guderian[0]["summary"]
    assert "carried" in guderian[0]["summary"] or "took" in guderian[0]["summary"]
    assert len(pavlov) == 1
    assert "Baranovichi" in pavlov[0]["summary"]


def test_encirclement_noted_in_record():
    state, dossiers = setup()
    report = TurnReport(
        turn=4,
        combats=[
            {
                "region": "minsk",
                "attackers": ["xxiv_pz"],
                "defenders": ["sov_13a"],
                "odds": 8.0,
                "attacker_losses": 0,
                "defender_losses": 100,
                "outcome": "defender_retreated",
                "encircled": True,
            }
        ],
    )
    update_track_records(state, report, dossiers)
    assert "encircled" in dossiers["guderian"].track_record[0]["summary"].lower()


def test_quiet_turn_leaves_no_record():
    state, dossiers = setup()
    update_track_records(state, TurnReport(turn=2), dossiers)
    assert all(not d.track_record for d in dossiers.values())


# ── morale ──────────────────────────────────────────────────────────────────

def _combat(attacker_ids, region, outcome, encircled=False, defenders=None):
    return {
        "region": region, "terrain": "clear",
        "attackers": list(attacker_ids), "defenders": list(defenders or []),
        "odds": 2.0, "attacker_losses": 3, "defender_losses": 20,
        "outcome": outcome, "encircled": encircled,
        "attacker_details": [], "defender_details": [],
    }


def test_winning_an_attack_raises_confidence_and_relationship():
    c = Campaign.new(DATA_DIR)
    gud = "guderian"
    corps = c.state.corps_for(gud)
    before_conf = c.dossiers[gud].dynamic["confidence"]
    before_rel = c.dossiers[gud].dynamic["relationship"]
    rep = TurnReport(turn=c.state.turn, movements=[],
                     combats=[_combat([corps[0].id], corps[0].location, "defender_retreated")])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["confidence"] == before_conf + 1
    assert c.dossiers[gud].dynamic["relationship"] == before_rel + 1


def test_repulsed_attack_lowers_confidence_and_relationship():
    c = Campaign.new(DATA_DIR)
    gud = "guderian"
    corps = c.state.corps_for(gud)
    before_conf = c.dossiers[gud].dynamic["confidence"]
    before_rel = c.dossiers[gud].dynamic["relationship"]
    rep = TurnReport(turn=c.state.turn, movements=[],
                     combats=[_combat([corps[0].id], corps[0].location, "defender_held")])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["confidence"] == before_conf - 1
    assert c.dossiers[gud].dynamic["relationship"] == before_rel - 1


def test_resting_lowers_fatigue_and_fighting_raises_it():
    c = Campaign.new(DATA_DIR)
    gud = "guderian"
    corps = c.state.corps_for(gud)
    c.dossiers[gud].dynamic["fatigue"] = 5
    update_morale(c.state, TurnReport(turn=c.state.turn, combats=[], movements=[]),
                  c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["fatigue"] == 4
    rep = TurnReport(turn=c.state.turn, movements=[],
                     combats=[_combat([corps[0].id], corps[0].location, "defender_retreated")])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["fatigue"] == 5


def test_morale_clamps_between_0_and_10():
    c = Campaign.new(DATA_DIR)
    gud = "guderian"
    c.dossiers[gud].dynamic["confidence"] = 0
    corps = c.state.corps_for(gud)
    rep = TurnReport(turn=c.state.turn, movements=[],
                     combats=[_combat([corps[0].id], corps[0].location, "defender_held")])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["confidence"] == 0


def test_signal_warm_chance_is_lower_for_prouder_commanders():
    assert _signal_warm_chance(9) < _signal_warm_chance(3)
    assert 0.05 <= _signal_warm_chance(9) <= 0.9


def test_signalling_can_warm_relationship_subject_to_the_roll():
    c = Campaign.new(DATA_DIR)
    gud = "guderian"
    c.state.conversations.setdefault(gud, []).append(
        {"turn": c.state.turn, "role": "player", "text": "Well done, Heinz."}
    )
    before = c.dossiers[gud].dynamic["relationship"]
    rep = TurnReport(turn=c.state.turn, combats=[], movements=[])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(), _force_roll=0.0)
    assert c.dossiers[gud].dynamic["relationship"] == before + 1
