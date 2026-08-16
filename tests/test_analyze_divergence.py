"""The divergence dev tool's IO edges.

The pure scoring is covered in test_divergence.py; what is easy to get wrong
here is the empty run (the spec asks for a clear message and exit 0, not a
traceback or an empty table) and the self-labeling header, which reads a
tokens.jsonl that a hand-copied log directory may simply not have.
"""

import json as _json
from pathlib import Path

from analyze_divergence import main, menu_shape_line, models_used
from commanders.briefing import build_briefing
from commanders.divergence import menu_shapes
from engine.scenario import load_scenario

DATA_DIR = Path(__file__).parent.parent / "data"


def test_an_empty_log_dir_prints_a_message_and_exits_zero(tmp_path, capsys):
    (tmp_path / "campaign").mkdir()
    assert main(["campaign"], tmp_path) == 0
    assert "no commander transcripts" in capsys.readouterr().out


def test_a_missing_log_dir_prints_a_message_and_exits_zero(tmp_path, capsys):
    assert main(["nope"], tmp_path) == 0
    assert "no commander transcripts" in capsys.readouterr().out


def test_models_used_falls_back_when_tokens_jsonl_is_missing(tmp_path):
    assert models_used(tmp_path) == "unknown model"


def test_models_used_lists_every_model_in_the_run(tmp_path):
    (tmp_path / "tokens.jsonl").write_text(
        '{"model": "b"}\n{"model": "a"}\n\n{"model": "b"}\n', encoding="utf-8"
    )
    assert models_used(tmp_path) == "a, b"          # sorted: determinism


def test_prints_a_table_and_the_menu_shape_mix(tmp_path, capsys):
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": [
        {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
        {"corps_id": "xlvi_pz", "posture": "advance", "objective": "pripyat"},
        {"corps_id": "xlvii_pz", "posture": "defend", "objective": None},
    ]})
    run = tmp_path / "run-19410622-000000" / "campaign"
    run.mkdir(parents=True)
    (run / "turn01_guderian.json").write_text(_json.dumps({
        "commander": "guderian",
        "request": {"messages": [{"role": "user", "content": build_briefing(state, "guderian")}]},
        "attempts": [{"response": reply}],
        "orders": {"orders": []},
    }), encoding="utf-8")

    assert main([], tmp_path) == 0
    out = capsys.readouterr().out
    assert "run-19410622-000000" in out
    assert "guderian" in out and "ALL" in out
    # the menu-shape mix: without it a reader cannot tell whether two runs are
    # comparable, since `middle` is only reachable on a 3-option menu.
    assert "3 options: 3" in out


def test_menu_shape_line_names_every_length_present():
    state = load_scenario(DATA_DIR)
    briefing = build_briefing(state, "guderian")
    transcript = {"request": {"messages": [{"role": "user", "content": briefing}]}}
    line = menu_shape_line(menu_shapes([transcript]))
    assert "3 corps-briefings" in line
    assert "3 options: 3" in line
