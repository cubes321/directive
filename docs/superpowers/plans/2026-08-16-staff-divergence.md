# Staff-Option Divergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A free, offline metric that scores each commander's orders against the staff options he was offered, so personality collapse becomes visible when swapping models.

**Architecture:** Pure scoring logic in `commanders/divergence.py` (strings and dicts in, counts out — no file IO), plus a thin top-level `analyze_divergence.py` that reads a run's transcripts and prints a table. This mirrors `commanders/replay.py` (analysis harness in `commanders/`, unit-tested) and `analyze_logs.py` (top-level script using `resolve_log_dir`).

**Tech Stack:** Python 3.13, stdlib only (`re`, `json`, `collections.Counter`), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-16-staff-divergence-design.md`

## Global Constraints

- Run everything with the venv interpreter: `.\.venv\Scripts\python.exe`
- `engine/` must not be touched: this is an analysis tool, and `engine/` is pure rules with no IO. All new code lives in `commanders/` and the repo root.
- `ruff check .` must stay green.
- **Never iterate a `set` where output depends on order** — sort first. This codebase has a cross-hash-seed regression test because of a past bug here.
- Do not modify `commanders/briefing.py`. The metric is a read-only instrument; changing what it measures while building it would invalidate the baseline.
- Tests are TDD-first: the failing test comes before the implementation, always.

---

### Task 1: Parse staff options out of a briefing

**Files:**
- Create: `commanders/divergence.py`
- Test: `tests/test_divergence.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Option = tuple[str, str | None]` — `(posture, objective_id)`, objective `None` for hold/reserve.
  - `parse_staff_options(briefing: str) -> dict[str, list[Option]]` — corps id to its options, in briefing order.

The tests build a **real** briefing via `build_briefing` rather than a hand-written string. That is deliberate: if `_staff_options` ever changes its phrasing, these tests must fail, because a parser that silently stops recognizing an option would score every order in that briefing as `off-menu` and report a *rise* in personality at the moment it went blind.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_divergence.py`:

```python
from pathlib import Path

from commanders.briefing import build_briefing
from commanders.divergence import parse_staff_options
from engine.scenario import load_scenario

DATA_DIR = Path(__file__).parent.parent / "data"


def test_parses_each_corps_options_in_order():
    state = load_scenario(DATA_DIR)
    options = parse_staff_options(build_briefing(state, "guderian"))
    assert options["xxiv_pz"] == [
        ("attack", "baranovichi"),
        ("advance", "pripyat"),
        ("defend", None),
    ]


def test_parses_every_briefed_corps():
    state = load_scenario(DATA_DIR)
    options = parse_staff_options(build_briefing(state, "guderian"))
    assert set(options) == {"xxiv_pz", "xlvi_pz", "xlvii_pz"}


def test_a_worn_corps_is_offered_reserve_not_hold():
    # _staff_options swaps "hold current position" for "hold in reserve" below
    # 70 supply or organization; both must map to a posture.
    state = load_scenario(DATA_DIR)
    corps = state.corps_for("guderian")[0]
    corps.supply = 50
    options = parse_staff_options(build_briefing(state, "guderian"))
    assert options[corps.id][-1] == ("reserve", None)


def test_an_unrecognized_option_line_raises():
    # Silence here would be the worst failure mode: unparsed options make every
    # order look off-menu, i.e. personality appears to rise as the metric blinds.
    briefing = "STAFF OPTIONS:\nFor X Corps [x_ak]:\n  * dig in and pray\n"
    try:
        parse_staff_options(briefing)
    except ValueError as e:
        assert "dig in and pray" in str(e)
    else:
        raise AssertionError("expected ValueError on an unrecognized option")


def test_a_briefing_without_staff_options_yields_nothing():
    assert parse_staff_options("SITUATION BRIEFING - no options here") == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_divergence.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'commanders.divergence'`

- [ ] **Step 3: Implement the parser**

Create `commanders/divergence.py`:

```python
"""Staff-option divergence: how far a commander's orders sit from what his own
staff suggested.

Turn time and order validity are already instrumented. Both can stay green
while the thing that actually matters rots: a smaller model that regresses to
taking staff option #1 every turn passes every schema check. This scores each
order against the options that corps was offered, so that regression shows up
as a number.

Pure functions only - strings and dicts in, counts out. The file IO lives in
analyze_divergence.py.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable

Option = tuple[str, str | None]  # (posture, objective region id)

BUCKETS = ("first", "middle", "hold", "off-menu")

_CORPS_HEADER = re.compile(r"^For .+ \[([a-z0-9_]+)\]:$")
_OPTION_LINE = re.compile(r"^  \* (.+)$")
_REGION_ID = re.compile(r"\[id: ([a-z0-9_]+)\]")

# Prefix -> posture, mirroring commanders/briefing.py:_staff_options. "close up
# toward the front" is a move like any other, so it reads as an advance.
_MOVE_PREFIXES = (
    ("attack ", "attack"),
    ("advance to ", "advance"),
    ("close up toward the front at ", "advance"),
)


def _region_of(text: str) -> str:
    match = _REGION_ID.search(text)
    if match is None:
        raise ValueError(f"staff option names no region: {text!r}")
    return match.group(1)


def _option_from_text(text: str) -> Option:
    for prefix, posture in _MOVE_PREFIXES:
        if text.startswith(prefix):
            return (posture, _region_of(text))
    if text.startswith("hold in reserve"):
        return ("reserve", None)
    if text.startswith("hold current position"):
        return ("defend", None)
    raise ValueError(f"unrecognized staff option: {text!r}")


def parse_staff_options(briefing: str) -> dict[str, list[Option]]:
    """corps id -> the options it was offered, in the order the briefing gave
    them. Empty when the briefing has no STAFF OPTIONS section."""
    if "STAFF OPTIONS" not in briefing:
        return {}
    options: dict[str, list[Option]] = {}
    current: str | None = None
    for line in briefing.split("STAFF OPTIONS", 1)[1].splitlines():
        header = _CORPS_HEADER.match(line)
        if header:
            current = header.group(1)
            options[current] = []
            continue
        entry = _OPTION_LINE.match(line)
        if entry and current is not None:
            options[current].append(_option_from_text(entry.group(1)))
    return options
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_divergence.py -q
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Run the full suite and lint**

```bash
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

Expected: all tests pass; `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add commanders/divergence.py tests/test_divergence.py
git commit -m "Parse staff options out of a logged briefing"
```

---

### Task 2: Bucket one order against its options

**Files:**
- Modify: `commanders/divergence.py`
- Test: `tests/test_divergence.py`

**Interfaces:**
- Consumes: `Option` from Task 1.
- Produces: `bucket_for(order: dict, options: list[Option]) -> str` where `order` is `{"corps_id": str, "posture": str, "objective": str | None}` and the return is one of `BUCKETS`.

The precedence rule is the subtle part. A corps with nothing in reach gets a one-entry list holding only the hold option, so index 0 is simultaneously first and last. `hold` wins: taking the only option offered, when that option is inaction, is not independence.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_divergence.py`:

```python
from commanders.divergence import bucket_for

ATTACK = ("attack", "minsk")
ADVANCE = ("advance", "slonim")
HOLD = ("defend", None)


def _order(posture, objective=None, corps_id="xxiv_pz"):
    return {"corps_id": corps_id, "posture": posture, "objective": objective}


def test_the_staffs_lead_suggestion_is_first():
    assert bucket_for(_order("attack", "minsk"), [ATTACK, ADVANCE, HOLD]) == "first"


def test_a_later_move_suggestion_is_middle():
    assert bucket_for(_order("advance", "slonim"), [ATTACK, ADVANCE, HOLD]) == "middle"


def test_the_trailing_hold_option_is_hold():
    assert bucket_for(_order("defend"), [ATTACK, ADVANCE, HOLD]) == "hold"


def test_index_one_is_hold_when_the_list_is_only_two_long():
    # A quiet sector offers one move and then the hold. Raw rank would call
    # this "middle" and read as independence; it is the opposite.
    assert bucket_for(_order("defend"), [ATTACK, HOLD]) == "hold"


def test_the_only_option_being_hold_scores_as_hold_not_first():
    # Starving infantry in the mud can reach nothing at all.
    assert bucket_for(_order("defend"), [HOLD]) == "hold"


def test_an_objective_the_staff_never_raised_is_off_menu():
    assert bucket_for(_order("advance", "slutsk"), [ATTACK, ADVANCE, HOLD]) == "off-menu"


def test_the_right_region_with_the_wrong_posture_is_off_menu():
    assert bucket_for(_order("advance", "minsk"), [ATTACK, ADVANCE, HOLD]) == "off-menu"


def test_a_missing_objective_key_is_treated_as_none():
    assert bucket_for({"corps_id": "x", "posture": "defend"}, [ATTACK, HOLD]) == "hold"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_divergence.py -q
```

Expected: FAIL — `ImportError: cannot import name 'bucket_for'`

- [ ] **Step 3: Implement the bucketing**

Append to `commanders/divergence.py`:

```python
def bucket_for(order: dict, options: list[Option]) -> str:
    """Which bucket this order falls in, given the options that corps was
    offered. See BUCKETS.

    A one-entry list holding only the hold option makes index 0 both first and
    last; 'hold' wins, because taking the only offered option when that option
    is inaction is not a sign of a commander thinking for himself.
    """
    chosen = (order["posture"], order.get("objective"))
    if chosen not in options:
        return "off-menu"
    index = options.index(chosen)
    if index == len(options) - 1 and chosen[0] in ("defend", "reserve"):
        return "hold"
    return "first" if index == 0 else "middle"
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_divergence.py -q
```

Expected: PASS, 13 tests.

- [ ] **Step 5: Run the full suite and lint**

```bash
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

- [ ] **Step 6: Commit**

```bash
git add commanders/divergence.py tests/test_divergence.py
git commit -m "Bucket an order against the options its staff offered"
```

---

### Task 3: Score a whole transcript

**Files:**
- Modify: `commanders/divergence.py`
- Test: `tests/test_divergence.py`

**Interfaces:**
- Consumes: `parse_staff_options`, `bucket_for`.
- Produces: `score_transcript(transcript: dict) -> tuple[Counter, int]` — `(bucket counts, unscored count)`.

Two things make this more than a loop:

1. **Score the model's own first attempt.** `salvage_orders` forces illegal orders to `defend`. Scoring the final validated set would count an engine repair as the model going passive — the exact false positive this metric exists to avoid. `transcript["attempts"][0]["response"]` is the raw model reply; fall back to `transcript["orders"]` only when a transcript has no `attempts` key at all (older logs).
2. **An unreadable first attempt scores nothing.** When the raw reply will not parse, we cannot know what the model chose — but we *do* know how many corps it was briefed on, so that many orders go to `unscored`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_divergence.py`:

```python
import json as _json

from commanders.divergence import score_transcript


def _transcript(state, commander, attempts=None, final_orders=None):
    briefing = build_briefing(state, commander)
    out = {
        "commander": commander,
        "request": {"messages": [
            {"role": "system", "content": "persona"},
            {"role": "user", "content": briefing},
        ]},
        "orders": {"orders": final_orders or []},
    }
    if attempts is not None:
        out["attempts"] = attempts
    return out


def test_scores_the_orders_of_a_clean_transcript():
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": [
        {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
        {"corps_id": "xlvi_pz", "posture": "advance", "objective": "pripyat"},
        {"corps_id": "xlvii_pz", "posture": "defend", "objective": None},
    ]})
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": reply}])
    )
    assert buckets == Counter({"first": 1, "middle": 1, "hold": 1})
    assert unscored == 0


def test_scores_the_first_attempt_not_the_salvaged_result():
    # The model ordered an attack; salvage forced all three to defend. Scoring
    # the final set would report this commander as passive when he was not.
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": [
        {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
    ]})
    forced = [{"corps_id": "xxiv_pz", "posture": "defend", "objective": None}]
    buckets, _ = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": reply}, {"response": "x"}],
                    final_orders=forced)
    )
    assert buckets == Counter({"first": 1})


def test_an_unreadable_first_attempt_scores_nothing_and_counts_its_corps():
    state = load_scenario(DATA_DIR)
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": "not json at all"}])
    )
    assert buckets == Counter()
    assert unscored == 3          # guderian was briefed on three corps


def test_falls_back_to_the_final_orders_when_there_are_no_attempts():
    state = load_scenario(DATA_DIR)
    final = [{"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"}]
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", final_orders=final)
    )
    assert buckets == Counter({"first": 1})
    assert unscored == 0


def test_an_order_for_an_unbriefed_corps_is_unscored():
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": [
        {"corps_id": "ghost_pz", "posture": "attack", "objective": "minsk"},
    ]})
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": reply}])
    )
    assert buckets == Counter()
    assert unscored == 1
```

Add `from collections import Counter` to the top of the test file.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_divergence.py -q
```

Expected: FAIL — `ImportError: cannot import name 'score_transcript'`

- [ ] **Step 3: Implement the scorer**

Append to `commanders/divergence.py`:

```python
def _first_attempt_orders(transcript: dict) -> list[dict] | None:
    """The orders the MODEL chose, before the engine touched them.

    salvage_orders forces illegal orders to 'defend', so scoring the validated
    set would count an engine repair as the model going passive. Returns None
    when the raw reply cannot be read at all.
    """
    attempts = transcript.get("attempts")
    if not attempts:
        return list(transcript["orders"]["orders"])
    try:
        return list(json.loads(attempts[0].get("response") or "")["orders"])
    except (ValueError, TypeError, KeyError):
        return None


def score_transcript(transcript: dict) -> tuple[Counter, int]:
    """(bucket counts, unscored) for one commander-turn."""
    briefing = next(
        (m["content"] for m in transcript["request"]["messages"] if m["role"] == "user"),
        "",
    )
    options = parse_staff_options(briefing)
    orders = _first_attempt_orders(transcript)
    if orders is None:
        # We cannot know what he chose, but we know how many corps he held.
        return Counter(), len(options)
    buckets: Counter = Counter()
    unscored = 0
    for order in orders:
        corps_options = options.get(order.get("corps_id"))
        if not corps_options:
            unscored += 1
            continue
        buckets[bucket_for(order, corps_options)] += 1
    return buckets, unscored
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_divergence.py -q
```

Expected: PASS, 18 tests.

- [ ] **Step 5: Run the full suite and lint**

```bash
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

- [ ] **Step 6: Commit**

```bash
git add commanders/divergence.py tests/test_divergence.py
git commit -m "Score a commander-turn against its staff options"
```

---

### Task 4: Aggregate and report

**Files:**
- Modify: `commanders/divergence.py`
- Create: `analyze_divergence.py`
- Test: `tests/test_divergence.py`

**Interfaces:**
- Consumes: `score_transcript`, `BUCKETS`.
- Produces: `summarize(transcripts: Iterable[dict]) -> dict[str, tuple[Counter, int]]` — commander id to `(bucket counts, unscored)`, with the aggregate under the key `"ALL"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_divergence.py`:

```python
from commanders.divergence import summarize


def test_summarize_groups_by_commander_and_totals_under_all():
    state = load_scenario(DATA_DIR)
    aggressive = _json.dumps({"orders": [
        {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
    ]})
    passive = _json.dumps({"orders": [
        {"corps_id": "xxxix_pz", "posture": "defend", "objective": None},
    ]})
    rows = summarize([
        _transcript(state, "guderian", attempts=[{"response": aggressive}]),
        _transcript(state, "hoth", attempts=[{"response": passive}]),
    ])
    assert rows["guderian"][0] == Counter({"first": 1})
    assert rows["hoth"][0] == Counter({"hold": 1})
    assert rows["ALL"][0] == Counter({"first": 1, "hold": 1})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_divergence.py -q
```

Expected: FAIL — `ImportError: cannot import name 'summarize'`

- [ ] **Step 3: Implement the aggregation**

Append to `commanders/divergence.py`:

```python
def summarize(transcripts: Iterable[dict]) -> dict[str, tuple[Counter, int]]:
    """commander id -> (bucket counts, unscored), plus the total under "ALL"."""
    rows: dict[str, tuple[Counter, int]] = {}
    total: Counter = Counter()
    total_unscored = 0
    for transcript in transcripts:
        commander = transcript["commander"]
        buckets, unscored = score_transcript(transcript)
        prior, prior_unscored = rows.get(commander, (Counter(), 0))
        rows[commander] = (prior + buckets, prior_unscored + unscored)
        total += buckets
        total_unscored += unscored
    rows["ALL"] = (total, total_unscored)
    return rows
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_divergence.py -q
```

Expected: PASS, 19 tests.

- [ ] **Step 5: Write the reporting script**

Create `analyze_divergence.py`:

```python
"""Dev tool: staff-option divergence per commander.

Answers "is this model still playing a character, or just taking the staff's
first suggestion every time?" - offline, free, no LLM calls.

  .\\.venv\\Scripts\\python.exe analyze_divergence.py            # newest run
  .\\.venv\\Scripts\\python.exe analyze_divergence.py run-20260816-170643/campaign
"""

import json
import sys
from pathlib import Path

from commanders.divergence import BUCKETS, summarize
from commanders.runlog import resolve_log_dir

log_dir = resolve_log_dir(sys.argv[1] if len(sys.argv) > 1 else None,
                          Path(__file__).parent / "logs")


def models_used(directory: Path) -> str:
    tokens = directory / "tokens.jsonl"
    if not tokens.exists():
        return "unknown model"
    names = {
        json.loads(line)["model"]
        for line in tokens.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    return ", ".join(sorted(names)) or "unknown model"   # sorted: determinism


transcripts = [
    json.loads(f.read_text(encoding="utf-8")) for f in sorted(log_dir.glob("turn*.json"))
]
if not transcripts:
    print(f"no commander transcripts in {log_dir}")
    raise SystemExit(0)

rows = summarize(transcripts)
print(f"{log_dir.parent.name}  {models_used(log_dir)}")
header = f"{'commander':12}{'n':>5}  " + "".join(f"{b:>9}" for b in BUCKETS) + f"{'unscored':>10}"
print(header)
for commander in sorted(rows, key=lambda c: (c == "ALL", c)):
    buckets, unscored = rows[commander]
    n = sum(buckets.values())
    cells = "".join(f"{(100 * buckets[b] / n if n else 0):>8.0f}%" for b in BUCKETS)
    print(f"{commander:12}{n:>5}  {cells}{unscored:>10}")
```

- [ ] **Step 6: Run it against a real run**

```bash
.\.venv\Scripts\python.exe analyze_divergence.py
```

Expected: a table of every commander in the newest run, percentages summing to
100 per row. Sanity-check two things before trusting it: `unscored` should be
small (single digits over a 4-turn run), and `off-menu` should be non-zero —
0% off-menu across every commander means either genuine collapse or a broken
parser, so confirm against a transcript by hand before reporting it as collapse.

- [ ] **Step 7: Run the full suite and lint**

```bash
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

- [ ] **Step 8: Commit**

```bash
git add commanders/divergence.py analyze_divergence.py tests/test_divergence.py
git commit -m "Report staff-option divergence per commander"
```

---

### Task 5: Record the baseline

**Files:**
- Modify: `docs/superpowers/specs/2026-08-16-staff-divergence-design.md`

The metric is only useful against a reference. Today's runs are on disk and are the natural baseline: `run-20260816-164524` (qwen3.5-4b), `run-20260816-165131` (qwen/qwen3.5-9b), `run-20260816-170643` (9b, after the addressee fix).

- [ ] **Step 1: Measure all three runs**

```bash
.\.venv\Scripts\python.exe analyze_divergence.py run-20260816-164524/campaign
.\.venv\Scripts\python.exe analyze_divergence.py run-20260816-165131/campaign
.\.venv\Scripts\python.exe analyze_divergence.py run-20260816-170643/campaign
```

- [ ] **Step 2: Append the numbers to the spec**

Add a `## Baseline (measured 2026-08-16)` section holding the three `ALL` rows
verbatim, each labeled with its model and run id. State the sample size (36
commander-turns per run) and note that these are 4-turn runs, so per-commander
rows rest on ~12 orders and are indicative rather than settled.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-08-16-staff-divergence-design.md
git commit -m "Record the divergence baseline for 4b and 9b"
```

---

## Self-review notes

- **Spec coverage:** buckets (T2), per-commander plus aggregate (T4), first-attempt scoring (T3), `unscored` (T3), raising on unknown options (T1), model name in output (T4), empty-log-dir handling (T4 script), the four-bucket output table (T4). Non-goals stay out: no trend file, no pass/fail threshold, no changes to `_staff_options`.
- **Deviation from the spec, deliberate:** the spec's Decisions section says the fallback to final orders "is the common path". That is wrong — `attempts[0]` is present and parseable in the 80–97% clean case, so the first-attempt path is the common one and the fallback covers transcripts with no `attempts` key. The plan implements the correct behavior; fix the spec's wording during Task 5.
- **Type consistency:** `Option`, `BUCKETS`, `parse_staff_options`, `bucket_for`, `score_transcript`, `summarize` are used with identical names and signatures across tasks. `score_transcript` and `summarize` both return `Counter` (not `dict`), which the tests compare against `Counter(...)`.
