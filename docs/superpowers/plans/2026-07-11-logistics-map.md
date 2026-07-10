# Logistics Map Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show supply on the situation map — colour corps counters by supply band and shade friendly regions by truck-leg distance from the railhead.

**Architecture:** A thin pure function exposes the truck-leg mapping the supply model already computes; the server adds it to the snapshot; the frontend colours counters (from `corps.supply`) and draws a subtle always-on region gradient (from `supply_legs`). Visualization only — the supply model is unchanged.

**Tech Stack:** Python (FastAPI, pytest), vanilla JS SVG rendering, CSS.

Spec: `docs/superpowers/specs/2026-07-11-logistics-map-design.md`.

---

### Task 1: Expose `supply_legs` from the supply model

**Files:**
- Modify: `engine/supply.py`
- Test: `tests/test_supply.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_supply.py` (it already imports from `engine.supply` and has `make_map`):

```python
def test_supply_legs_counts_truck_legs_from_the_railhead():
    from engine.supply import supply_legs
    game_map = make_map()  # source -rail- a -rail- b -road- c -road- d -road- e
    control = {r: "axis" for r in ["source", "a", "b", "c", "d", "e"]}
    converted = {"source", "a"}  # railhead reaches 'a'
    legs = supply_legs(game_map, control, "axis", ["source"], converted)
    assert legs["source"] == 0
    assert legs["a"] == 0      # on the converted railhead
    assert legs["b"] == 1      # one leg past it (rail exists but b unconverted)
    assert legs["c"] == 2      # road leg
    assert legs["e"] == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_supply.py::test_supply_legs_counts_truck_legs_from_the_railhead -v`
Expected: FAIL — `ImportError: cannot import name 'supply_legs'`.

- [ ] **Step 3: Write minimal implementation**

Add to `engine/supply.py` (below `compute_supply`):

```python
def supply_legs(
    game_map: GameMap,
    control: dict[str, str],
    side: str,
    sources: list[str],
    converted: set[str] | None = None,
) -> dict[str, int]:
    """Minimum truck legs from a supply source to each friendly region (0 = on
    the converted railhead, N = N legs beyond it). Powers the map supply
    gradient; a thin public view of the value compute_supply already derives."""
    return _truck_legs_from_sources(game_map, control, side, sources, converted)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_supply.py -v`
Expected: PASS (all supply tests).

- [ ] **Step 5: Commit**

```bash
git add engine/supply.py tests/test_supply.py
git commit -m "Expose supply_legs: truck-leg distance per friendly region"
```

---

### Task 2: Add `supply_legs` to the snapshot

**Files:**
- Modify: `server/app.py` (the `snapshot` function; `railhead`/`supply_sources` are already resolved there)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py`:

```python
async def test_snapshot_exposes_supply_legs(api):
    snap = (await api.post("/api/game/new")).json()
    legs = snap["supply_legs"]
    assert isinstance(legs, dict)
    # rear supply source sits on the railhead at zero legs
    assert any(v == 0 for v in legs.values())
    # every value is a non-negative int keyed by a region id on the map
    region_ids = {r["id"] for r in snap["regions"]}
    assert all(k in region_ids and isinstance(v, int) and v >= 0 for k, v in legs.items())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_server.py::test_snapshot_exposes_supply_legs -v`
Expected: FAIL — `KeyError: 'supply_legs'`.

- [ ] **Step 3: Write minimal implementation**

In `server/app.py`, add the import (with the other `engine.supply` import):

```python
from engine.supply import default_railhead_on_load, supply_legs
```

In `snapshot`, after the block that resolves `railhead` (the converted set for `side`) and using `state.supply_sources`, add to the returned dict:

```python
        "supply_legs": supply_legs(
            state.game_map, state.control, side,
            state.supply_sources.get(side, []), set(railhead),
        ),
```

Note: `railhead` in `snapshot` is a sorted list; wrap it with `set(...)`. Place the key alongside the existing `"railhead": railhead,` entry in the returned dict.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_server.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app.py tests/test_server.py
git commit -m "Snapshot: expose per-region supply_legs for the map gradient"
```

---

### Task 3: Colour corps counters by supply band

**Files:**
- Modify: `web/app.js` (the region-node loop, corps counter block ~L149-159)
- Modify: `web/style.css`

No unit test — verified live in the browser preview.

- [ ] **Step 1: Add a supply-band helper in `web/app.js`**

Add near the top-level helpers (e.g. beside `commanderSurname`):

```javascript
// Lowest supply in a stack decides the counter colour — one starving corps
// should light the whole marker. Thresholds match the supply model + the
// staff's "supply critical (<40)" language.
function supplyBand(corpsList) {
  const min = Math.min(...corpsList.map((c) => Number(c.supply)));
  if (min < 40) return "sup-red";
  if (min < 75) return "sup-amber";
  return "sup-green";
}
```

- [ ] **Step 2: Apply the band class to the own-counter group**

In the own-counter block, change:

```javascript
      const cls = ids.some((id) => highlightedCorps.has(id)) ? "counter own hl" : "counter own";
      const gc = el("g", { class: cls }, g);
```

to:

```javascript
      const base = ids.some((id) => highlightedCorps.has(id)) ? "counter own hl" : "counter own";
      const gc = el("g", { class: `${base} ${supplyBand(own)}` }, g);
```

- [ ] **Step 3: Add band colours in `web/style.css`**

```css
/* Supply band on own counters: fill of the counter rect. */
.counter.own.sup-green rect { fill: #2f4a2f; }
.counter.own.sup-amber rect { fill: #6b5a1f; }
.counter.own.sup-red   rect { fill: #6b2a24; }
```

(Adjust exact hues in preview; keep them readable against the map and legible with the existing white counter text.)

- [ ] **Step 4: Verify in the browser preview**

Start the dev server (preview_start with the game server config), open the map, and confirm counters are tinted by supply. If no live low-supply corps exist at turn 1, end a couple of turns (or inspect after advancing) so a spearhead drops below 75/40. Take a screenshot.

- [ ] **Step 5: Commit**

```bash
git add web/app.js web/style.css
git commit -m "Colour corps counters by supply band on the map"
```

---

### Task 4: Region supply gradient

**Files:**
- Modify: `web/app.js` (region-node loop, ~L128-132, before the base marker)
- Modify: `web/style.css`

No unit test — verified live in the browser preview.

- [ ] **Step 1: Read `supply_legs` into the render**

Near the top of the map render (where `railhead` is built ~L98), add:

```javascript
  const supplyLegs = snap.supply_legs || {};
```

- [ ] **Step 2: Draw a halo behind each friendly region node**

Inside the region loop, immediately after the group `g` is created and before the `railhead-ring`/base circle, add:

```javascript
    if (r.id in supplyLegs) {
      const legs = supplyLegs[r.id];
      // 0 legs = supplied (blue), fading to neutral, to dull red beyond supply
      const cls = legs === 0 ? "supply-halo l0"
                : legs === 1 ? "supply-halo l1"
                : legs === 2 ? "supply-halo l2"
                : "supply-halo l3";
      el("circle", { cx: r.x, cy: r.y, r: 15, class: cls }, g);
    }
```

- [ ] **Step 3: Style the halo in `web/style.css`**

```css
/* Supply gradient: a soft halo behind the region node. Always on, subtle. */
.supply-halo { pointer-events: none; }
.supply-halo.l0 { fill: #3a6ea533; }   /* on the railhead: supplied blue */
.supply-halo.l1 { fill: #3a6ea520; }
.supply-halo.l2 { fill: #7a6a4a18; }   /* neutral */
.supply-halo.l3 { fill: #7a2a2433; }   /* beyond supply: dull red */
```

- [ ] **Step 4: Verify and tune in the browser preview**

Reload the map. Confirm: the halo sits behind the node (not over the label/star/ring), reads as ambient texture not clutter, and the rear is blue while the spearhead fades toward red. Dial the opacity/radius here until it reads well in both light and dark (`resize_window` with each colorScheme). Screenshot.

- [ ] **Step 5: Commit**

```bash
git add web/app.js web/style.css
git commit -m "Draw a subtle supply gradient behind map regions"
```

---

## Self-Review

- **Spec coverage:** Task 1 = `supply_legs` pure fn; Task 2 = snapshot field; Task 3 = counter bands (green ≥75 / amber 40–74 / red <40); Task 4 = always-on subtle region gradient. All spec sections covered.
- **Types:** `supply_legs(game_map, control, side, sources, converted)` consistent across Tasks 1–2; snapshot key `supply_legs` consistent across Tasks 2–4; CSS classes `sup-*` and `supply-halo l0..l3` consistent within their tasks.
- **No placeholders:** every code step shows the code; preview steps name what to look at.
