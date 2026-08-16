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

## Decisions taken

1. **Per commander, not pooled.** Personality is per persona; a cautious Kluge
   and a reckless Guderian *should* differ, and pooling hides exactly the
   signal. An aggregate row is reported as well, for run-to-run comparison.
2. **Score the model's first attempt, falling back to the final orders.**
   Salvage *forces* unparseable or illegal orders to `defend`
   (`engine/orders.py:salvage_orders`). Scoring the final validated set would
   count engine repairs as the model collapsing into passivity — precisely the
   false positive this metric exists to avoid. Most orders are clean on the
   first try (80–97% depending on model), so the fallback is the common path.
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

def bucket_for(order: dict, options: list[Option]) -> str:
    """order is {corps_id, posture, objective}.
    Returns 'first' | 'middle' | 'hold' | 'off-menu'."""

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
