"""Measure rail-hop depth from axis sources to key regions, to calibrate
railhead conversion speed."""

from collections import deque
from pathlib import Path

from commanders.campaign import Campaign

ROOT = Path(__file__).parent
campaign = Campaign.load(ROOT / "server" / "saves" / "campaign.json")
state = campaign.state
sources = state.supply_sources["axis"]


def rail_depth_held(game_map, control, side, sources):
    """BFS depth over friendly-held rail edges only."""
    depth = {s: 0 for s in sources if control.get(s) == side}
    q = deque(depth)
    while q:
        here = q.popleft()
        for n in game_map.neighbors(here):
            if control.get(n) != side or n in depth:
                continue
            if game_map.edge(here, n).rail:
                depth[n] = depth[here] + 1
                q.append(n)
    return depth


depth = rail_depth_held(state.game_map, state.control, "axis", sources)
print(f"turn {state.turn}; axis sources {sources}")
print("\nrail-hop depth from source (held rail only):")
for cid in sorted(depth, key=lambda r: depth[r]):
    name = state.game_map.regions[cid].name
    print(f"  {depth[cid]:2}  {name}")

held_rail = [r for r, s in state.control.items() if s == "axis"]
unreached = [state.game_map.regions[r].name for r in held_rail if r not in depth]
print(f"\naxis-held regions NOT on the rail net: {unreached}")
