"""Show what supply becomes under the railhead model on the live save:
migrate the (pre-feature) save, advance the railhead one tick, recompute."""

from pathlib import Path

from commanders.campaign import Campaign
from engine.supply import (
    RAILHEAD_SPEED,
    advance_railhead,
    compute_supply,
    default_railhead_on_load,
)

ROOT = Path(__file__).parent
campaign = Campaign.load(ROOT / "server" / "saves" / "campaign.json")
state = campaign.state
sources = state.supply_sources["axis"]

converted = (
    set(state.railheads["axis"]) if "axis" in state.railheads
    else default_railhead_on_load(state.game_map, state.control, "axis", sources)
)
converted = advance_railhead(state.game_map, state.control, "axis", converted, RAILHEAD_SPEED)
fresh = compute_supply(
    state.game_map, state.control, sources,
    [c for c in state.corps.values() if c.side == "axis"], converted,
)

print(f"turn {state.turn}; railhead converts {RAILHEAD_SPEED}/turn")
print("converted railhead regions:",
      ", ".join(sorted(state.game_map.regions[r].name for r in converted)))
print("\naxis corps supply after next tick:")
for c in sorted((c for c in state.corps.values() if c.side == "axis"),
                key=lambda c: fresh[c.id]):
    region = state.game_map.regions[c.location].name
    bar = "#" * (fresh[c.id] // 10)
    print(f"  {c.name:22} at {region:14} {fresh[c.id]:3} {bar}")
