# Logistics visibility on the map — design

## Problem

The map already draws the *rail network* status — converted rail as a bright
ticked line (both endpoints in the railhead), unconverted rail faint, a
`railhead-ring` on each converted region ([web/app.js](../../../web/app.js) ~L98-131).
What it does **not** show is the *consequence* of that network:

- **Who is starving** — per-corps supply lives only on the FORCES tab and in
  dispatches; on the map, where the counters are, a supply-25 spearhead looks
  identical to a supply-100 one.
- **Where the supply cliff is** — supply is a gradient (100 → 75 → 50 → 25 → 20
  by truck-leg), but the map draws converted-vs-not as binary. The moment a
  spearhead crosses from "on the rail" to "two legs out and bleeding" — the whole
  drama of the railhead system — is invisible.

This directly supports the open supply/combat balance question: seeing supply on
the map makes overreach legible while playing.

## Scope (agreed)

Both halves: **coloured corps counters** (who's starving) **and a region
supply gradient** (where the cliff is). Gradient is **always on, subtle** — no
toggle. Exact opacity/colours tuned live in the browser preview.

## Data flow

`_truck_legs_from_sources` in [engine/supply.py](../../../engine/supply.py)
already computes minimum truck-legs to every friendly region — exactly the
gradient data. No new algorithm.

- **engine/supply.py**: add a thin public `supply_legs(game_map, control, side,
  sources, converted) -> dict[region_id, int]` that returns that mapping (wraps
  the existing internal `_truck_legs_from_sources`). Pure.
- **server/app.py `snapshot`**: add `supply_legs: {region_id: legs}` for the
  player's side, using the same converted railhead the snapshot already resolves
  for the `railhead` field. Regions not friendly/unreachable are omitted (drawn
  neutral). 0 = on the converted railhead; N = N truck-legs beyond it.

## Frontend ([web/app.js](../../../web/app.js), [web/style.css](../../../web/style.css))

- **Counter supply bands** — colour each corps counter by `corps.supply`, tied
  to the discrete supply steps and the existing "supply critical" staff flag
  (<40):
  - green ≥ 75 (on/one leg past the railhead, near full)
  - amber 40–74 (two legs, "strained")
  - red < 40 (three+ legs, at the combat floor; matches the staff's "critical")
- **Region gradient** — a low-opacity halo *behind* the region node keyed to
  `supply_legs`, anchored to the existing supplied-rail blue: 0 legs = soft blue
  "supplied" glow, fading through neutral at ~2 legs, to a dull red "beyond
  supply" at 3+. Drawn behind control colour, VP star, terrain marks and the
  railhead ring so it never fights them.
- Opacity/exact hues dialled in the live preview before commit.

## Testing

- **server**: snapshot includes `supply_legs`; a region on the converted
  railhead reports 0; a region two legs beyond reports 2; enemy/unreachable
  regions absent.
- **engine**: `supply_legs` returns 0 for source/converted regions and rising
  leg counts outward (mirrors the existing compute_supply expectations).
- **frontend**: verified live via the browser preview (counter colours across
  supply bands; gradient reads without clutter; light/dark).

## Out of scope (YAGNI)

No supply-view toggle (gradient is always-on/subtle). No per-corps supply
history or trend arrows. No change to the supply *model* — this is visualization
only; the supply/combat balance tuning is a separate effort.
