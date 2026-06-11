from pathlib import Path

from commanders.intent import soviet_directives
from engine.scenario import load_scenario

DATA_DIR = Path(__file__).parent.parent / "data"


def test_frontier_stage_focuses_on_holding_the_border():
    state = load_scenario(DATA_DIR)
    directives = soviet_directives(state)
    assert set(directives) == {"pavlov", "timoshenko", "konev", "zhukov"}
    assert "Minsk" in directives["pavlov"]


def test_dnieper_stage_after_minsk_falls():
    state = load_scenario(DATA_DIR)
    state.control["minsk"] = "axis"
    directives = soviet_directives(state)
    assert "Smolensk" in directives["timoshenko"]


def test_moscow_stage_after_smolensk_falls():
    state = load_scenario(DATA_DIR)
    state.control["minsk"] = "axis"
    state.control["smolensk"] = "axis"
    directives = soviet_directives(state)
    assert "Moscow" in directives["zhukov"]
    # everyone shifts to the capital's defense
    assert all("Moscow" in d for d in directives.values())
