"""Scenario assembly: data files -> initial GameState.

Initial control: regions where axis corps stand are axis; everything else is
soviet (the campaign opens on the frontier). Corps not given explicit strength
or supply in the OOB start at full.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.state import GameState

DEFAULT_SEED = 1941


def load_scenario(data_dir: Path, seed: int = DEFAULT_SEED) -> GameState:
    map_data = json.loads((data_dir / "map_agc.json").read_text(encoding="utf-8"))
    oob = json.loads((data_dir / "oob_1941.json").read_text(encoding="utf-8"))

    axis_starts = {c["location"] for c in oob["corps"] if c["side"] == "axis"}
    control = {
        r["id"]: ("axis" if r["id"] in axis_starts else "soviet") for r in map_data["regions"]
    }
    return GameState.from_dict(
        {
            "map": map_data,
            "corps": oob["corps"],
            "control": control,
            "supply_sources": oob["supply_sources"],
            "turn": 1,
            "seed": seed,
        }
    )
