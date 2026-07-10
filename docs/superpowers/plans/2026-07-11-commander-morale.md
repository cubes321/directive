# Living Commander Morale Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `dossier.dynamic` (confidence/fatigue/relationship) evolve each turn from outcomes and player treatment, feed the mood into the commander's prompt, and show it on his card.

**Architecture:** A pure `update_morale` (in `commanders/records.py`, called next to `update_track_records`) adjusts each player-side commander's `dynamic` from the turn's combats/movements and whether the player signalled him (a seeded, temperament-weighted roll). A prose "current state" block in `prompts.py` renders that mood into the persona prompt so behaviour — including insubordination — emerges from the LLM. Peer-dismissal cooling lives in `Campaign.dismiss`. The card gains animated morale bars. Engine and combat maths are untouched.

**Tech Stack:** Python (pytest), vanilla JS, CSS.

Spec: `docs/superpowers/specs/2026-07-11-commander-morale-design.md`.

---

### Task 1: `update_morale` — outcomes, fatigue, and the signalling roll

**Files:**
- Modify: `commanders/records.py`
- Test: `tests/test_records.py` (create if absent)

- [ ] **Step 1: Write the failing tests**

Create/extend `tests/test_records.py`:

```python
import random
from pathlib import Path

from commanders.campaign import Campaign
from commanders.records import update_morale, _signal_warm_chance
from engine.orders import CommanderOrders, CorpsOrder
from engine.turn import resolve_turn

DATA_DIR = Path(__file__).parent.parent / "data"


def _fresh():
    # Real scenario so corps/commanders/map are wired as in play.
    return Campaign.new(DATA_DIR)


def _run(campaign, orders):
    report = resolve_turn(campaign.state, orders)
    update_morale(campaign.state, report, campaign.dossiers, campaign.player_side,
                  rng=random.Random(0))
    return report


def _combat(attacker_ids, region, outcome, encircled=False, defenders=None):
    return {
        "region": region, "terrain": "clear",
        "attackers": list(attacker_ids), "defenders": list(defenders or []),
        "odds": 2.0, "attacker_losses": 3, "defender_losses": 20,
        "outcome": outcome, "encircled": encircled,
        "attacker_details": [], "defender_details": [],
    }


def test_winning_an_attack_raises_confidence_and_relationship():
    c = _fresh()
    gud = "guderian"
    corps = c.state.corps_for(gud)
    before_conf = c.dossiers[gud].dynamic["confidence"]
    before_rel = c.dossiers[gud].dynamic["relationship"]
    from engine.turn import TurnReport
    rep = TurnReport(
        turn=c.state.turn, movements=[],
        combats=[_combat([corps[0].id], corps[0].location, "defender_retreated")],
    )
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["confidence"] == before_conf + 1
    assert c.dossiers[gud].dynamic["relationship"] == before_rel + 1


def test_repulsed_attack_lowers_confidence_and_relationship():
    c = _fresh()
    gud = "guderian"
    corps = c.state.corps_for(gud)
    before_conf = c.dossiers[gud].dynamic["confidence"]
    before_rel = c.dossiers[gud].dynamic["relationship"]
    from engine.turn import TurnReport
    rep = TurnReport(turn=c.state.turn, movements=[], combats=[{
        "region": corps[0].location, "terrain": "clear",
        "attackers": [corps[0].id], "defenders": [],
        "odds": 0.5, "attacker_losses": 20, "defender_losses": 2,
        "outcome": "defender_held", "encircled": False,
        "attacker_details": [], "defender_details": [],
    }])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["confidence"] == before_conf - 1
    assert c.dossiers[gud].dynamic["relationship"] == before_rel - 1


def test_resting_lowers_fatigue_and_fighting_raises_it():
    c = _fresh()
    gud = "guderian"
    corps = c.state.corps_for(gud)
    c.dossiers[gud].dynamic["fatigue"] = 5
    from engine.turn import TurnReport
    # no combats, no movements -> rested
    update_morale(c.state, TurnReport(turn=c.state.turn, combats=[], movements=[]),
                  c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["fatigue"] == 4
    # fought -> +1
    rep = TurnReport(turn=c.state.turn, movements=[], combats=[{
        "region": corps[0].location, "terrain": "clear",
        "attackers": [corps[0].id], "defenders": [], "odds": 2.0,
        "attacker_losses": 3, "defender_losses": 20, "outcome": "defender_retreated",
        "encircled": False, "attacker_details": [], "defender_details": [],
    }])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["fatigue"] == 5


def test_morale_clamps_between_0_and_10():
    c = _fresh()
    gud = "guderian"
    c.dossiers[gud].dynamic["confidence"] = 0
    corps = c.state.corps_for(gud)
    from engine.turn import TurnReport
    rep = TurnReport(turn=c.state.turn, movements=[], combats=[{
        "region": corps[0].location, "terrain": "clear",
        "attackers": [corps[0].id], "defenders": [], "odds": 0.4,
        "attacker_losses": 20, "defender_losses": 1, "outcome": "defender_held",
        "encircled": False, "attacker_details": [], "defender_details": [],
    }])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["confidence"] == 0  # cannot go below 0


def test_signal_warm_chance_is_lower_for_prouder_commanders():
    assert _signal_warm_chance(9) < _signal_warm_chance(3)
    assert 0.05 <= _signal_warm_chance(9) <= 0.9


def test_signalling_can_warm_relationship_subject_to_the_roll():
    c = _fresh()
    gud = "guderian"
    c.state.conversations.setdefault(gud, []).append(
        {"turn": c.state.turn, "role": "player", "text": "Well done, Heinz."}
    )
    before = c.dossiers[gud].dynamic["relationship"]
    from engine.turn import TurnReport
    rep = TurnReport(turn=c.state.turn, combats=[], movements=[])
    # rng that always rolls 0.0 -> below any chance -> warms
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(),
                  _force_roll=0.0)
    assert c.dossiers[gud].dynamic["relationship"] == before + 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_records.py -v`
Expected: FAIL — `ImportError: cannot import name 'update_morale'`.

- [ ] **Step 3: Implement `update_morale`**

Add to `commanders/records.py`:

```python
import random
from collections import defaultdict

SIGNAL_BASE_CHANCE = 0.6
SIGNAL_EGO_WEIGHT = 0.05
SIGNAL_MIN_CHANCE = 0.05
SIGNAL_MAX_CHANCE = 0.9
CONF_CAP = 3      # max confidence swing per turn
REL_CAP = 2       # max relationship swing per turn (before the signal roll)


def _clamp(v: int) -> int:
    return max(0, min(10, v))


def _signal_warm_chance(ego: int) -> float:
    return max(SIGNAL_MIN_CHANCE, min(SIGNAL_MAX_CHANCE,
                                      SIGNAL_BASE_CHANCE - SIGNAL_EGO_WEIGHT * ego))


def _signalled_this_turn(state: GameState, commander_id: str, turn: int) -> bool:
    return any(
        line.get("role") == "player" and line.get("turn") == turn
        for line in state.conversations.get(commander_id, [])
    )


def update_morale(
    state: GameState,
    report: TurnReport,
    dossiers: dict[str, Dossier],
    player_side: str,
    rng: random.Random | None = None,
    _force_roll: float | None = None,
) -> None:
    """Evolve each player-side commander's dynamic (confidence/fatigue/
    relationship) from this turn's outcomes and whether the player signalled him.
    Pure over state/report/dossiers except the dossier mutation. Deterministic:
    the signalling roll uses a seeded rng and commanders are visited in id order."""
    rng = rng or random.Random(state.seed * 7907 + report.turn)
    moved = {m["corps"] for m in report.movements
             if not m.get("bounced") and not m.get("arrived")}

    conf: dict[str, int] = defaultdict(int)
    rel: dict[str, int] = defaultdict(int)
    fought: set[str] = set()
    for combat in report.combats:
        won = combat["outcome"] == "defender_retreated"
        for cid in combat["attackers"]:
            cmd = _commander_of(state, cid)
            if cmd is None:
                continue
            fought.add(cmd)
            if won and combat["encircled"]:
                conf[cmd] += 2; rel[cmd] += 1
            elif won:
                conf[cmd] += 1; rel[cmd] += 1
            else:
                conf[cmd] -= 1; rel[cmd] -= 1   # repulsed: shaken, men spent for nothing
        for cid in combat["defenders"]:
            cmd = _commander_of(state, cid)
            if cmd is None:
                continue
            fought.add(cmd)
            conf[cmd] += -2 if won else 1        # lost the position, or held

    for cid in sorted(dossiers):
        dossier = dossiers[cid]
        if dossier.side != player_side:
            continue
        dyn = dossier.dynamic
        dc = max(-CONF_CAP, min(CONF_CAP, conf.get(cid, 0)))
        dyn["confidence"] = _clamp(dyn.get("confidence", 5) + dc)

        commander_moved = any(_commander_of(state, x) == cid for x in moved)
        delta_f = 1 if (cid in fought or commander_moved) else -1
        dyn["fatigue"] = _clamp(dyn.get("fatigue", 0) + delta_f)

        dr = max(-REL_CAP, min(REL_CAP, rel.get(cid, 0)))
        if _signalled_this_turn(state, cid, report.turn):
            chance = _signal_warm_chance(dossier.traits.get("ego", 5))
            roll = _force_roll if _force_roll is not None else rng.random()
            if roll < chance:
                dr += 1
        dyn["relationship"] = _clamp(dyn.get("relationship", 5) + dr)
```

Add `import random` and `from collections import defaultdict` at the top with the existing imports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_records.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add commanders/records.py tests/test_records.py
git commit -m "Add update_morale: evolve commander confidence/fatigue/relationship"
```

---

### Task 2: Render mood into the persona prompt

**Files:**
- Modify: `commanders/prompts.py`
- Test: `tests/test_prompts.py` (create if absent)

- [ ] **Step 1: Write the failing tests**

Create/extend `tests/test_prompts.py`:

```python
from commanders.dossier import Dossier
from commanders.prompts import _current_state_block, build_persona_prompt


def _dossier(**dynamic):
    base = {"confidence": 5, "fatigue": 0, "relationship": 5}
    base.update(dynamic)
    return Dossier(id="x", name="Test", role="Test Corps", side="axis",
                   bio="A soldier.", traits={"ego": 5}, dynamic=base)


def test_low_relationship_block_signals_insubordination():
    block = _current_state_block(_dossier(relationship=1))
    assert "own judgment" in block.lower()


def test_high_confidence_and_exhaustion_show():
    assert "riding high" in _current_state_block(_dossier(confidence=9)).lower()
    assert "exhaust" in _current_state_block(_dossier(fatigue=8)).lower()


def test_neutral_mood_is_calm_not_empty():
    block = _current_state_block(_dossier())
    assert block.strip()  # a neutral line, never an empty section


def test_persona_prompt_includes_current_state():
    prompt = build_persona_prompt(_dossier(relationship=1))
    assert "YOUR CURRENT STATE" in prompt
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_prompts.py -v`
Expected: FAIL — `ImportError: cannot import name '_current_state_block'`.

- [ ] **Step 3: Implement**

Add to `commanders/prompts.py`:

```python
def _current_state_block(dossier: Dossier) -> str:
    d = dossier.dynamic
    lines: list[str] = []
    conf, fat, rel = d.get("confidence", 5), d.get("fatigue", 0), d.get("relationship", 5)
    if conf >= 8:
        lines.append("You are riding high - recent successes leave you certain of your judgment.")
    elif conf <= 2:
        lines.append("Recent reverses have shaken you; you are second-guessing yourself.")
    if fat >= 7:
        lines.append("Your formations are exhausted, stretched past the point of endurance.")
    if rel >= 8:
        lines.append("You trust the theater commander; his intent and yours run together.")
    elif rel <= 2:
        lines.append("Your patience with headquarters is worn thin; you increasingly act on "
                     "your own judgment, whatever the directive says.")
    if not lines:
        lines.append("You are steady - neither elated nor discouraged.")
    return "\n".join(lines)
```

Then append it to `build_persona_prompt`'s return string, after the `YOUR WAR SO FAR` block:

```python
    return f"""\
You are {dossier.name}, commanding {dossier.role} in {theater}, summer 1941.

WHO YOU ARE:
{dossier.bio}

YOUR CHARACTER (let these genuinely drive your decisions):
{_traits_block(dossier)}

YOUR WAR SO FAR:
{_track_record_block(dossier)}

YOUR CURRENT STATE:
{_current_state_block(dossier)}"""
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_prompts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add commanders/prompts.py tests/test_prompts.py
git commit -m "Feed commander mood into the persona prompt"
```

---

### Task 3: Cool remaining commanders when a peer is dismissed

**Files:**
- Modify: `commanders/campaign.py` (`dismiss`)
- Test: `tests/test_campaign_session.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_campaign_session.py`:

```python
def test_dismissing_a_commander_cools_the_remaining_ones():
    campaign = Campaign.new(DATA_DIR)
    hoth_before = campaign.dossiers["hoth"].dynamic["relationship"]
    campaign.dismiss("guderian", "schmidt")  # relieve a peer
    assert campaign.dossiers["hoth"].dynamic["relationship"] == hoth_before - 1
    # the newly promoted replacement and the enemy are unaffected
    assert campaign.dossiers["pavlov"].dynamic["relationship"] == 5
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_campaign_session.py::test_dismissing_a_commander_cools_the_remaining_ones -v`
Expected: FAIL — relationship unchanged (still 5).

- [ ] **Step 3: Implement**

In `commanders/campaign.py` `dismiss`, just before `return cost`, add:

```python
        # A relief unsettles the peers who remain in command.
        for other_id, other in self.dossiers.items():
            if (other_id not in (commander_id, replacement_id)
                    and other.side == self.player_side
                    and self.state.corps_for(other_id)):
                other.dynamic["relationship"] = max(
                    0, other.dynamic.get("relationship", 5) - 1
                )
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_campaign_session.py -k dismiss -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add commanders/campaign.py tests/test_campaign_session.py
git commit -m "Dismissing a commander cools the remaining commanders"
```

---

### Task 4: Update morale each turn in `play_turn`

**Files:**
- Modify: `commanders/campaign.py` (`play_turn`; import)
- Test: `tests/test_campaign_session.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_campaign_session.py`:

```python
async def test_play_turn_evolves_morale_and_it_persists(tmp_path):
    campaign = make_campaign()
    # freeze a known fatigue so we can see it change
    for cid in campaign.active_commanders(campaign.player_side):
        campaign.dossiers[cid].dynamic["fatigue"] = 5
    await campaign.play_turn({})
    fatigues = [campaign.dossiers[cid].dynamic["fatigue"]
                for cid in campaign.active_commanders(campaign.player_side)]
    assert any(f != 5 for f in fatigues)  # morale moved for someone
    path = tmp_path / "save.json"
    campaign.save(path)
    reloaded = Campaign.load(path)
    any_cid = campaign.active_commanders(campaign.player_side)[0]
    assert (reloaded.dossiers[any_cid].dynamic
            == campaign.dossiers[any_cid].dynamic)  # survives round trip
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_campaign_session.py::test_play_turn_evolves_morale_and_it_persists -v`
Expected: FAIL — all fatigues still 5 (morale not wired in).

- [ ] **Step 3: Implement**

In `commanders/campaign.py`, update the import:

```python
from commanders.records import update_morale, update_track_records
```

In `play_turn`, right after `update_track_records(self.state, report, self.dossiers)`:

```python
        update_morale(self.state, report, self.dossiers, self.player_side)
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_campaign_session.py -v`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add commanders/campaign.py tests/test_campaign_session.py
git commit -m "Evolve commander morale each turn in play_turn"
```

---

### Task 5: Morale bars on the commander card

**Files:**
- Modify: `web/app.js` (`renderCommanders`, ~L266-293)
- Modify: `web/style.css`

No unit test — verified live in the browser preview. (`snapshot` already includes `dynamic` per the commander at `server/app.py:154`; confirm the commander object the frontend renders carries `dynamic`.)

- [ ] **Step 1: Confirm the data reaches the client**

Run the server, open the browser preview, and in the console check a commander has `dynamic`:
`javascript_tool`: `JSON.stringify((window.__lastSnap||{}).commanders?.[0]?.dynamic)` — if the app doesn't stash the snapshot, instead read the network response for `/api/game`. Confirm `{confidence,fatigue,relationship}` present. If the frontend commander list strips `dynamic`, add it where the card reads `cmd` (it already reads `cmd.traits`).

- [ ] **Step 2: Render morale bars**

In `renderCommanders`, where `traits` is built (the `Object.entries(cmd.traits)` block), add a morale block after it:

```javascript
    const morale = cmd.dynamic
      ? ["confidence", "fatigue", "relationship"].map((k) =>
          `<div class="morale-row"><span>${k}</span>
           <span class="mbar"><span class="mfill ${k}" style="width:${Number(cmd.dynamic[k]) * 10}%"></span></span></div>`
        ).join("")
      : "";
```

Then include `${morale}` in the card's `innerHTML` (after the `<div class="traits">...</div>`), e.g.:

```javascript
      <div class="traits">${traits}</div>
      <div class="morale">${morale}</div>
```

- [ ] **Step 3: Style + animate in `web/style.css`**

```css
.morale { margin-top: 6px; }
.morale-row { display: flex; align-items: center; gap: 6px; font-size: 11px; opacity: 0.85; }
.morale-row span:first-child { width: 78px; text-transform: uppercase; letter-spacing: 0.5px; }
.mbar { flex: 1; height: 5px; background: #0003; border-radius: 3px; overflow: hidden; }
.mfill { display: block; height: 100%; transition: width 0.6s ease; }
.mfill.confidence { background: #6a9a5b; }
.mfill.fatigue { background: #a8843f; }
.mfill.relationship { background: #5b82a8; }
```

- [ ] **Step 4: Verify in the browser preview**

Reload, open COMMANDERS. Confirm three morale bars per card, distinct from the trait bars. End a turn and confirm a bar's width animates as morale shifts. Check light/dark via `resize_window`. Screenshot.

- [ ] **Step 5: Commit**

```bash
git add web/app.js web/style.css
git commit -m "Show animated morale bars on the commander card"
```

---

## Self-Review

- **Spec coverage:** scale/defaults (Task 1); confidence/fatigue/relationship signals + signalling roll (Task 1); temperament-weighted chance `_signal_warm_chance` (Task 1); peer-dismissal cooling (Task 3); prose mood block incl. the low-relationship insubordination lever (Task 2); wired each turn + save/load (Task 4); animated card bars, noting they must be *added* (Task 5). Psychological-only: no engine/combat change anywhere. All spec sections covered.
- **Type consistency:** `update_morale(state, report, dossiers, player_side, rng=None, _force_roll=None)` used identically in Tasks 1 and 4; `_signal_warm_chance(ego)`, `_current_state_block(dossier)`, `_signalled_this_turn` names consistent; `dynamic` keys `confidence`/`fatigue`/`relationship` consistent across engine, prompt, and CSS (`.mfill.confidence` etc).
- **Placeholder scan:** every code step shows full code; preview steps name exactly what to check. Task 1 tests build a crafted `TurnReport` via the `_combat` helper rather than driving live combats — the reliable, deterministic path.
- **Note for executor:** `TurnReport` is a dataclass `TurnReport(turn, movements, combats)`; construct it directly in tests as shown.
