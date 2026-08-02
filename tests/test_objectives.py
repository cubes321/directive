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
    s = make_state(turn=6, objectives=[capture_obj(status="met")],
                   control={"minsk": "axis", "smolensk": "soviet", "gomel": "soviet"})
    assert advance_objectives(s, player_side="axis") == []


def test_met_objective_reopens_if_the_target_is_lost_before_the_deadline():
    # "met" used to latch on first capture, so the panel read ACHIEVED while the
    # place sat in enemy hands behind the front - which hid a real crisis.
    s = make_state(turn=3, objectives=[capture_obj(status="met")])  # minsk soviet again
    events = advance_objectives(s, player_side="axis")
    assert s.objectives[0]["status"] == "active"
    reopened = next(e for e in events if e["type"] == "reopened")
    assert reopened["capital_delta"] == -3   # the reward is handed back


def test_a_reopened_objective_can_be_met_again():
    s = make_state(turn=3, objectives=[capture_obj(status="met")])
    advance_objectives(s, player_side="axis")
    s.control["minsk"] = "axis"
    events = advance_objectives(s, player_side="axis")
    assert s.objectives[0]["status"] == "met"
    assert next(e for e in events if e["type"] == "met")["capital_delta"] == 3


def test_met_diversion_reopens_as_accepted_not_active():
    s = make_state(turn=4, objectives=[divert_obj(status="met")])  # gomel soviet
    advance_objectives(s, player_side="axis")
    assert s.objectives[0]["status"] == "accepted"


def test_an_objective_held_to_its_deadline_is_banked_for_good():
    # deadline 4, now turn 5: you delivered on time. Losing it later is a
    # different problem and must not claw back standing you earned.
    s = make_state(turn=5, objectives=[capture_obj(status="met")])
    events = advance_objectives(s, player_side="axis")
    assert s.objectives[0]["status"] == "met"
    assert not [e for e in events if e["capital_delta"]]


def test_losing_a_banked_objective_warns_once():
    s = make_state(turn=5, objectives=[capture_obj(status="met")])
    events = advance_objectives(s, player_side="axis")
    warning = next(e for e in events if e["type"] == "lost")
    assert warning["capital_delta"] == 0     # a signal, not a punishment
    assert "Minsk" in warning["text"]
    assert advance_objectives(s, player_side="axis") == []  # and never nags again


def test_capture_met_takes_priority_even_at_deadline():
    # target captured exactly as the deadline turn passes -> met, not failed
    s = make_state(turn=4, objectives=[capture_obj(status="active")],
                   control={"minsk": "axis", "smolensk": "soviet", "gomel": "soviet"})
    advance_objectives(s, player_side="axis")
    assert s.objectives[0]["status"] == "met"
