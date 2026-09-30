import json
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


def _range_entries(text: str) -> list[str]:
    """The first corps' "In range" line, split into its per-region entries."""
    line = next(ln for ln in text.splitlines() if ln.strip().startswith("In range"))
    return line.split(": ", 1)[1].split(", ")


def _entry(entries: list[str], region_id: str) -> str:
    return next(e for e in entries if f"[id: {region_id}]" in e)


def _forward_corps_state():
    # Same line, but the corps stands at "far", next to the enemy: everything
    # friendly it can reach lies behind it.
    state = _rear_area_state()
    state.corps["r1"].location = "far"
    return state


def test_in_range_marks_enemy_ground_and_depth_behind_the_front():
    # A flat, alphabetical list gave a small model no way to tell the front
    # from the rear: Guderian "bypassed" the enemy by driving back to Siedlce,
    # Slutsk and Minsk, and "attacked" ground his own infantry already held.
    entries = _range_entries(build_briefing(_forward_corps_state(), "strauss"))
    assert "enemy-held" in _entry(entries, "front")
    assert "2 regions behind the front" in _entry(entries, "mid")
    assert "3 regions behind the front" in _entry(entries, "rear")


def test_in_range_flags_a_move_away_from_the_enemy():
    entries = _range_entries(build_briefing(_forward_corps_state(), "strauss"))
    assert "away from the enemy" in _entry(entries, "mid")
    assert "away from the enemy" in _entry(entries, "rear")
    assert "away from the enemy" not in _entry(entries, "front")


def test_in_range_does_not_call_a_move_up_from_the_rear_a_retreat():
    # Depth is relative to the front, direction relative to the corps: for a
    # corps parked in the rear, "2 behind the front" is still a step forward.
    entries = _range_entries(build_briefing(_rear_area_state(), "strauss"))
    assert "on the front line" in _entry(entries, "far")
    assert "away from the enemy" not in _entry(entries, "mid")
    assert "away from the enemy" not in _entry(entries, "far")


def test_in_range_lists_the_front_first():
    # Ids chosen so alphabetical order is exactly backwards (rear first) - the
    # plain line above happens to sort front-to-back by name and cannot tell.
    data = _rear_area_state().to_dict()
    rename = {"rear": "a_rear", "mid": "b_mid", "far": "c_far", "front": "z_front"}
    raw = json.loads(json.dumps(data))
    for region in raw["map"]["regions"]:
        region["id"] = rename[region["id"]]
    for edge in raw["map"]["edges"]:
        edge["between"] = [rename[r] for r in edge["between"]]
    raw["control"] = {rename[r]: s for r, s in raw["control"].items()}
    raw["supply_sources"] = {s: [rename[r] for r in rs] for s, rs in raw["supply_sources"].items()}
    for corps in raw["corps"]:
        corps["location"] = rename[corps["location"]]
    state = GameState.from_dict(raw)
    state.corps["r1"].location = "c_far"
    entries = _range_entries(build_briefing(state, "strauss"))
    order = [e.split("[id: ")[1].split("]")[0] for e in entries]
    assert order == ["z_front", "b_mid", "a_rear"]


def test_guderians_opening_briefing_marks_siedlce_as_the_rear():
    # The exact move from both playtests: XLVII Panzer Corps sent back to
    # Siedlce on 22 June "to strike at the enemy's logistical spine".
    state = load_scenario(DATA_DIR)
    entries = _range_entries(build_briefing(state, "guderian"))
    assert "away from the enemy" in _entry(entries, "siedlce")
    assert "enemy-held" in _entry(entries, "baranovichi")


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


def _with_intel(state):
    state.intel = {
        "soviet": {
            "commander": "guderian",
            "name": "Generaloberst Heinz Guderian",
            "role": "2nd Panzer Group",
            "orders": [
                {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
            ],
        }
    }
    return state


def test_a_soviet_briefing_carries_the_decrypt():
    state = _with_intel(load_scenario(DATA_DIR))
    text = build_briefing(state, "pavlov")
    assert "SIGNALS INTELLIGENCE" in text
    assert "Guderian" in text
    assert "[id: baranovichi]" in text


def test_the_other_side_sees_no_decrypt():
    # intel is keyed by side: soviet intelligence never appears in axis briefings.
    state = _with_intel(load_scenario(DATA_DIR))
    assert "SIGNALS INTELLIGENCE" not in build_briefing(state, "guderian")


def test_a_briefing_without_intel_is_unchanged():
    state = load_scenario(DATA_DIR)
    assert "SIGNALS INTELLIGENCE" not in build_briefing(state, "pavlov")


def test_the_decrypt_sits_above_the_staff_options():
    # divergence.py parses STAFF OPTIONS positionally from the end; keep the
    # new block above it.
    state = _with_intel(load_scenario(DATA_DIR))
    text = build_briefing(state, "pavlov")
    assert text.index("SIGNALS INTELLIGENCE") < text.index("STAFF OPTIONS")
