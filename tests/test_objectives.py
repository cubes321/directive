from engine.objectives import advance_objectives
from engine.state import GameState


def make_state(turn=1, objectives=None, control=None):
    regions = [
        {"id": "minsk", "name": "Minsk", "terrain": "urban", "victory_points": 5},
        {"id": "smolensk", "name": "Smolensk", "terrain": "urban", "victory_points": 10},
        {"id": "gomel", "name": "Gomel", "terrain": "clear", "victory_points": 2},
    ]
    data = {
        "map": {"regions": regions, "edges": [
            {"between": ["minsk", "smolensk"], "road": "highway", "rail": True},
            {"between": ["smolensk", "gomel"], "road": "minor", "rail": False},
        ]},
        "corps": [],
        "control": control or {"minsk": "soviet", "smolensk": "soviet", "gomel": "soviet"},
        "supply_sources": {"axis": ["minsk"], "soviet": ["smolensk"]},
        "turn": turn,
        "seed": 1,
        "objectives": objectives or [],
    }
    return GameState.from_dict(data)


def capture_obj(**kw):
    base = dict(id="o1", kind="capture", title="Take Minsk", detail="",
                issued_turn=1, deadline_turn=4, target="minsk",
                reward=3, penalty=3, status="scheduled")
    base.update(kw)
    return base


def divert_obj(**kw):
    base = dict(id="d1", kind="divert", title="Turn south to Gomel", detail="",
                issued_turn=2, deadline_turn=6, target="gomel",
                reward=4, penalty=4, decline_penalty=2, status="scheduled")
    base.update(kw)
    return base


def test_capture_objective_activates_when_issued():
    s = make_state(turn=1, objectives=[capture_obj()])
    events = advance_objectives(s, player_side="axis")
    assert s.objectives[0]["status"] == "active"
    assert any(e["type"] == "issued" and e["id"] == "o1" for e in events)


def test_diversion_activates_as_pending_decision():
    s = make_state(turn=2, objectives=[divert_obj()])
    advance_objectives(s, player_side="axis")
    assert s.objectives[0]["status"] == "pending"


def test_not_yet_issued_objective_stays_scheduled():
    s = make_state(turn=1, objectives=[capture_obj(issued_turn=5)])
    events = advance_objectives(s, player_side="axis")
    assert s.objectives[0]["status"] == "scheduled"
    assert events == []


def test_capture_met_when_target_taken_grants_reward():
    s = make_state(turn=3, objectives=[capture_obj(status="active")],
                   control={"minsk": "axis", "smolensk": "soviet", "gomel": "soviet"})
    events = advance_objectives(s, player_side="axis")
    assert s.objectives[0]["status"] == "met"
    met = next(e for e in events if e["type"] == "met")
    assert met["capital_delta"] == 3


def test_capture_fails_when_deadline_passes_costs_penalty():
    # deadline 4; we are now at turn 5 with minsk still soviet
    s = make_state(turn=5, objectives=[capture_obj(status="active")])
    events = advance_objectives(s, player_side="axis")
    assert s.objectives[0]["status"] == "failed"
    failed = next(e for e in events if e["type"] == "failed")
    assert failed["capital_delta"] == -3


def test_accepted_diversion_met_on_capture():
    s = make_state(turn=4, objectives=[divert_obj(status="accepted")],
                   control={"minsk": "soviet", "smolensk": "soviet", "gomel": "axis"})
    advance_objectives(s, player_side="axis")
    assert s.objectives[0]["status"] == "met"


def test_pending_diversion_auto_declines_past_deadline():
    s = make_state(turn=7, objectives=[divert_obj(status="pending")])
    events = advance_objectives(s, player_side="axis")
    assert s.objectives[0]["status"] == "auto_declined"
    e = next(e for e in events if e["type"] == "auto_declined")
    assert e["capital_delta"] == -2  # decline_penalty


def test_closed_objectives_are_not_reprocessed():
    s = make_state(turn=6, objectives=[capture_obj(status="met")])
    assert advance_objectives(s, player_side="axis") == []


def test_capture_met_takes_priority_even_at_deadline():
    # target captured exactly as the deadline turn passes -> met, not failed
    s = make_state(turn=4, objectives=[capture_obj(status="active")],
                   control={"minsk": "axis", "smolensk": "soviet", "gomel": "soviet"})
    advance_objectives(s, player_side="axis")
    assert s.objectives[0]["status"] == "met"
