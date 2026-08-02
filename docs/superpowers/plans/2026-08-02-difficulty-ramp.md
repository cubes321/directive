# Difficulty Ramp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Army Group Center wear out as it advances, so the campaign gets harder the closer it gets to Moscow, and make Moscow something you must hold rather than touch.

**Architecture:** Three independent engine changes plus a visibility pass. Marching past your railhead costs strength and organisation, scaled by supply shortfall and weather (`engine/turn.py`). A cadre ceiling derived from cumulative damage stops that loss being handed back by a turn in reserve (`engine/units.py`). Moscow requires three consecutive turns of control to win (`engine/state.py`, `engine/victory.py`). The engine stays pure — no LLM, network or file IO.

**Tech Stack:** Python 3.12, pytest, ruff. Vanilla JS frontend, no build step.

## Global Constraints

- Engine (`engine/`) is pure: no LLM imports, no network, no file IO.
- Seed every RNG. Never iterate a `set` where output order matters — sort first.
- Every multiplicative combat factor gets a floor.
- Use the venv interpreter explicitly: `.\.venv\Scripts\python.exe`
- `ruff check .` must be green before every commit.
- Tests are TDD-first: write the failing test, watch it fail, then implement.
- Design spec: `docs/superpowers/specs/2026-08-02-difficulty-ramp-design.md`
- Wastage applies to corps that **moved only**. Static corps — including
  pockets — are untouched, preserving
  `test_contained_pocket_is_not_destroyed_by_containment_alone`.

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `engine/units.py` | `damage_taken` field, derived `max_strength`, clamped `recover` | 1 |
| `tests/test_units.py` | cadre ceiling behaviour | 1 |
| `engine/turn.py` | `march_wastage` + the wastage resolution step | 2 |
| `tests/test_turn.py` | wastage behaviour | 2 |
| `engine/state.py` | `moscow_held_turns` field + serialization | 3 |
| `engine/victory.py` | hold requirement replaces instant win | 3 |
| `tests/test_victory.py` | hold behaviour | 3 |
| `commanders/briefing.py` | report the ceiling to commanders | 4 |
| `web/app.js` | FORCES tab shows `str/max` | 4 |
| `tests/test_briefing.py` | ceiling appears in briefing | 4 |

---

### Task 1: Cadre ceiling on Corps

A corps that has been ground down can be rebuilt, but never quite to what it was. The ceiling is **derived from cumulative damage**, not decremented per loss event — `_distribute_losses` applies combat damage one point at a time, so a per-call `round(1 * 0.25)` would round to zero every time and decay nothing.

**Files:**
- Modify: `engine/units.py`
- Test: `tests/test_units.py`

**Interfaces:**
- Consumes: nothing
- Produces: `Corps.damage_taken: int`, `Corps.max_strength: int` (read-only property), `Corps.take_losses(strength, organization)` now accumulates damage, `Corps.recover(organization, strength)` now clamps strength to `max_strength`. Module constants `CADRE_LOSS_FRACTION = 0.25`, `MIN_CADRE = 40`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_units.py`:

```python
def test_ceiling_falls_with_cumulative_damage():
    c = Corps(id="c", name="C", side="axis", kind="infantry",
              location="x", commander="cmd")
    assert c.max_strength == 100
    c.take_losses(strength=40)
    assert c.strength == 60
    assert c.max_strength == 90        # 100 - round(40 * 0.25)


def test_ceiling_is_the_same_however_the_damage_arrives():
    # _distribute_losses delivers combat damage one point at a time; a ceiling
    # decremented per call would round every one of those to zero.
    bulk = Corps(id="a", name="A", side="axis", kind="infantry",
                 location="x", commander="cmd")
    drip = Corps(id="b", name="B", side="axis", kind="infantry",
                 location="x", commander="cmd")
    bulk.take_losses(strength=20)
    for _ in range(20):
        drip.take_losses(strength=1)
    assert bulk.max_strength == drip.max_strength == 95


def test_a_corps_cannot_be_rebuilt_past_its_ceiling():
    c = Corps(id="c", name="C", side="axis", kind="infantry",
              location="x", commander="cmd")
    c.take_losses(strength=40)          # ceiling 90, strength 60
    for _ in range(20):
        c.recover(strength=5)
    assert c.strength == 90


def test_the_ceiling_never_falls_below_the_cadre_floor():
    # Note the corps must be rebuilt between maulings to accumulate damage past
    # 100: take_losses can only ever remove the strength that is actually there.
    from engine.units import MIN_CADRE
    c = Corps(id="c", name="C", side="axis", kind="infantry",
              location="x", commander="cmd")
    for _ in range(20):
        c.take_losses(strength=20)
        c.recover(strength=20)          # rebuilt each time, but the cadre is gone
    assert c.max_strength == MIN_CADRE


def test_damage_and_ceiling_survive_a_round_trip():
    c = Corps(id="c", name="C", side="axis", kind="infantry",
              location="x", commander="cmd")
    c.take_losses(strength=40)
    back = Corps.from_dict(c.to_dict())
    assert back.damage_taken == 40
    assert back.max_strength == 90


def test_a_save_predating_the_cadre_system_still_loads():
    old = {"id": "c", "name": "C", "side": "axis", "kind": "infantry",
           "location": "x", "commander": "cmd", "strength": 70,
           "organization": 80, "supply": 90, "experience": 50}
    c = Corps.from_dict(old)
    assert c.damage_taken == 0 and c.max_strength == 100
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_units.py -q
```

Expected: FAIL — `AttributeError: 'Corps' object has no attribute 'max_strength'`

- [ ] **Step 3: Implement**

Replace the body of `engine/units.py` below the docstring with:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

DESTROYED_THRESHOLD = 5
# A formation ground down can be rebuilt, but never to what it was: some of
# each loss is cadre - the officers and specialists that cannot be replaced by
# drafts. Derived from CUMULATIVE damage, never decremented per loss event,
# because _distribute_losses delivers combat damage one point at a time.
CADRE_LOSS_FRACTION = 0.25
MIN_CADRE = 40


@dataclass
class Corps:
    id: str
    name: str
    side: str  # axis | soviet
    kind: str  # panzer | motorized | infantry
    location: str  # region id
    commander: str  # commander id
    strength: int = 100
    organization: int = 100
    supply: int = 100
    experience: int = 50
    damage_taken: int = 0  # cumulative strength lost, ever

    @property
    def is_destroyed(self) -> bool:
        return self.strength < DESTROYED_THRESHOLD

    @property
    def max_strength(self) -> int:
        """The most this corps can ever be rebuilt to."""
        return max(MIN_CADRE, 100 - round(self.damage_taken * CADRE_LOSS_FRACTION))

    def take_losses(self, strength: int = 0, organization: int = 0) -> None:
        applied = min(self.strength, max(0, strength))
        self.strength -= applied
        self.damage_taken += applied
        self.organization = max(0, self.organization - organization)

    def recover(self, organization: int = 0, strength: int = 0) -> None:
        self.organization = min(100, self.organization + organization)
        self.strength = min(self.max_strength, self.strength + strength)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["max_strength"] = self.max_strength  # derived: for the UI and telemetry
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Corps:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
```

Note `from_dict` now filters unknown keys, which is what lets `to_dict` emit the
derived `max_strength` without breaking the round trip.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_units.py -q
```

Expected: PASS

- [ ] **Step 5: Run the full suite and lint**

```bash
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: PASS. If `tests/test_telemetry.py` or `tests/test_server.py` fail on an unexpected `max_strength` key, that is the new derived field appearing in `to_dict` — update the assertion to accept it rather than removing the field.

```bash
.\.venv\Scripts\python.exe -m ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add engine/units.py tests/test_units.py
git commit -m "Give a corps a ceiling it can never be rebuilt past"
```

---

### Task 2: Marching wastage

**Files:**
- Modify: `engine/turn.py`
- Test: `tests/test_turn.py`

**Interfaces:**
- Consumes: `Corps.take_losses` from Task 1 (wastage feeds `damage_taken`, so it lowers the ceiling like combat damage).
- Produces: `march_wastage(corps: Corps, weather: str) -> int`, constants `WASTAGE_SUPPLY_STEP = 25`, `WASTAGE_WEATHER = {"clear": 1.0, "mud": 2.0, "snow": 2.5}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_turn.py`:

```python
def test_marching_inside_your_supply_costs_nothing():
    from engine.turn import march_wastage
    c = _corps("c")           # supply defaults to 100
    assert march_wastage(c, "clear") == 0


def test_wastage_grows_with_the_supply_shortfall():
    from engine.turn import march_wastage
    assert march_wastage(_corps("a", supply=75), "clear") == 1
    assert march_wastage(_corps("b", supply=20), "clear") == 3
    assert march_wastage(_corps("c", supply=0), "clear") == 4


def test_wastage_is_worse_in_mud_and_snow():
    from engine.turn import march_wastage
    outrun = dict(supply=20)
    assert march_wastage(_corps("a", **outrun), "mud") == 6
    assert march_wastage(_corps("b", **outrun), "snow") == 8


def test_a_corps_that_marched_past_its_railhead_bleeds():
    data = state_data()
    data["corps"][0]["supply"] = 20
    data["control"]["center"] = "axis"     # empty friendly ground: an uncontested move
    s = GameState.from_dict(data)
    before = s.corps["ax1"].strength
    resolve_turn(s, orders(CorpsOrder("ax1", "advance", "center")))
    assert s.corps["ax1"].strength < before
    assert s.corps["ax1"].damage_taken > 0   # and it lowers the ceiling


def test_a_corps_that_stayed_put_does_not_waste_away():
    # The cost of standing still is the ground you are not taking, not blood.
    # This is also what keeps a contained pocket alive.
    data = state_data()
    s = GameState.from_dict(data)
    s.corps["ax1"].supply = 0
    before = s.corps["ax1"].strength
    resolve_turn(s, orders(CorpsOrder("ax1", "defend", None)))
    assert s.corps["ax1"].strength == before
```

Add a `supply` passthrough to the existing `_corps` helper at the top of `tests/test_turn.py`:

```python
def _corps(cid, strength=100, organization=100, supply=100):
    return Corps(id=cid, name=cid.upper(), side="axis", kind="infantry",
                 location="x", commander="c", strength=strength,
                 organization=organization, supply=supply)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_turn.py -q
```

Expected: FAIL — `ImportError: cannot import name 'march_wastage'`

- [ ] **Step 3: Implement the constants and the function**

In `engine/turn.py`, after the `POCKET_LOSS` constant, add:

```python
# Marching wears an army out even where nobody is shooting: breakdowns,
# straggling, sick horses, boots. Staying inside your railhead costs nothing;
# every step of supply shortfall costs, and the weather multiplies it. This is
# what makes the campaign harder as it gets further from the rail net, rather
# than harder on a date in the calendar.
WASTAGE_SUPPLY_STEP = 25
WASTAGE_WEATHER = {"clear": 1.0, "mud": 2.0, "snow": 2.5}


def march_wastage(corps: Corps, weather: str) -> int:
    """Strength a marching corps loses to non-combat wastage this turn."""
    shortfall = max(0, 100 - corps.supply)
    return round(shortfall / WASTAGE_SUPPLY_STEP * WASTAGE_WEATHER.get(weather, 1.0))
```

- [ ] **Step 4: Add the resolution step**

In `resolve_turn`, immediately after the recovery loop (step 3) and **before** the supply tick (step 4), insert:

```python
    # 3b. Marching wastage. Reinforcements that just arrived have not marched,
    # and a bounced corps went nowhere, so neither pays.
    marched = {
        m["corps"] for m in report.movements
        if not m.get("bounced") and not m.get("arrived")
    }
    for corps_id in sorted(marched):
        corps = state.corps.get(corps_id)
        if corps is None or corps.is_destroyed:
            continue
        loss = march_wastage(corps, state.weather)
        if loss:
            corps.take_losses(strength=loss, organization=loss * 2)
```

`sorted(marched)` because iteration order over a set must never affect output.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_turn.py -q
```

Expected: PASS, including the existing `test_contained_pocket_is_not_destroyed_by_containment_alone`.

- [ ] **Step 6: Run the full suite and lint**

```bash
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

Expected: PASS and `All checks passed!`. `tests/test_determinism.py` must still pass — if it fails, something is iterating an unsorted set.

- [ ] **Step 7: Commit**

```bash
git add engine/turn.py tests/test_turn.py
git commit -m "Make marching past the railhead cost blood"
```

---

### Task 3: Moscow must be held

**Files:**
- Modify: `engine/state.py`, `engine/turn.py`, `engine/victory.py`
- Test: `tests/test_victory.py`

**Interfaces:**
- Consumes: nothing from Tasks 1-2.
- Produces: `GameState.moscow_held_turns: int` (serialized), `engine.victory.MOSCOW_HOLD_TURNS = 3`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_victory.py`, add `moscow_held` to `make_state` and replace the instant-victory test:

```python
def make_state(turn=1, moscow="soviet", axis_vp=5, moscow_held=0):
    # ... existing body unchanged, but add to the data dict:
    #     "moscow_held_turns": moscow_held,
```

Then replace `test_taking_moscow_is_a_decisive_axis_victory_immediately` with:

```python
def test_taking_moscow_is_not_enough_on_its_own():
    # It used to be a decisive win the instant control flipped, so the Siberian
    # counteroffensive and the winter were scenery arriving after the credits.
    verdict = check_victory(make_state(turn=9, moscow="axis", moscow_held=1))
    assert verdict is None


def test_two_turns_of_moscow_is_still_not_enough():
    assert check_victory(make_state(turn=9, moscow="axis", moscow_held=2)) is None


def test_holding_moscow_three_turns_is_a_decisive_axis_victory():
    verdict = check_victory(make_state(turn=9, moscow="axis", moscow_held=3))
    assert verdict["winner"] == "axis"
    assert verdict["kind"] == "decisive"
```

And in `tests/test_turn.py`, add:

```python
def test_the_moscow_clock_counts_up_and_resets_when_it_is_lost():
    data = state_data()
    data["map"]["regions"].append({"id": "moscow", "name": "Moscow", "terrain": "urban"})
    data["map"]["edges"].append({"between": ["far_east", "moscow"],
                                 "road": "highway", "rail": True})
    data["control"]["moscow"] = "axis"
    s = GameState.from_dict(data)
    resolve_turn(s, {})
    resolve_turn(s, {})
    assert s.moscow_held_turns == 2
    s.control["moscow"] = "soviet"
    resolve_turn(s, {})
    assert s.moscow_held_turns == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_victory.py tests/test_turn.py -q
```

Expected: FAIL — `TypeError: make_state() got an unexpected keyword argument 'moscow_held'` and `AttributeError: 'GameState' object has no attribute 'moscow_held_turns'`

- [ ] **Step 3: Add the field to GameState**

In `engine/state.py`, after the `objectives` field (line ~35):

```python
    moscow_held_turns: int = 0  # consecutive turns the axis has held Moscow
```

In `from_dict`, after the `objectives=` line:

```python
            moscow_held_turns=data.get("moscow_held_turns", 0),
```

In `to_dict`, after the `"objectives":` line:

```python
            "moscow_held_turns": self.moscow_held_turns,
```

- [ ] **Step 4: Count the turns in resolve_turn**

In `engine/turn.py`, immediately before `state.turn += 1`:

```python
    # 5. The Moscow clock. A capital only counts when you can keep it.
    if state.control.get("moscow") == "axis":
        state.moscow_held_turns += 1
    else:
        state.moscow_held_turns = 0
```

- [ ] **Step 5: Require the hold in check_victory**

In `engine/victory.py`, add the constant below `FINAL_TURN`:

```python
MOSCOW_HOLD_TURNS = 3  # taking the city is not the same as keeping it
```

Replace the opening branch of `check_victory`:

```python
    if state.moscow_held_turns >= MOSCOW_HOLD_TURNS:
        return {
            "winner": "axis",
            "kind": "decisive",
            "reason": "Moscow has fallen and been held against the counterattack. "
                      "The Soviet state is decapitated.",
        }
```

Update the module docstring's first bullet to read:

```
- Axis holds Moscow for MOSCOW_HOLD_TURNS consecutive turns: decisive axis
  victory. Taking it is not enough - the Siberians are coming.
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_victory.py tests/test_turn.py -q
```

Expected: PASS

- [ ] **Step 7: Run the full suite and lint**

```bash
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

Expected: PASS and `All checks passed!`. `tests/test_objectives_balance.py` and `tests/test_campaign.py` play long campaigns and may now run to turn 24 where they previously ended early — read any failure before changing it; if a test asserted an early Moscow win, that assertion is what this task deliberately changes.

- [ ] **Step 8: Commit**

```bash
git add engine/state.py engine/turn.py engine/victory.py tests/test_victory.py tests/test_turn.py
git commit -m "Make Moscow something you have to hold"
```

---

### Task 4: Surface the ceiling

Wear the player cannot see is the game cheating.

**Files:**
- Modify: `commanders/briefing.py`, `web/app.js`
- Test: `tests/test_briefing.py`

**Interfaces:**
- Consumes: `Corps.max_strength` from Task 1; `max_strength` in the corps snapshot dict via `Corps.to_dict`.
- Produces: no new callable interfaces.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_briefing.py`:

```python
def test_briefing_reports_a_reduced_ceiling():
    state = load_scenario(DATA_DIR)
    worn = state.corps_for("guderian")[0]
    worn.take_losses(strength=40)          # ceiling drops to 90
    text = build_briefing(state, "guderian")
    line = next(ln for ln in text.splitlines() if worn.name in ln)
    assert "/90" in line                   # strength shown against the ceiling
    assert "cadre" in line.lower() or "never" in line.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_briefing.py -q
```

Expected: FAIL — the line still reads `strength 60/100`

- [ ] **Step 3: Report the ceiling in the briefing**

In `commanders/briefing.py`, `_corps_status`, replace the `return` with:

```python
    if corps.max_strength < 100:
        notes.append(f"cadre worn: can never be rebuilt past {corps.max_strength}")
    note = f" ({', '.join(notes)})" if notes else ""
    return (
        f"- {corps.name} [{corps.id}], {corps.kind}, at {_region_label(state, corps.location)}: "
        f"strength {corps.strength}/{corps.max_strength}, "
        f"organization {corps.organization}/100, "
        f"supply {corps.supply}/100{note}"
    )
```

Delete the old `note = ...` line that this replaces, so `note` is assigned once.

- [ ] **Step 4: Run the test to verify it passes**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_briefing.py -q
```

Expected: PASS

- [ ] **Step 5: Show it on the FORCES tab**

In `web/app.js` around line 536, the cells array currently reads:

```javascript
      const cells = [
        `${c.name}${c.kind === "panzer" ? " ⛭" : ""}`,
        regionName[c.location] || c.location,
        c.strength, c.organization, c.supply,
      ];
      cells.forEach((v, i) => {
        const td = document.createElement("td");
        td.textContent = v;
        if (i >= 2 && Number(v) < 40) td.className = "low";
```

Replace with:

```javascript
      const worn = Number(c.max_strength ?? 100) < 100;
      const cells = [
        `${c.name}${c.kind === "panzer" ? " ⛭" : ""}`,
        regionName[c.location] || c.location,
        worn ? `${c.strength}/${c.max_strength}` : c.strength,
        c.organization, c.supply,
      ];
      const numeric = [null, null, c.strength, c.organization, c.supply];
      cells.forEach((v, i) => {
        const td = document.createElement("td");
        td.textContent = v;
        if (i >= 2 && Number(numeric[i]) < 40) td.className = "low";
```

The separate `numeric` array matters: the existing check is `Number(v) < 40`, and
`Number("60/90")` is `NaN`, which would silently stop the low-strength
highlight from ever firing.

- [ ] **Step 6: Verify the frontend**

```bash
# start the preview via preview_start with name "directive", then in the page:
```

```javascript
snap.corps[0].max_strength = 90; snap.corps[0].strength = 60;
renderOob();
document.querySelector(".oob-table tbody tr").textContent
```

Expected: contains `60/90`. Confirm a corps with `max_strength` 100 still shows a bare number, and that a corps at strength 30 still gets the `low` class.

**Do not end a turn or start a new game in the preview** — `server/saves/campaign.json` is a live game.

- [ ] **Step 7: Run the full suite and lint, then commit**

```bash
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
git add commanders/briefing.py web/app.js tests/test_briefing.py
git commit -m "Show a commander what his divisions can never be again"
```

---

### Task 5: Measure and tune

The constants are first guesses. This task is where they get fixed.

**Files:**
- Create: `docs/superpowers/plans/2026-08-02-ramp-baseline.md` (measurements)
- Modify: `engine/turn.py`, `data/oob_1941.json` (only if the numbers say so)

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: no code interfaces; a recorded before/after and any constant changes.

- [ ] **Step 1: Record the new curve**

Write this to a scratch path outside the repo (do **not** commit it):

```python
"""Scripted 24-turn trace: does the ramp now bite before Moscow falls?"""
from pathlib import Path

from commanders.scripted import scripted_orders
from engine.scenario import load_scenario
from engine.turn import resolve_turn
from engine.weather import weather_for_turn

GER = ["guderian", "hoth", "kluge", "strauss", "weichs"]
SOV = ["pavlov", "timoshenko", "konev", "zhukov"]

state = load_scenario(Path("data"))
prev = {c.id: c.strength for c in state.corps.values()}
lost = regained = 0
moscow_fell = None

print("turn  wx     axis_str  sov_str  ratio  axis_n sov_n  moscow  held")
for _ in range(24):
    orders = {c: scripted_orders(state, c, stance="advance", goal="moscow") for c in GER}
    orders |= {c: scripted_orders(state, c, stance="defend") for c in SOV}
    t = state.turn
    resolve_turn(state, orders)
    for c in state.corps.values():
        delta = c.strength - prev.get(c.id, c.strength)
        if c.side == "axis":
            lost += -delta if delta < 0 else 0
            regained += delta if delta > 0 else 0
        prev[c.id] = c.strength
    ax = [c for c in state.living_corps() if c.side == "axis"]
    sv = [c for c in state.living_corps() if c.side == "soviet"]
    a, s = sum(c.strength for c in ax), sum(c.strength for c in sv)
    if state.control.get("moscow") == "axis" and moscow_fell is None:
        moscow_fell = t
    print(f" T{t:<4} {weather_for_turn(t):<6} {a:>7}  {s:>7}  {a / max(s, 1):>5.2f}"
          f"  {len(ax):>5}  {len(sv):>4}   {state.control.get('moscow'):<7}"
          f" {state.moscow_held_turns}")

print(f"\nMoscow first fell: turn {moscow_fell}")
print(f"axis took {lost} damage, regenerated {regained}")
print("ceilings:", sorted(c.max_strength for c in state.corps.values() if c.side == "axis"))
```

```bash
$env:PYTHONPATH="E:\programming\ww2 game"; .\.venv\Scripts\python.exe <scratch>\ramp_trace.py
```

The pre-change baseline to compare against:

```
 T7    clear    1391    1135   1.23      14      16
 T14   clear    1388    1299   1.07      14      18
 T19   mud      1358    1347   1.01      14      19   <- Moscow fell
 T24   snow     1358    1447   0.94      14      20
axis took 71 strength of damage over 24 turns, regenerated 29 free
```

- [ ] **Step 2: Judge against the target**

The target from the spec is that a well-played campaign is a **near-miss**: the axis reaches the gates and is stopped, or takes Moscow and cannot hold it three turns.

- If Moscow now falls **later than turn 22** or not at all, the schedule needs no re-timing — go to Step 4.
- If Moscow still falls around turn 19, the ramp is still too late: move the Siberian arrivals in `data/oob_1941.json` earlier (turns 16/18/20 → 13/15/17) and re-run.
- If the axis is destroyed or cannot pass Smolensk, wastage is too steep: raise `WASTAGE_SUPPLY_STEP` from 25 toward 35, which shallows the whole curve.

- [ ] **Step 3: Check the specific risks the spec flagged**

- **Double punishment:** a corps at supply 20 already fights at a 0.2 power factor and now bleeds 3/turn as well. Confirm a spearhead that outruns its railhead is *punished*, not *deleted* — it should be able to pull back and recover, at a cost.
- **`CADRE_LOSS_FRACTION` too harsh:** confirm the axis can still reach Moscow at all. If every corps is at the `MIN_CADRE` floor by turn 15, drop the fraction to 0.15.

- [ ] **Step 4: Write up and commit the measurements**

Record the before/after tables and any constants changed, with the reasoning, in `docs/superpowers/plans/2026-08-02-ramp-baseline.md`.

```bash
git add docs/superpowers/plans/2026-08-02-ramp-baseline.md engine/turn.py data/oob_1941.json
git commit -m "Tune the ramp against the 24-turn trace"
```

- [ ] **Step 5: Live playtest**

Run a headless LLM playtest of at least 8 turns. **Use a scratch save path** — `play_campaign.py` writes `server/saves/campaign.json` on every turn and will destroy a live game. Confirm commanders react in character to worn formations, and that the briefing's cadre note appears in their reasoning.

---

## Notes

- Tasks 1, 2 and 3 are independent of each other in code and could be done in
  any order; 4 needs 1, and 5 needs all of them.
- The design spec's rejected options — a player-allocated replacement pool, and
  wastage for static corps — are deliberate omissions. Do not add them.
