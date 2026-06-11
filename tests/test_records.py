from pathlib import Path

from commanders.dossier import load_dossiers
from commanders.records import update_track_records
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
