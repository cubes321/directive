# Staff-option divergence: measuring personality collapse

**Status: APPROVED — design agreed 2026-08-16, ready for an implementation plan.**
**Date:** 2026-08-16

## The idea

A number that answers "is this model still playing a character, or is it just
taking the staff's first suggestion every time?" — computed offline from logs
already on disk, for free, with no LLM calls.

It exists to make model swaps decidable. Turn time and order validity are
already measured (`analyze_logs.py`, `tokens.jsonl`); both stayed green while
the thing that actually matters could rot silently. As the cost baseline puts
it: the real risk of a smaller model isn't broken JSON, it's a student that
regresses to always taking staff option #1 while every schema check passes.

## What it measures

Each corps order is scored against the staff options that corps was offered in
its own briefing, and lands in one of four buckets:

| bucket | meaning |
| --- | --- |
| `first` | took the staff's lead suggestion |
| `middle` | took a suggestion that was neither first nor the hold option |
| `hold` | took the last option — hold position, or hold in reserve |
| `off-menu` | ordered something that was not offered at all |

### Why buckets rather than raw rank

`_staff_options` (`commanders/briefing.py:85`) emits at most
`MAX_OPTIONS_PER_CORPS = 3` entries: up to two moves, then always a hold option
appended last. A corps in a quiet rear area may get only one move, so its list
is two long — and there, "option 2" *is* the hold option, while in a three-long
list option 2 is a genuine move. Raw indices would silently mix the two.

Buckets also encode the fact that the list is not neutral: moves are sorted
attacks-on-spotted-enemies first, so option #1 is nearly always the aggressive
choice and the last is always inaction. That makes `first` and `hold` the two
*opposite* collapse modes, and a single "divergence from option 1" fraction
cannot tell them apart. It would score a model that sits still forever as
maximally independent.

`off-menu` is the strongest positive signal: the commander chose an objective
its staff never raised. Observed in real play — `xlvii_pz` ordered to advance on
`slutsk` when the options offered were Minsk and Slonim.

The originally-scoped metric is recoverable: divergence = 100% − `first`.

### What `off-menu` deliberately excludes

Being the strongest positive signal makes `off-menu` the bucket most worth
defending, and the first implementation leaked three things into it that are
not independence at all — between 44% and 77% of the bucket, measured on the
runs below. Anyone touching the matching in `bucket_for` must keep all three
out:

1. **The other move verb.** `attack` and `advance` are one order to the engine:
   `engine/turn.py:138` is the only place either posture is read and it reads
   them jointly. So "advance to Minsk" against a staff option of "attack Minsk"
   is compliance. Scored apart, the metric could be defeated by exactly the
   collapse it exists to detect — a model that always takes option #1 but
   writes the other verb would score 0% `first` and 100% `off-menu`. Matching
   is therefore on `(move-class, objective)`.
2. **The other word for sitting still.** `defend` and `reserve` are the same
   physical inaction, differing only in recovery (`engine/turn.py:268`), and
   which one the staff offers is a pure function of that corps's own supply and
   organization (`commanders/briefing.py:110`). A corps told to sit still must
   never land in the independence bucket because of its own supply level: a
   hold-posture order scores `hold` whenever the menu ends in a hold option.
   The engine ignores `objective` for those postures, so a stray one (observed:
   `sov_13a`, sitting in Minsk, ordered "defend / minsk") cannot change that.
3. **An objective the corps cannot reach.** That order is rejected by
   `validate_orders` and forced to `defend` by `salvage_orders` — a model
   failure scored as brilliance. The legal set is already in the briefing (the
   `In range this week:` line, read via its `[id: ...]` markers so the
   `(FULL - no room)` annotation is ignored — a full region is still a legal
   objective, the move merely bounces). Such orders go to `unscored`, not to a
   fifth bucket: validity is `analyze_logs.py`'s beat, and `unscored` already
   means "this order told us nothing about the model's character".

### The menu shape is endogenous — report it

`middle` is only reachable on a three-long menu, and only ~27% of briefings
have one. Worse, the shape is itself an output of model behaviour: a model that
advances reaches contact and *earns* three-long attack menus, while a passive
one keeps drawing two-long ones — so a run-to-run comparison is partly
circular. `analyze_divergence.py` therefore prints the run's menu-shape mix
above the table (`menu shape (120 corps-briefings) 1 option: 4, 2 options: 83,
3 options: 33`), so a reader can see whether two runs are comparable before
reading anything into the difference.

## Decisions taken

1. **Per commander, not pooled.** Personality is per persona; a cautious Kluge
   and a reckless Guderian *should* differ, and pooling hides exactly the
   signal. An aggregate row is reported as well, for run-to-run comparison.
2. **Score the model's first attempt, falling back to the final orders.**
   Salvage *forces* unparseable or illegal orders to `defend`
   (`engine/orders.py:salvage_orders`). Scoring the final validated set would
   count engine repairs as the model collapsing into passivity — precisely the
   false positive this metric exists to avoid. Most orders are clean on the
   first try (80–97% depending on model), so the first-attempt path is the
   common one; the fallback to final orders only covers transcripts that have
   no `attempts` key at all.
3. **The briefing scored against is the original one** — `messages[1]` — never
   the repair message, which quotes validation errors rather than options.

## Architecture

Two pieces, following the precedent of `commanders/replay.py` (an analysis
harness that lives in `commanders/` and is unit-tested):

- **`commanders/divergence.py`** — pure logic, no file IO. Takes strings and
  dicts, returns counts. This is what the tests exercise.
- **`analyze_divergence.py`** — top-level script doing the IO and printing,
  mirroring `analyze_logs.py`: `resolve_log_dir(sys.argv[1] or None, logs/)`,
  iterate `*.json`, print a table.

This keeps the IO/logic split the codebase already uses (`engine/telemetry.py`
builds, `Campaign._write_turn_log` writes) and makes the parsing testable
without needing a log directory on disk.

### Interfaces

```python
Option = tuple[str, str | None]          # (posture, objective_id)

def parse_staff_options(briefing: str) -> dict[str, list[Option]]:
    """corps_id -> its options, in the order the briefing listed them."""

def parse_in_range(briefing: str) -> dict[str, set[str]]:
    """corps_id -> the regions it may legally be sent to this week.
    Absent (not empty) when the briefing carried no "In range" line."""

def bucket_for(order: dict, options: list[Option],
               in_range: set[str] | None = None) -> str:
    """order is {corps_id, posture, objective}.
    Returns 'first' | 'middle' | 'hold' | 'off-menu' | 'unscored'."""

def menu_shapes(transcripts) -> Counter:
    """options offered -> how many corps-briefings offered exactly that many."""

def score_transcript(transcript: dict) -> tuple[dict[str, int], int]:
    """(bucket counts, unscored_count) for one commander-turn."""
```

**Bucket precedence.** A corps with nothing in reach gets a one-entry option
list containing only the hold option — so index 0 is simultaneously first and
last. `hold` wins: taking the only offered option, when that option is
inaction, is not independence. Concretely, the last option is classified as
`hold` whenever its posture is `defend` or `reserve`, before `first` is
considered.

### Option string → (posture, objective)

Parsed by prefix; objective ids come from the `[id: ...]` markers already
present in the text.

| option text | posture | objective |
| --- | --- | --- |
| `attack X [id: x] - defended by ...` | `attack` | `x` |
| `advance to X [id: x] (no known enemy)` | `advance` | `x` |
| `close up toward the front at X [id: x]` | `advance` | `x` |
| `hold in reserve to recover organization and supply` | `reserve` | `None` |
| `hold current position` | `defend` | `None` |

An option line that matches none of these is a parser failure, not an
`off-menu` order: it must raise rather than silently score every order in that
briefing as independent. If `_staff_options` gains a new phrasing, this metric
must be updated with it, and a loud failure is how that gets noticed.

## Error handling

One counter, `unscored`, covers both cases below. Both mean "this order told us
nothing about the model's character", and splitting them would imply a
distinction the reader cannot act on.

- **First attempt that will not parse as JSON** → `unscored`, excluded from the
  bucket denominator. A model's malformed output must not masquerade as a
  behavior signal.
- **An order for a corps with no options in the briefing** (destroyed or
  transferred mid-turn) → `unscored`.
- **A log directory with no transcripts** → print a clear message, exit 0.

## Output

Format only — the numbers below are invented, not measured.

```
run-20260816-170643  qwen/qwen3.5-9b
menu shape (119 corps-briefings) 1 option: 5, 2 options: 76, 3 options: 38
commander      n   first  middle    hold  off-menu
guderian      12    33%      25%      8%       33%
kluge         12    17%      33%     42%        8%
...
ALL           36    28%      29%     22%       21%          (unscored: 2)
```

Model name is read from `tokens.jsonl` so runs are self-labeling.

## Testing

TDD, against the mocked-transport-free pure functions:

- each option-string shape parses to the right `(posture, objective)`
- an unrecognized option line raises
- a two-option list scores index 1 as `hold`, not `middle`
- a three-option list scores index 1 as `middle`
- a one-option list holding only `hold current position` scores as `hold`, not
  `first`
- an order matching no option is `off-menu`
- a salvaged transcript scores the model's first attempt, not the forced
  `defend`
- a single-attempt transcript falls back to the final orders
- an unparseable first attempt counts as `unscored` and leaves buckets empty

## Non-goals

- No trend tracking or history file. Runs are compared by eye, by running the
  script against two log dirs.
- No pass/fail threshold. What counts as collapse depends on the personas and
  is a judgment call; the metric informs it rather than making it.
- No changes to `_staff_options` or the briefing. This is a read-only
  instrument; changing what it measures while building it would invalidate the
  baseline it exists to establish.

## Next step

`superpowers:writing-plans` for the implementation plan.

## Baseline (re-measured 2026-08-16, after the off-menu fix)

Measured by running `analyze_divergence.py` against the three same-day runs.
Sample size: 36 commander-turns per run (9 commanders × 4 turns each); the
`n` column below is the total corps-orders scored from those 36 transcripts,
which differs slightly by run because commanders command varying numbers of
corps. Per-commander rows (not reproduced here) rest on roughly a dozen
orders each and are indicative rather than settled — treat only the `ALL`
row as a run-level signal.

An earlier version of this table (4b 22/8/32/38, 9b 33/9/12/45, 9b-post
34/12/13/40) was produced by the buggy scoring described under "What
`off-menu` deliberately excludes" and is void: it showed the 4b model as the
*more* independent of the two, which was an artifact of it writing the wrong
move verb and naming unreachable regions more often.

| run | model | menu shape (1 / 2 / 3 options) | n | first | middle | hold | off-menu | unscored |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `run-20260816-164524` | qwen3.5-4b | 4 / 83 / 33 | 112 | 29% | 9% | 48% | 14% | 9 |
| `run-20260816-165131` | qwen/qwen3.5-9b | 6 / 82 / 32 | 119 | 47% | 9% | 21% | 23% | 1 |
| `run-20260816-170643` | qwen/qwen3.5-9b (post addressee fix) | 5 / 76 / 38 | 116 | 41% | 12% | 23% | 23% | 3 |

The reading reverses. The 4b model is not more independent, it is *more
passive*: 48% `hold` against the 9b's 21–23%, and only 14% `off-menu` against
23%. The 9b runs take the staff's lead suggestion far more often (47% and 41%
vs 29%) but, when they leave the menu, leave it for somewhere they can
actually go.

`unscored` still separates the models the same way, and for the reasons the
counter exists: 9 for the 4b run against 1 and 3 for the 9b runs — first
attempts that would not parse, orders for corps with no briefed options, and
(the new contributor) objectives out of reach. Six of the 4b's nine are
"advance to the region I am already standing in", which `validate_orders`
accepts but the engine discards as a no-op; they belong in `unscored` either
way, since they tell us nothing about the commander's character.

The menu-shape mixes are close enough across the three runs (27–32% three-long)
that the `middle` column is comparable between them. That will not always hold.
