"""Phase 1 exit criterion: a scripted 24-turn campaign runs headless and
produces a historically plausible shape (deep axis advance, mounting losses,
no crashes, state stays serializable)."""

from pathlib import Path

from commanders.scripted import scripted_orders
from engine.scenario import load_scenario
from engine.state import GameState
from engine.turn import resolve_turn  # noqa: F401  (used via play_campaign)

DATA_DIR = Path(__file__).parent.parent / "data"

GERMAN_COMMANDERS = ["guderian", "hoth", "kluge", "strauss", "weichs"]
SOVIET_COMMANDERS = ["pavlov", "timoshenko", "konev", "zhukov"]


def play_campaign(turns=24):
    state = load_scenario(DATA_DIR)
    for _ in range(turns):
        orders = {}
        for cmd in GERMAN_COMMANDERS:
            orders[cmd] = scripted_orders(state, cmd, stance="advance", goal="moscow")
        for cmd in SOVIET_COMMANDERS:
            orders[cmd] = scripted_orders(state, cmd, stance="defend")
        resolve_turn(state, orders)
    return state


def test_campaign_completes_24_turns():
    state = play_campaign()
    assert state.turn == 25
    assert state.date.isoformat() == "1941-12-07"


def test_axis_advances_deep_into_soviet_territory():
    state = play_campaign()
    assert state.control["minsk"] == "axis"
    assert state.control["smolensk"] == "axis"


def test_war_is_costly_for_both_sides():
    # measure against the forces actually committed (starting OOB plus any
    # reinforcements that can arrive), not a magic number — both sides should
    # end below their full committed strength
    start = load_scenario(DATA_DIR)
    max_axis = sum(c.strength for c in start.corps.values() if c.side == "axis")
    max_soviet = sum(c.strength for c in start.corps.values() if c.side == "soviet")
    max_soviet += sum(
        r["corps"]["strength"] for r in start.reinforcements
        if r["corps"]["side"] == "soviet"
    )
    state = play_campaign()
    axis_strength = sum(c.strength for c in state.corps.values() if c.side == "axis")
    soviet_strength = sum(c.strength for c in state.corps.values() if c.side == "soviet")
    assert axis_strength < max_axis  # axis took losses
    assert soviet_strength < max_soviet  # soviets took losses despite reinforcements


def test_no_corps_vanish_and_state_round_trips():
    state = play_campaign()
    assert len(state.corps) >= 30  # original 30 plus any arrived reinforcements
    assert "xxiv_pz" in state.corps and "sov_49a" in state.corps
    assert GameState.from_dict(state.to_dict()).to_dict() == state.to_dict()
