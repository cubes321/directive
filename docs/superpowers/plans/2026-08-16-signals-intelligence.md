# Signals Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Occasionally decrypt one enemy commander's full order set from last week, delivered to the player's inbox for him to distribute, and broadcast into the AI side's briefings.

**Architecture:** `GameState` persists last turn's validated orders. A new pure module `commanders/intel.py` rolls and selects an intercept, mirroring `commanders/communique.py`. `Campaign.play_turn` rolls once per side before briefings are built: the player's own intercept becomes an inbox dispatch and nothing more, while the AI side's goes into `state.intel` where `build_briefing` renders it.

**Tech Stack:** Python 3.13 stdlib, pytest, ruff; vanilla JS + CSS for the inbox card.

**Spec:** `docs/superpowers/specs/2026-08-02-signals-intelligence-design.md`

## Global Constraints

- Run everything with the venv interpreter: `.\.venv\Scripts\python.exe -m pytest -q` and `.\.venv\Scripts\python.exe -m ruff check .`. Both green before every commit.
- **`engine/` is pure**: rules, map, combat, supply, WEGO turns. Zero LLM imports, zero network, zero file IO. `commanders/intel.py` is likewise pure and seeded — no LLM call, no IO.
- **Determinism.** Seed every RNG. **Never iterate a `set` where output depends on order — sort first.** There is a cross-hash-seed regression test in `test_supply.py` because of a past bug here.
- **Fog discipline.** Only ever surface the player's own side. The snapshot is fog-filtered in `server/app.py`; a Soviet intercept must never reach the player by any path.
- **Briefings advise, the engine enforces.** The "not circulated" line is prose on a card, never a validation rule.
- TDD: the failing test comes first, is run, and is watched failing, before any implementation.
- Do not change `commanders/prompts.py` or the order schema. This feature adds context, not new order options.

---

### Task 1: Persist last week's validated orders

**Files:**
- Modify: `engine/state.py` (dataclass fields, `from_dict`, `to_dict`)
- Modify: `engine/turn.py` (`resolve_turn`)
- Test: `tests/test_state.py`, `tests/test_turn.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `GameState.last_orders: dict[str, dict]` — commander id to `CommanderOrders.to_dict()` output, i.e. `{"commander", "orders": [{"corps_id", "posture", "objective"}], "dispatch", "reasoning"}`.
  - `GameState.intel: dict[str, dict]` — side to the intercept that side's commanders should see this turn. Added here so serialization lives in one commit; it is populated in Task 4.

Validated orders, not raw: the decrypt must report what the engine actually acted on, including a salvaged set. That is what makes "100% correct" true rather than approximately true.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state.py`:

```python
def test_last_orders_and_intel_round_trip_through_a_save():
    state = load_scenario(DATA_DIR)
    state.last_orders = {
        "guderian": {
            "commander": "guderian",
            "orders": [{"corps_id": "xxiv_pz", "posture": "attack", "objective": "minsk"}],
            "dispatch": "Forward.",
            "reasoning": "",
        }
    }
    state.intel = {"soviet": {"commander": "guderian", "name": "G", "orders": []}}
    restored = GameState.from_dict(state.to_dict())
    assert restored.last_orders["guderian"]["orders"][0]["objective"] == "minsk"
    assert restored.intel["soviet"]["commander"] == "guderian"


def test_a_save_predating_signals_intelligence_still_loads():
    state = load_scenario(DATA_DIR)
    payload = state.to_dict()
    del payload["last_orders"]
    del payload["intel"]
    restored = GameState.from_dict(payload)
    assert restored.last_orders == {}
    assert restored.intel == {}
```

Check the existing imports at the top of `tests/test_state.py` before adding any — `GameState`, `load_scenario` and `DATA_DIR` may already be there.

Append to `tests/test_turn.py`:

```python
def test_resolve_turn_records_the_orders_it_acted_on():
    # The decrypt must report what the engine actually did, so this stores the
    # VALIDATED set - a salvaged order is what the corps really received.
    state = load_scenario(DATA_DIR)
    orders = {
        "guderian": CommanderOrders(
            commander="guderian",
            orders=[CorpsOrder(corps_id="xxiv_pz", posture="defend", objective=None)],
            dispatch="Holding.",
        )
    }
    resolve_turn(state, orders)
    assert state.last_orders["guderian"]["orders"][0]["posture"] == "defend"
    assert state.last_orders["guderian"]["dispatch"] == "Holding."
```

Check `tests/test_turn.py`'s existing imports for `CommanderOrders` / `CorpsOrder` before adding them.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_state.py tests/test_turn.py -q
```

Expected: FAIL — `AttributeError: 'GameState' object has no attribute 'last_orders'`

- [ ] **Step 3: Add the fields**

In `engine/state.py`, after the `moscow_held_turns` field:

```python
    # Last turn's VALIDATED orders per commander, for signals intelligence.
    # Validated rather than raw so a decrypt reports what the engine acted on.
    last_orders: dict[str, dict] = field(default_factory=dict)
    # This turn's intercept per side, for the briefing block. Only ever holds a
    # side's own intelligence; the player's copy goes to his inbox instead.
    intel: dict[str, dict] = field(default_factory=dict)
```

In `from_dict`, after `moscow_held_turns=...`:

```python
            last_orders={k: dict(v) for k, v in data.get("last_orders", {}).items()},
            intel={k: dict(v) for k, v in data.get("intel", {}).items()},
```

In `to_dict`, after `"moscow_held_turns": ...`:

```python
            "last_orders": {k: dict(v) for k, v in self.last_orders.items()},
            "intel": {k: dict(v) for k, v in self.intel.items()},
```

- [ ] **Step 4: Record the orders in `resolve_turn`**

In `engine/turn.py`, in `resolve_turn`, immediately before the final `return report`:

```python
    # Keep what we actually resolved, for next week's signals intelligence.
    # Written at the end so it reflects the set the engine really acted on.
    state.last_orders = {cid: o.to_dict() for cid, o in all_orders.items()}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_state.py tests/test_turn.py -q
```

Expected: PASS

- [ ] **Step 6: Run the full suite and lint**

```bash
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

- [ ] **Step 7: Commit**

```bash
git add engine/state.py engine/turn.py tests/test_state.py tests/test_turn.py
git commit -m "Keep last week's validated orders on the state"
```

---

### Task 2: Select an intercept

**Files:**
- Create: `commanders/intel.py`
- Test: `tests/test_intel.py`

**Interfaces:**
- Consumes: `GameState.last_orders` from Task 1; `Dossier` (`.name`, `.role`, `.side`).
- Produces:
  - `intercept(state, dossiers, side, rng, *, chance) -> dict | None` — the intercept **`side` made of its enemy**, or `None`. Shape: `{"commander": str, "name": str, "role": str, "orders": [{"corps_id", "posture", "objective"}]}`.
  - `INTEL_CHANCE = 0.25`
  - `CONTACT_MULTIPLIER = 4`
  - `format_intel_lines(state, hit) -> list[str]` — the rendered decrypt body, one line per corps, used by both the briefing block and the inbox card so they cannot drift.

Note the signature carries `dossiers`, unlike the spec's sketch: the name and role must be captured at selection time because `build_briefing(state, commander)` has no access to dossiers.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_intel.py`:

```python
import random
from pathlib import Path

from commanders.dossier import load_dossiers
from commanders.intel import format_intel_lines, intercept
from engine.scenario import load_scenario

DATA_DIR = Path(__file__).parent.parent / "data"


def _state_with_soviet_orders():
    state = load_scenario(DATA_DIR)
    state.last_orders = {
        "pavlov": {
            "commander": "pavlov",
            "orders": [
                {"corps_id": "sov_3a", "posture": "attack", "objective": "suwalki"},
                {"corps_id": "sov_10a", "posture": "defend", "objective": None},
                {"corps_id": "sov_4a", "posture": "reserve", "objective": None},
            ],
            "dispatch": "",
            "reasoning": "",
        }
    }
    return state, load_dossiers(DATA_DIR)


def test_no_intercept_at_zero_chance():
    state, dossiers = _state_with_soviet_orders()
    assert intercept(state, dossiers, "axis", random.Random(1), chance=0.0) is None


def test_an_intercept_at_certainty_names_an_enemy_commander():
    state, dossiers = _state_with_soviet_orders()
    hit = intercept(state, dossiers, "axis", random.Random(1), chance=1.0)
    assert hit["commander"] == "pavlov"
    assert "Pavlov" in hit["name"]
    assert len(hit["orders"]) == 3


def test_the_same_seed_picks_the_same_commander():
    state, dossiers = _state_with_soviet_orders()
    state.last_orders["timoshenko"] = {
        "commander": "timoshenko", "orders": [], "dispatch": "", "reasoning": "",
    }
    a = intercept(state, dossiers, "axis", random.Random(7), chance=1.0)
    b = intercept(state, dossiers, "axis", random.Random(7), chance=1.0)
    assert a["commander"] == b["commander"]


def test_you_never_intercept_your_own_side():
    # last_orders holds BOTH sides; an axis roll must only ever read soviet traffic.
    state, dossiers = _state_with_soviet_orders()
    state.last_orders["guderian"] = {
        "commander": "guderian", "orders": [], "dispatch": "", "reasoning": "",
    }
    for seed in range(20):
        hit = intercept(state, dossiers, "axis", random.Random(seed), chance=1.0)
        assert dossiers[hit["commander"]].side == "soviet"


def test_no_intercept_when_the_enemy_issued_no_orders():
    state, dossiers = _state_with_soviet_orders()
    state.last_orders = {}
    assert intercept(state, dossiers, "axis", random.Random(1), chance=1.0) is None


def test_a_commander_in_contact_is_preferred():
    # You intercept the sector you are facing, not a radio net 300 miles away.
    # pavlov's armies sit on the border facing the axis; zhukov is at Moscow.
    state, dossiers = _state_with_soviet_orders()
    state.last_orders["zhukov"] = {
        "commander": "zhukov", "orders": [], "dispatch": "", "reasoning": "",
    }
    picks = [
        intercept(state, dossiers, "axis", random.Random(s), chance=1.0)["commander"]
        for s in range(40)
    ]
    assert picks.count("pavlov") > picks.count("zhukov")


def test_the_decrypt_renders_regions_with_ids_and_names_the_corps():
    state, dossiers = _state_with_soviet_orders()
    hit = intercept(state, dossiers, "axis", random.Random(1), chance=1.0)
    lines = format_intel_lines(state, hit)
    assert any("[id: suwalki]" in ln for ln in lines)
    assert any("attack" in ln for ln in lines)
    assert any("reserve" in ln.lower() for ln in lines)


def test_the_decrypt_survives_a_corps_that_has_since_been_destroyed():
    # last_orders is a week old; a corps in it may be gone. Render the id
    # rather than crashing on a missing name.
    state, dossiers = _state_with_soviet_orders()
    state.last_orders["pavlov"]["orders"] = [
        {"corps_id": "ghost_army", "posture": "defend", "objective": None}
    ]
    hit = intercept(state, dossiers, "axis", random.Random(1), chance=1.0)
    assert any("ghost_army" in ln for ln in format_intel_lines(state, hit))
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_intel.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'commanders.intel'`

- [ ] **Step 3: Implement the module**

Create `commanders/intel.py`:

```python
"""Signals intelligence: whose orders got decrypted this week.

Pure and seeded, like commanders/communique.py — no LLM call and no IO. The
campaign layer decides what to do with the result; this module only picks.

WEGO simultaneity means a decrypt is always of LAST week's orders: briefings are
built before this turn's enemy orders exist. That is honest, and it is what
signals intelligence actually looked like — a step behind, but revealing of an
axis of effort, which persists.
"""

from __future__ import annotations

import random

from commanders.dossier import Dossier
from engine.state import GameState

INTEL_CHANCE = 0.25
CONTACT_MULTIPLIER = 4  # you intercept the sector you are facing


def _in_contact(state: GameState, commander: str, side: str) -> bool:
    """True when any of this commander's corps stands in or beside a region
    holding a living corps of ``side``."""
    own_regions = {
        c.location for c in state.corps_for(commander) if not c.is_destroyed
    }
    for region in sorted(own_regions):  # sorted: determinism
        near = [region, *sorted(state.game_map.neighbors(region))]
        for other in near:
            if any(c.side == side and not c.is_destroyed for c in state.corps_at(other)):
                return True
    return False


def intercept(
    state: GameState,
    dossiers: dict[str, Dossier],
    side: str,
    rng: random.Random,
    *,
    chance: float = INTEL_CHANCE,
) -> dict | None:
    """One roll: what ``side`` decrypted of its enemy's traffic last week.

    Returns the enemy commander's id, name, role and full order set, or None.
    Deterministic for a given rng.
    """
    if chance <= 0 or rng.random() >= chance:
        return None
    candidates = [
        cid
        for cid in sorted(state.last_orders)  # sorted: determinism
        if cid in dossiers
        and dossiers[cid].side != side
        and any(not c.is_destroyed for c in state.corps_for(cid))
    ]
    if not candidates:
        return None
    weights = [
        CONTACT_MULTIPLIER if _in_contact(state, cid, side) else 1 for cid in candidates
    ]
    cid = rng.choices(candidates, weights=weights, k=1)[0]
    return {
        "commander": cid,
        "name": dossiers[cid].name,
        "role": dossiers[cid].role,
        "orders": [dict(o) for o in state.last_orders[cid]["orders"]],
    }


def format_intel_lines(state: GameState, hit: dict) -> list[str]:
    """The decrypt body, one line per corps. Shared by the briefing block and
    the player's inbox card so the two can never drift apart."""
    lines = [f"  {hit['name']}, {hit['role']}:"]
    for order in hit["orders"]:
        corps = state.corps.get(order["corps_id"])
        who = corps.name if corps is not None else order["corps_id"]
        posture = order.get("posture")
        objective = order.get("objective")
        if posture in ("attack", "advance") and objective:
            region = state.game_map.regions.get(objective)
            where = f"{region.name} [id: {objective}]" if region else objective
            lines.append(f"    - {who}: {posture} {where}")
        elif posture == "reserve":
            lines.append(f"    - {who}: hold in reserve")
        else:
            lines.append(f"    - {who}: hold position")
    return lines
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_intel.py -q
```

Expected: PASS, 8 tests.

- [ ] **Step 5: Run the full suite and lint**

```bash
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

- [ ] **Step 6: Commit**

```bash
git add commanders/intel.py tests/test_intel.py
git commit -m "Select which enemy commander's traffic was decrypted"
```

---

### Task 3: Render the decrypt into a briefing

**Files:**
- Modify: `commanders/briefing.py` (`build_briefing`)
- Test: `tests/test_briefing.py`

**Interfaces:**
- Consumes: `GameState.intel` (Task 1), `format_intel_lines` (Task 2).
- Produces: a `SIGNALS INTELLIGENCE` block in the briefing, placed between `ENEMY CONTACTS` and `STAFF OPTIONS`.

**Do not disturb the `STAFF OPTIONS` section.** `commanders/divergence.py` parses it by exact phrasing, and its tests build real briefings specifically so a rephrasing fails loudly. Adding a section above it is fine; changing the option lines is not.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_briefing.py`:

```python
from commanders.intel import format_intel_lines  # noqa: F401  (kept parallel with intel)


def _with_intel(state):
    state.intel = {
        "soviet": {
            "commander": "guderian",
            "name": "Generaloberst Heinz Guderian",
            "role": "2nd Panzer Group",
            "orders": [
                {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
            ],
        }
    }
    return state


def test_a_soviet_briefing_carries_the_decrypt():
    state = _with_intel(load_scenario(DATA_DIR))
    text = build_briefing(state, "pavlov")
    assert "SIGNALS INTELLIGENCE" in text
    assert "Guderian" in text
    assert "[id: baranovichi]" in text


def test_the_other_side_sees_no_decrypt():
    # intel is keyed by side: soviet intelligence never appears in axis briefings.
    state = _with_intel(load_scenario(DATA_DIR))
    assert "SIGNALS INTELLIGENCE" not in build_briefing(state, "guderian")


def test_a_briefing_without_intel_is_unchanged():
    state = load_scenario(DATA_DIR)
    assert "SIGNALS INTELLIGENCE" not in build_briefing(state, "pavlov")


def test_the_decrypt_sits_above_the_staff_options():
    # divergence.py parses STAFF OPTIONS positionally from the end; keep the
    # new block above it.
    state = _with_intel(load_scenario(DATA_DIR))
    text = build_briefing(state, "pavlov")
    assert text.index("SIGNALS INTELLIGENCE") < text.index("STAFF OPTIONS")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_briefing.py -q
```

Expected: FAIL — `assert 'SIGNALS INTELLIGENCE' in text`

- [ ] **Step 3: Render the block**

In `commanders/briefing.py`, add the import at the top:

```python
from commanders.intel import format_intel_lines
```

In `build_briefing`, immediately after the `ENEMY CONTACTS` block and before the blank line preceding `STAFF OPTIONS`:

```python
    decrypt = state.intel.get(side)
    if decrypt:
        lines.append("")
        lines.append(
            "SIGNALS INTELLIGENCE (decrypt of last week's enemy traffic - "
            "believed accurate):"
        )
        lines.extend(format_intel_lines(state, decrypt))
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_briefing.py -q
```

Expected: PASS

- [ ] **Step 5: Run the full suite and lint**

```bash
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

`tests/test_divergence.py` must still pass — it builds real briefings. If it fails, you changed the `STAFF OPTIONS` section; revert that part.

- [ ] **Step 6: Commit**

```bash
git add commanders/briefing.py tests/test_briefing.py
git commit -m "Show a decrypt in the briefings of the side that made it"
```

---

### Task 4: Roll the intercept each turn

**Files:**
- Modify: `commanders/campaign.py` (`Campaign` field, `play_turn`)
- Test: `tests/test_campaign_session.py`

**Interfaces:**
- Consumes: `intercept`, `format_intel_lines`, `INTEL_CHANCE` (Task 2); `state.intel` (Task 1).
- Produces: `Campaign.intel_chance: float = INTEL_CHANCE`; an inbox dispatch `{"turn", "commander": "intel", "side", "text"}`.

**The asymmetry is the whole point of this task.** The player's own intercept goes to his **inbox only** — it must NOT enter any friendly briefing. The AI side's goes into `state.intel` so its commanders can act on it. There is no player on that side to distribute it.

The roll happens **before** `gather_orders`, because that is what builds the briefings.

The dispatch carries an explicit `side` key. `server/app.py` fogs dispatches with an allow-list, and a bare `"intel"` entry there would leak a Soviet decrypt to the player; the `side` tag lets Task 5 filter correctly by construction.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_campaign_session.py`:

```python
def _campaign_with_enemy_traffic(commander, corps_id):
    """A campaign holding one commander's orders from 'last week'."""
    campaign = Campaign.new(DATA_DIR)
    campaign.intel_chance = 1.0
    campaign.state.last_orders = {
        commander: {
            "commander": commander,
            "orders": [{"corps_id": corps_id, "posture": "defend", "objective": None}],
            "dispatch": "", "reasoning": "",
        }
    }
    return campaign


async def test_an_axis_intercept_reaches_the_inbox_and_no_axis_briefing():
    # The asymmetry of the design: the player distributes his own intelligence.
    # A future change that "helpfully" broadcasts it must fail here.
    campaign = _campaign_with_enemy_traffic("pavlov", "sov_3a")
    await campaign.play_turn({})
    cards = [d for d in campaign.state.dispatches if d["commander"] == "intel"]
    assert len(cards) == 1
    assert cards[0]["side"] == "axis"
    assert "axis" not in campaign.state.intel


async def test_a_soviet_intercept_reaches_soviet_briefings_and_no_inbox_card():
    campaign = _campaign_with_enemy_traffic("guderian", "xxiv_pz")
    await campaign.play_turn({})
    assert campaign.state.intel["soviet"]["commander"] == "guderian"
    assert not [
        d for d in campaign.state.dispatches
        if d["commander"] == "intel" and d.get("side") == "soviet"
    ]


async def test_the_intel_card_says_it_has_not_been_circulated():
    # Without this line the player watches his commanders ignore a decrypt he
    # never sent them, and blames the commanders for his own omission.
    campaign = _campaign_with_enemy_traffic("pavlov", "sov_3a")
    await campaign.play_turn({})
    card = next(d for d in campaign.state.dispatches if d["commander"] == "intel")
    assert "not been circulated" in card["text"]


async def test_no_intercept_at_zero_chance():
    campaign = _campaign_with_enemy_traffic("pavlov", "sov_3a")
    campaign.intel_chance = 0.0
    await campaign.play_turn({})
    assert not [d for d in campaign.state.dispatches if d["commander"] == "intel"]
    assert campaign.state.intel == {}
```

`Campaign` and `DATA_DIR` are already imported at the top of that file. `pyproject.toml` sets `asyncio_mode = "auto"`, so a bare `async def test_...` runs without a decorator — match the file's existing style. `Campaign.new(DATA_DIR)` with no client takes the scripted-orders path, so these tests need no LLM and no mocked transport.

Note `resolve_turn` overwrites `state.last_orders` at the end of the turn; the intercept is rolled at the start, so the fixture's traffic is what gets decrypted.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_campaign_session.py -q
```

Expected: FAIL — no dispatch with `commander == "intel"` exists.

- [ ] **Step 3: Add the field**

In `commanders/campaign.py`, add the import:

```python
from commanders.intel import INTEL_CHANCE, format_intel_lines, intercept
```

and next to `communique_chance` in the `Campaign` dataclass:

```python
    intel_chance: float = INTEL_CHANCE
```

- [ ] **Step 4: Roll the intercepts before briefings are built**

In `play_turn`, after the two `self.state.directives.update(...)` lines and **before** `active = self.active_commanders()`:

```python
        # Signals intelligence, rolled before briefings because that is what
        # consumes it. Asymmetric on purpose: the player distributes his own
        # side's intelligence himself (inbox only, and he signals whoever he
        # wants), while the AI side has no player to do that, so its decrypt
        # goes straight into every briefing on that side.
        self.state.intel = {}
        intel_rng = random.Random(self.state.seed * 6151 + self.state.turn)
        for side in ("axis", "soviet"):  # fixed order: determinism
            hit = intercept(
                self.state, self.dossiers, side, intel_rng, chance=self.intel_chance
            )
            if hit is None:
                continue
            if side == self.player_side:
                body = "\n".join(format_intel_lines(self.state, hit))
                self.state.dispatches.append({
                    "turn": self.state.turn,
                    "commander": "intel",
                    "side": side,
                    "text": (
                        "DECRYPT of last week's enemy traffic - believed accurate:\n"
                        f"{body}\n\n"
                        "This decrypt has not been circulated. Signal a commander "
                        "if you want him to act on it."
                    ),
                })
            else:
                self.state.intel[side] = hit
```

`random` is already imported in `commanders/campaign.py`; confirm before adding it.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_campaign_session.py -q
```

Expected: PASS

- [ ] **Step 6: Run the full suite and lint**

```bash
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

- [ ] **Step 7: Commit**

```bash
git add commanders/campaign.py tests/test_campaign_session.py
git commit -m "Roll a decrypt each turn, and let the player distribute his own"
```

---

### Task 5: Fog-filter the card, and show it

**Files:**
- Modify: `server/app.py` (the dispatch filter in `snapshot`)
- Modify: `web/app.js` (dispatch card rendering), `web/style.css`
- Test: `tests/test_server.py`

Note the test file: `tests/test_fog.py` covers `engine.fog.visible_enemy_contacts` and knows nothing about the server. The snapshot is exercised in `tests/test_server.py`, which has an `api` fixture wiring an `httpx.ASGITransport` around the app with `use_llm=False`.

**Interfaces:**
- Consumes: the `{"commander": "intel", "side": ...}` dispatch from Task 4.
- Produces: no new callable interfaces.

`server/app.py` currently lets `staff` and `okh` through unconditionally and otherwise requires the dispatch's commander to be a dossier on the player's side. An `intel` dispatch matches neither, so it would be silently dropped. Adding a bare `"intel"` to that allow-list would be worse — it would pass a Soviet decrypt straight to the player. Filter on the `side` key.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_server.py`. These use the file's existing `api` fixture and its `get_session` import; `asyncio_mode = "auto"` is set in `pyproject.toml`, so a bare `async def test_...` runs without a decorator.

```python
async def test_the_players_own_decrypt_reaches_his_snapshot(api):
    await api.post("/api/game/new")
    campaign = get_session().require_campaign()
    campaign.state.dispatches.append(
        {"turn": 1, "commander": "intel", "side": "axis", "text": "DECRYPT ..."}
    )
    snap = (await api.get("/api/game")).json()
    assert any(d["commander"] == "intel" for d in snap["dispatches"])


async def test_a_soviet_decrypt_never_reaches_the_player(api):
    # Fog discipline: only ever surface the player's own side. A bare "intel"
    # entry in the allow-list would leak this.
    await api.post("/api/game/new")
    campaign = get_session().require_campaign()
    campaign.state.dispatches.append(
        {"turn": 1, "commander": "intel", "side": "soviet", "text": "DECRYPT ..."}
    )
    snap = (await api.get("/api/game")).json()
    assert not any(d["commander"] == "intel" for d in snap["dispatches"])
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_server.py -q
```

Expected: FAIL — the first test finds no `intel` dispatch (it is being filtered out).

- [ ] **Step 3: Let a side's own decrypt through**

In `server/app.py`, in the `dispatches` list comprehension:

```python
    dispatches = [
        d for d in state.dispatches
        if d["commander"] in ("staff", "okh")  # staff report and OKH directives
        # a decrypt is fogged by the side that made it, never by commander id
        or (d["commander"] == "intel" and d.get("side") == side)
        or (d["commander"] in campaign.dossiers
            and campaign.dossiers[d["commander"]].side == side)
    ][-DISPATCH_HISTORY_LIMIT:]
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_server.py -q
```

Expected: PASS

- [ ] **Step 5: Render the card**

In `web/app.js`, in the dispatch-card branch chain, after the `okh` branch and before the final `else`:

```javascript
    } else if (d.commander === "intel") {
      card.className = "dispatch intel";
      card.innerHTML = `
        <div class="geheim">ENTZIFFERT</div>
        <div class="from">Horchdienst — Signals Intercept Service</div>
        <div class="meta">DECRYPT · WEEK ${Number(d.turn)}</div>
        <div class="body"></div>`;
```

The existing `card.querySelector(".body").textContent = d.text;` after the chain fills the body, so the decrypt's newlines are inserted as text, not markup. Do not switch it to `innerHTML`.

In `web/style.css`, beside the `.dispatch.okh` and `.dispatch.staff` rules:

```css
.dispatch.intel { background: #e4e8ea; border-left: 5px solid #46606e; }
.dispatch.intel .geheim { color: rgba(70,96,110,.85); border-color: rgba(70,96,110,.6); }
.dispatch.intel .from { color: #33474f; }
.dispatch.intel .body { white-space: pre-wrap; }
```

`white-space: pre-wrap` matters: the decrypt is a multi-line list and would otherwise collapse to one paragraph.

- [ ] **Step 6: See it in the browser**

Start the server and confirm a decrypt card renders with its lines intact.

```bash
.\.venv\Scripts\python.exe -m uvicorn server.app:app --port 8000
```

Do not end a turn in `server/saves/campaign.json` — that is a real in-progress game. To check the card without playing, load the page and append a fake intel dispatch to the client-side snapshot object, then re-render.

- [ ] **Step 7: Run the full suite and lint**

```bash
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

- [ ] **Step 8: Commit**

```bash
git add server/app.py web/app.js web/style.css tests/test_server.py
git commit -m "Show the player his own decrypts, and only his own"
```

---

### Task 6: Close the spec

**Files:**
- Modify: `docs/superpowers/specs/2026-08-02-signals-intelligence-design.md`
- Modify: `README.md`

- [ ] **Step 1: Settle the frequency question**

Play or replay enough turns to see a decrypt land, then record in the spec whether 0.25 per side per turn felt right. Open question 2 becomes a decision with a number and one sentence of reasoning. Change the status line from PROPOSED to IMPLEMENTED.

- [ ] **Step 2: Mention the feature in the README**

Add signals intelligence to the feature list, in one sentence, stating that a decrypt reaches the player and not his commanders.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-08-02-signals-intelligence-design.md README.md
git commit -m "Signals intelligence: record the frequency decision"
```

---

## Self-review notes

- **Spec coverage:** persist validated orders (T1), pure seeded selection with contact weighting (T2), the briefing block with region ids (T3), the asymmetric delivery and the "not circulated" line (T4), fog safety and the inbox card (T5), frequency (T6). Every test the spec's Testing section lists has a home: chance 0/1 and same-seed and contact-preference in T2; validated-orders and save round-trip in T1; region ids in T2/T3; the fog test and the axis-inbox-only test in T4/T5.
- **Deviation from the spec, deliberate:** `intercept` takes `dossiers`, which the spec's sketch omitted. `build_briefing(state, commander)` cannot reach dossiers, so the name and role must be captured at selection time and stored in `state.intel`.
- **Addition the spec did not anticipate:** the dispatch carries a `side` key. `server/app.py`'s allow-list fogs by commander id, and `intel` is not a commander — a bare allow-list entry would leak Soviet decrypts. Filtering on `side` makes the fog rule correct by construction rather than by the producer's good behavior.
- **Type consistency:** `intercept` returns `{"commander", "name", "role", "orders"}` and every consumer (`format_intel_lines`, the briefing block, the dispatch text) reads exactly those keys. `state.intel` is `side -> that dict`. `state.last_orders` is `commander -> CommanderOrders.to_dict()` output in T1, T2 and T4 alike.
- **Risk to watch:** T3 touches `commanders/briefing.py`, whose `STAFF OPTIONS` section `commanders/divergence.py` parses by exact phrasing. The new block goes above it and `tests/test_divergence.py` is the guard; a divergence failure after T3 means the option lines were disturbed.
- **Two errors caught in review of this plan, already corrected above:** the snapshot tests were first written into `tests/test_fog.py`, which covers `engine.fog.visible_enemy_contacts` and has no server fixture — they belong in `tests/test_server.py` with its `api` fixture. And the Task 4 tests used `asyncio.run(...)`, where this repo sets `asyncio_mode = "auto"` and writes bare `async def test_...`. Follow the corrected versions.
