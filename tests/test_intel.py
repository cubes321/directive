import random
from pathlib import Path

from commanders.dossier import load_dossiers
from commanders.intel import format_intel_lines, intercept
from engine.scenario import load_scenario

DATA_DIR = Path(__file__).parent.parent / "data"


def _state_with_soviet_orders():
    state = load_scenario(DATA_DIR)
    state.last_orders = {
        "pavlov": {
            "commander": "pavlov",
            "orders": [
                {"corps_id": "sov_3a", "posture": "attack", "objective": "suwalki"},
                {"corps_id": "sov_10a", "posture": "defend", "objective": None},
                {"corps_id": "sov_4a", "posture": "reserve", "objective": None},
            ],
            "dispatch": "",
            "reasoning": "",
        }
    }
    return state, load_dossiers(DATA_DIR)


def test_no_intercept_at_zero_chance():
    state, dossiers = _state_with_soviet_orders()
    assert intercept(state, dossiers, "axis", random.Random(1), chance=0.0) is None


def test_an_intercept_at_certainty_names_an_enemy_commander():
    state, dossiers = _state_with_soviet_orders()
    hit = intercept(state, dossiers, "axis", random.Random(1), chance=1.0)
    assert hit["commander"] == "pavlov"
    assert "Pavlov" in hit["name"]
    assert len(hit["orders"]) == 3


def test_the_same_seed_picks_the_same_commander():
    state, dossiers = _state_with_soviet_orders()
    state.last_orders["timoshenko"] = {
        "commander": "timoshenko", "orders": [], "dispatch": "", "reasoning": "",
    }
    a = intercept(state, dossiers, "axis", random.Random(7), chance=1.0)
    b = intercept(state, dossiers, "axis", random.Random(7), chance=1.0)
    assert a["commander"] == b["commander"]


def test_you_never_intercept_your_own_side():
    # last_orders holds BOTH sides; an axis roll must only ever read soviet traffic.
    state, dossiers = _state_with_soviet_orders()
    state.last_orders["guderian"] = {
        "commander": "guderian", "orders": [], "dispatch": "", "reasoning": "",
    }
    for seed in range(20):
        hit = intercept(state, dossiers, "axis", random.Random(seed), chance=1.0)
        assert dossiers[hit["commander"]].side == "soviet"


def test_no_intercept_when_the_enemy_issued_no_orders():
    state, dossiers = _state_with_soviet_orders()
    state.last_orders = {}
    assert intercept(state, dossiers, "axis", random.Random(1), chance=1.0) is None


def test_a_commander_in_contact_is_preferred():
    # You intercept the sector you are facing, not a radio net 300 miles away.
    # pavlov's armies sit on the border facing the axis; zhukov is at Moscow.
    state, dossiers = _state_with_soviet_orders()
    state.last_orders["zhukov"] = {
        "commander": "zhukov", "orders": [], "dispatch": "", "reasoning": "",
    }
    picks = [
        intercept(state, dossiers, "axis", random.Random(s), chance=1.0)["commander"]
        for s in range(40)
    ]
    assert picks.count("pavlov") > picks.count("zhukov")


def test_the_decrypt_renders_regions_with_ids_and_names_the_corps():
    state, dossiers = _state_with_soviet_orders()
    hit = intercept(state, dossiers, "axis", random.Random(1), chance=1.0)
    lines = format_intel_lines(state, hit)
    assert any("[id: suwalki]" in ln for ln in lines)
    assert any("attack" in ln for ln in lines)
    assert any("reserve" in ln.lower() for ln in lines)


def test_an_advance_reads_as_advance_to_the_region():
    # The briefing's own staff options say "advance to X"; interpolating the
    # raw posture gave "advance Orsha", which reads as a different verb.
    # "attack X" is already grammatical and must stay as it is.
    state, dossiers = _state_with_soviet_orders()
    state.last_orders["pavlov"]["orders"] = [
        {"corps_id": "sov_3a", "posture": "advance", "objective": "suwalki"},
        {"corps_id": "sov_10a", "posture": "attack", "objective": "suwalki"},
    ]
    hit = intercept(state, dossiers, "axis", random.Random(1), chance=1.0)
    lines = format_intel_lines(state, hit)
    assert any("advance to Suwalki [id: suwalki]" in ln for ln in lines)
    assert any("attack Suwalki [id: suwalki]" in ln for ln in lines)


def test_the_decrypt_survives_a_corps_that_has_since_been_destroyed():
    # last_orders is a week old; a corps in it may be gone. Render the id
    # rather than crashing on a missing name.
    state, dossiers = _state_with_soviet_orders()
    state.last_orders["pavlov"]["orders"] = [
        {"corps_id": "ghost_army", "posture": "defend", "objective": None}
    ]
    hit = intercept(state, dossiers, "axis", random.Random(1), chance=1.0)
    assert any("ghost_army" in ln for ln in format_intel_lines(state, hit))
