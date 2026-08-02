import json
from pathlib import Path

from commanders.replay import load_recorded_orders, replay
from engine.scenario import load_scenario
from engine.state import GameState

DATA_DIR = Path(__file__).parent.parent / "data"


def _log(tmp_path, turn, commander, orders, **extra):
    entry = {
        "commander": commander,
        "turn": turn,
        "outcome": "ok",
        "orders": {"commander": commander, "orders": orders,
                   "dispatch": "", "reasoning": ""},
    }
    entry.update(extra)
    path = tmp_path / f"turn{turn:02d}_{commander}_{turn}00.json"
    path.write_text(json.dumps(entry), encoding="utf-8")


def test_recorded_orders_are_loaded_by_turn_and_commander(tmp_path):
    _log(tmp_path, 1, "guderian", [{"corps_id": "xxiv_pz", "posture": "attack",
                                    "objective": "baranovichi"}])
    _log(tmp_path, 1, "hoth", [{"corps_id": "xxxix_pz", "posture": "advance",
                                "objective": "vilnius"}])
    _log(tmp_path, 2, "guderian", [{"corps_id": "xxiv_pz", "posture": "defend",
                                    "objective": None}])
    loaded = load_recorded_orders(tmp_path)
    assert sorted(loaded) == [1, 2]
    assert sorted(loaded[1]) == ["guderian", "hoth"]
    assert loaded[1]["guderian"].orders[0].objective == "baranovichi"
    assert loaded[2]["guderian"].orders[0].posture == "defend"


def test_entries_without_usable_orders_are_skipped(tmp_path):
    # a fallback turn logs no order block; a staff call logs none either
    _log(tmp_path, 1, "guderian", [{"corps_id": "xxiv_pz", "posture": "defend",
                                    "objective": None}])
    (tmp_path / "turn01_staff_1.json").write_text(
        json.dumps({"commander": "staff", "turn": 1, "outcome": "ok"}), encoding="utf-8"
    )
    (tmp_path / "turn01_weichs_1.json").write_text(
        json.dumps({"commander": "weichs", "turn": 1, "outcome": "fallback",
                    "orders": {"commander": "weichs", "orders": []}}), encoding="utf-8"
    )
    loaded = load_recorded_orders(tmp_path)
    assert sorted(loaded[1]) == ["guderian"]


def test_replay_advances_the_campaign_and_reports_fidelity(tmp_path):
    # A recorded block covers every corps the commander had; validate_orders
    # treats a missing one as an error, so a partial record counts as a repair.
    state = load_scenario(DATA_DIR)
    own = state.corps_for("guderian")
    _log(tmp_path, 1, "guderian",
         [{"corps_id": own[0].id, "posture": "advance", "objective": "pripyat"}]
         + [{"corps_id": c.id, "posture": "defend", "objective": None} for c in own[1:]])
    result = replay(state, load_recorded_orders(tmp_path))
    assert result.turns == 1
    assert state.turn == 2
    assert result.salvaged[1] == 0          # every order was still legal
    assert result.fidelity == 1.0


def test_an_order_that_no_longer_fits_is_salvaged_and_counted(tmp_path):
    # The whole point of the harness: when a rules change makes a recorded
    # decision impossible, say so rather than silently dropping it.
    state = load_scenario(DATA_DIR)
    corps = state.corps_for("guderian")[0]
    _log(tmp_path, 1, "guderian", [{"corps_id": corps.id, "posture": "advance",
                                    "objective": "moscow"}])   # nowhere near it
    result = replay(state, load_recorded_orders(tmp_path))
    assert result.salvaged[1] == 1
    assert result.fidelity < 1.0


def test_replay_is_deterministic(tmp_path):
    corps_id = load_scenario(DATA_DIR).corps_for("guderian")[0].id
    _log(tmp_path, 1, "guderian", [{"corps_id": corps_id, "posture": "advance",
                                    "objective": "pripyat"}])
    recorded = load_recorded_orders(tmp_path)

    def play():
        s = load_scenario(DATA_DIR)
        replay(s, recorded)
        return GameState.from_dict(s.to_dict()).to_dict()

    assert play() == play()
