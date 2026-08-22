# Dynamic per-briefing order schema — spec + plan

**Written 2026-08-22 by the benchmarking session (E:\programming\ai ssd).
This document is self-contained: everything the implementing session needs is
here or in this repo. The benchmarking notebook is reference-only — do not
work in it.**

## Why (measured, 2026-08-22, on this game's own captured briefings)

A contract-compliance instrument replayed 12 real captured briefings from
this game's logs against local models, scoring 13 machine-checkable
constraints ported from `engine/orders.py::validate_orders`. Measured on
`qwen/qwen3.6-35b-a3b` (the June campaigns' model), 48 samples per arm,
llama.cpp b10441:

| arm | compliance |
|---|---|
| no schema | 0.575 |
| **static `ORDER_SCHEMA`** (what production sends today) | **0.982** |
| **dynamic per-briefing schema** (this spec) | **1.000 — every constraint, every sample** |

What the static schema cannot express, measured as its entire residue:

1. **`objective` range** — the model orders objectives beyond staff reach
   (out-of-range regions, and once a *misspelled* region id on another
   model: `"bialsytok"`). ~0.5 pts.
2. **The defend/reserve ⇒ objective-null conditional** — the 35B habitually
   fills `objective` with the place being defended
   (`{"posture": "defend", "objective": "borisov"}`). ~1.3 pts. With the
   dynamic schema, the same seed produced the same `defend` decision with
   `objective` correctly null — **the constraint corrects the field, not
   the decision**, because properties generate in order
   `corps_id → posture → objective`, so the model chooses its posture
   freely and only then is the objective conditioned on it.
3. Corps identity (`corps_id` must be an owned corps) — free with per-corps
   branches.

Also verified: per-request distinct grammars decode correctly under 3-way
concurrency (0 empties/errors, 48 samples), grammar adds no measurable
latency, and **the only failure mode left is token-budget truncation of
grammar-legal output** — which this game does not share, because `_payload`
sets no `max_tokens` (the bound is the server context).

Context you do NOT need to re-derive: the June "empty response" storm and
the `kimi-k2.6p` empties were diagnosed and are already fixed in this repo
(`00f6a54` concurrency gate, `822ee88` surfaced 4xx, `ced17e7` warm-up).
No action on empties.

## What to build

Replace the static `ORDER_SCHEMA` in the **orders request only**
(`LMStudioClient.request_orders` → `_payload`) with a schema generated per
call from the same game state the briefing is built from. `request_text`
(staff reports, conversations) is untouched.

### Schema shape

Top level identical to today's `ORDER_SCHEMA` (`orders`/`dispatch`/
`reasoning`, `required` all three, `additionalProperties: false`). The
change is inside `orders`:

```python
"orders": {
    "type": "array",
    "items": {"oneOf": branches},      # two branches per living owned corps
    "minItems": len(own_corps),
    "maxItems": len(own_corps),
}
```

Per corps C, in this property order:

```python
# movement branch
{"type": "object",
 "properties": {
     "corps_id": {"const": C.id},
     "posture": {"type": "string", "enum": ["attack", "advance"]},
     "objective": {"enum": sorted(legal_destinations(C))}},
 "required": ["corps_id", "posture", "objective"],
 "additionalProperties": False}

# static branch
{"type": "object",
 "properties": {
     "corps_id": {"const": C.id},
     "posture": {"type": "string", "enum": ["defend", "reserve"]},
     "objective": {"const": None}},
 "required": ["corps_id", "posture", "objective"],
 "additionalProperties": False}
```

A reference implementation (fixture-shaped inputs, same branch structure,
5 unit tests) exists at
`E:\programming\ai ssd\tools\quality_eval\dynamic_schema.py` — port the
shape, not the file; this repo's version must be driven by game types.

### ⚠ Settled design decisions — do not re-derive, do not weaken

1. **The objective enum comes from the VALIDATOR's set, not the briefing's
   display list.** `engine/orders.py::_reach_options` is the named single
   source of truth ("a rejection can never name a destination the validator
   would then refuse") — call that (promote it or wrap it publicly; do not
   duplicate its body). The validator additionally accepts
   `objective == corps.location` (`_check_order`), so:
   `legal_destinations(C) = _reach_options(...)[0] | {C.location}`.
   Using the briefing's `_staff_options` instead would FORBID orders the
   validator accepts (staff options are capped at `MAX_OPTIONS_PER_CORPS`
   and sorted for display) — a schema/validator disagreement guarantees a
   repair loop. The equivalence test below is the guard.
2. **Sort every enum.** The sets come from `reachable()`; this codebase's
   determinism rule (CLAUDE.md: never iterate a set where output depends on
   order) applies to the schema bytes themselves — unsorted enums make the
   request body vary across `PYTHONHASHSEED`.
3. **Property order `corps_id → posture → objective`** in both branches —
   this is what makes the conditional bind after the model's posture choice
   (measured; see Why §2).
4. **Keep `minItems == maxItems == len(own living corps)`.** Coverage
   (each corps exactly once) is NOT expressible in the schema; count
   pinning plus the existing validator handles it. Measured: coverage was
   1.000 under the schema anyway.
5. **A corps with no reachable destination still gets its movement branch**
   (its enum then contains only `corps.location`) — the validator accepts
   attack/advance at own location, so the schema must too.
6. **No living corps ⇒ do not build a schema and do not call the model.**
   Verify what `request_orders` does today for a corpsless commander and
   preserve it; an empty `oneOf` is a grammar that matches nothing.
7. **`validate_orders` and the repair/salvage/fallback ladder stay exactly
   as they are.** Defense in depth: enforcement is a *backend* property.
   Production logs prove LM Studio can silently not enforce
   (fences and renames arrived DESPITE `strict: true`); llama.cpp enforces
   airtight. The schema narrows what a conforming backend can emit; the
   validator remains the authority.
8. **Backend rejection must degrade, not crash.** Today a non-transient
   4xx raises `LMStudioUnavailable` and kills the turn. A cloud backend
   that rejects `oneOf`/`const`-heavy schemas would therefore brick
   campaigns. Required behavior: if the dynamic-schema request is rejected
   with a non-transient 4xx, retry that call once with the static
   `ORDER_SCHEMA` and log loudly which schema was used; only raise if the
   static retry also fails. (`ORDER_SCHEMA` therefore stays in
   `prompts.py`.)

## Plan (TDD, this repo's conventions)

Commands: `.\.venv\Scripts\python.exe -m pytest` and
`.\.venv\Scripts\python.exe -m ruff check .` — both green before and after.
Failing test first at every step.

1. **Read first**: this spec; `commanders/prompts.py` (ORDER_SCHEMA, RULES);
   `commanders/llm.py` (`request_orders`, `_payload`, `_chat`);
   `engine/orders.py` (`validate_orders`, `_check_order`, `_reach_options`);
   `commanders/briefing.py::_staff_options` (to see why it is NOT the
   source); `tests/test_concurrency.py` + neighbors for the mocked-transport
   test style.
2. **Schema builder** — `dynamic_order_schema(state, commander) -> dict` in
   `commanders/prompts.py` (it may import from `engine`; the engine must
   not import it). Unit tests: two branches per corps; conditional null on
   the static branch; enums sorted; current location always present in the
   movement enum; min/max items pinned; top-level shape identical to
   `ORDER_SCHEMA`'s; corpsless commander refused.
3. **⭐ The equivalence test (the load-bearing one)**: on a real scenario
   state, for every branch of every corps, every `(corps_id, posture,
   objective)` the schema can represent passes `validate_orders` as a
   single-order set — and conversely, any single order `validate_orders`
   accepts is representable by some branch. This is the test that makes
   decision 1 permanent; without it the schema and validator drift apart
   silently.
4. **Wire in** — `request_orders` builds the schema from the same `state`
   it builds the briefing from and passes it to `_payload`. Repair
   round-trips reuse the same dynamic schema.
5. **Fallback path** — mocked transport returning 400 on the dynamic
   request: assert one retry with static `ORDER_SCHEMA`, a loud log line,
   and no `LMStudioUnavailable` unless both fail. Transient 4xx and 5xx
   behavior unchanged.
6. **Full suite + ruff green.** Then, if a live server is available, a
   smoke: `probe_llm.py` / one `verify_turn.py` turn; afterwards
   `analyze_logs.py` on the new run — expect `ok` to dominate and zero
   `unparseable`. (A one-call smoke proves wiring, not quality — the rate
   comes from the log analysis.)
7. **Docs**: README's config section if any knob was added (prefer none —
   the fallback makes a toggle unnecessary).

## Out of scope

- Anything in `engine/` beyond making `_reach_options` publicly callable.
- `request_text` / staff reports (no schema there today; keep it that way).
- Retry-on-`finish_reason=length`: with no `max_tokens` the game does not
  truncate; the repair ladder already catches the theoretical case. At most
  log `finish_reason` per call if trivial.
- The empties/concurrency work — already fixed and verified (see Why).
