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
