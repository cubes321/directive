"""Scenario assembly: data files -> initial GameState.

Initial control: regions where axis corps stand are axis; everything else is
soviet (the campaign opens on the frontier). Corps not given explicit strength
or supply in the OOB start at full.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.state import GameState
from engine.supply import initial_railhead

DEFAULT_SEED = 1941


def load_scenario(data_dir: Path, seed: int = DEFAULT_SEED) -> GameState:
    map_data = json.loads((data_dir / "map_agc.json").read_text(encoding="utf-8"))
    oob = json.loads((data_dir / "oob_1941.json").read_text(encoding="utf-8"))
    objectives = json.loads((data_dir / "objectives_1941.json").read_text(encoding="utf-8"))

    axis_starts = {c["location"] for c in oob["corps"] if c["side"] == "axis"}
    control = {
        r["id"]: ("axis" if r["id"] in axis_starts else "soviet") for r in map_data["regions"]
    }
    state = GameState.from_dict(
        {
            "map": map_data,
            "corps": oob["corps"],
            "control": control,
            "supply_sources": oob["supply_sources"],
            "turn": 1,
            "seed": seed,
            "reinforcements": oob.get("reinforcements", []),
            "objectives": objectives.get("objectives", []),
        }
    )
    # the railhead starts at the pre-war rail network behind each side's front
    for side, srcs in state.supply_sources.items():
        state.railheads[side] = sorted(
            initial_railhead(state.game_map, state.control, side, srcs)
        )
    return state
