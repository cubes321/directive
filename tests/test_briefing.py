from pathlib import Path

from commanders.briefing import build_briefing
from engine.scenario import load_scenario
from engine.state import GameState

DATA_DIR = Path(__file__).parent.parent / "data"


def _stacking_state():
    # home --(rail)-- hub, home --(rail)-- spur. Guderian sits at home; hub is
    # already packed with three friendly corps (the stacking limit).
    return GameState.from_dict({
        "map": {
            "regions": [{"id": r, "name": r.title(), "terrain": "clear"}
                        for r in ["home", "hub", "spur"]],
            "edges": [
                {"between": ["home", "hub"], "road": "highway", "rail": True},
                {"between": ["home", "spur"], "road": "highway", "rail": True},
            ],
        },
        "corps": [
            {"id": "g1", "name": "G1", "side": "axis", "kind": "panzer",
             "location": "home", "commander": "guderian"},
            {"id": "f1", "name": "F1", "side": "axis", "kind": "infantry",
             "location": "hub", "commander": "kluge"},
            {"id": "f2", "name": "F2", "side": "axis", "kind": "infantry",
             "location": "hub", "commander": "kluge"},
            {"id": "f3", "name": "F3", "side": "axis", "kind": "infantry",
             "location": "hub", "commander": "kluge"},
        ],
        "control": {"home": "axis", "hub": "axis", "spur": "axis"},
        "supply_sources": {"axis": ["home"]},
        "turn": 1, "seed": 1,
    })


def test_briefing_marks_full_regions_in_range():
    text = build_briefing(_stacking_state(), "guderian")
    in_range = next(ln for ln in text.splitlines() if ln.strip().startswith("In range"))
    assert "Hub [id: hub] (FULL" in in_range   # 3 friendly corps -> no room
    assert "Spur [id: spur]" in in_range
    assert "Spur [id: spur] (FULL" not in in_range  # empty -> not marked


def _rear_area_state():
    # rear -- mid -- far -- front, all highway (cost 2). An infantry corps in the
    # rear has 4 MP, so mid and far are in range but the front is not. Everything
    # it can reach is already friendly ground.
    return GameState.from_dict({
        "map": {
            "regions": [{"id": r, "name": r.title(), "terrain": "clear"}
                        for r in ["rear", "mid", "far", "front"]],
            "edges": [
                {"between": ["rear", "mid"], "road": "highway", "rail": True},
                {"between": ["mid", "far"], "road": "highway", "rail": True},
                {"between": ["far", "front"], "road": "highway", "rail": True},
            ],
        },
        "corps": [
            {"id": "r1", "name": "R1", "side": "axis", "kind": "infantry",
             "location": "rear", "commander": "strauss"},
            {"id": "s1", "name": "S1", "side": "soviet", "kind": "infantry",
             "location": "front", "commander": "pavlov"},
        ],
        "control": {"rear": "axis", "mid": "axis", "far": "axis", "front": "soviet"},
        "supply_sources": {"axis": ["rear"], "soviet": ["front"]},
        "turn": 1, "seed": 1,
    })


def test_staff_suggests_closing_up_when_no_enemy_is_in_range():
    # A move option was only ever generated for enemy-held ground, so a corps
    # sitting behind the front got "hold current position" as its ONLY staff
    # option - and cautious commanders duly sat there for turns on end.
    text = build_briefing(_rear_area_state(), "strauss")
    options = [ln for ln in text.splitlines() if ln.strip().startswith("*")]
    assert any("far" in ln for ln in options), f"no forward option offered: {options}"
    # and it must point at the region nearer the front, not the one behind it
    forward = next(ln for ln in options if "far" in ln or "mid" in ln)
    assert "mid" not in forward


def briefing_for_guderian():
    state = load_scenario(DATA_DIR)
    state.directives["guderian"] = "Drive on Minsk. Do not outrun your supply."
    return build_briefing(state, "guderian")


def test_briefing_includes_date_and_own_forces():
    text = briefing_for_guderian()
    assert "1941-06-22" in text
    assert "XXIV Panzer Corps" in text
    assert "Brest-Litovsk" in text


def test_briefing_includes_directive():
    text = briefing_for_guderian()
    assert "Drive on Minsk" in text


def test_briefing_includes_spotted_enemy_only():
    text = briefing_for_guderian()
    assert "Baranovichi" in text  # soviet 4th army spotted on his front
    assert "49th Army" not in text  # moscow garrison is unspotted
    assert "Zhukov" not in text


def test_briefing_reports_estimated_not_actual_strength():
    text = briefing_for_guderian()
    # sov_4a true strength is 90; the fog estimate band is 75 or 100
    assert "around 75" in text or "around 100" in text


def test_briefing_offers_staff_options_with_region_ids():
    text = briefing_for_guderian()
    assert "STAFF OPTIONS" in text
    assert "baranovichi" in text  # machine-usable region id present


def test_briefing_lists_legal_destinations_per_corps():
    text = briefing_for_guderian()
    # xxiv_pz at brest: baranovichi and pripyat are in range, minsk is not
    in_range_line = next(ln for ln in text.splitlines() if ln.strip().startswith("In range"))
    assert "baranovichi" in in_range_line
    assert "pripyat" in in_range_line
    assert "minsk" not in in_range_line


def test_briefing_only_covers_own_corps():
    text = briefing_for_guderian()
    assert "XXXIX Panzer Corps" not in text  # that's hoth's


def test_briefing_reports_a_reduced_ceiling():
    state = load_scenario(DATA_DIR)
    worn = state.corps_for("guderian")[0]
    worn.take_losses(strength=40)          # ceiling drops to 90
    text = build_briefing(state, "guderian")
    line = next(ln for ln in text.splitlines() if worn.name in ln)
    assert "/90" in line                   # strength shown against the ceiling
    assert "cadre" in line.lower() or "never" in line.lower()
