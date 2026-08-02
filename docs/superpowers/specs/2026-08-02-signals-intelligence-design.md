# Signals intelligence: intercepted enemy orders

**Status: PROPOSED — design presented, not yet approved. Two open questions at the end.**
**Date:** 2026-08-02

## The idea

Occasional intelligence briefings, 100% correct, available to both sides.
Related to the long-standing backlog item "signals intercepts (leak enemy
dispatch fragments as intel)".

## Decisions taken

Both were chosen explicitly during brainstorming.

1. **What it reveals: enemy intent — their actual orders.** Not sharpened
   strength figures, and not dispositions beyond recon range. An intercept
   names what an enemy commander was ordered to do. This is the most
   thematically apt option in a game about directives — intercepting one is the
   natural prize — and the engine already holds the data, so it is exact by
   construction rather than by estimation.
2. **Scope: one commander's full order set.** Every corps he was given, with
   posture and objective. A commander is the natural unit because it is how
   orders are actually issued; it is self-limiting (he is one of four); and it
   reads like a decrypt rather than a hint.

Rejected: unreliable or partial intelligence. The drama should come from acting
on a true decrypt, not from second-guessing it.

## The constraint that shapes everything

**WEGO simultaneity makes this-week intercepts impossible.** `Campaign.play_turn`
builds briefings inside `gather_orders`, which collects orders from *all*
commanders concurrently — so at briefing-build time this turn's enemy orders do
not exist yet.

An intercept is therefore always of **last week's** orders. That is honest, and
it is what signals intelligence actually looked like: a step behind, but
revealing of an enemy's axis of effort, which persists.

## Design

### 1. Persist last week's orders — `engine/state.py`, `engine/turn.py`

`GameState` gains `last_orders: dict[str, dict]` — commander id to the
**validated** order set, written in `resolve_turn`. Validated, not raw, so the
intercept reports what the engine actually acted on, including salvaged and
fallback orders. That is what makes "100% correct" true rather than
approximately true.

Serialized in `to_dict`/`from_dict`; old saves default to `{}`. One turn of
orders for nine commanders is a small addition to the save.

### 2. Selection — new pure module `commanders/intel.py`

Mirrors `commanders/communique.py`: pure, seeded, deterministic, no LLM call.

```python
def intercept(state, side, rng, *, chance) -> dict | None
```

One roll per side per turn. On success, pick an enemy commander who actually
issued orders last turn, **weighted toward commanders whose corps are in contact
with yours** — you intercept the sector you are facing, not a radio net three
hundred miles away. Returns commander id, name, and the full order set.

Determinism: seed as `communique.py` does, and sort before any weighted choice.

### 3. Delivery — both sides, fog-safe

- **Into the briefing** of every commander on the receiving side, as a
  `SIGNALS INTELLIGENCE` block alongside `ENEMY CONTACTS`. This is what lets an
  LLM commander act on it.
- **Into the player's inbox** as a dispatch from `"intel"`, styled like the
  `staff` and `okh` cards, when his own side intercepted.
- **The Soviet intercept never reaches the player.** It enters Soviet briefings
  only. The snapshot already filters dispatches by side, so this follows the
  existing fog discipline rather than inventing a new rule.

Reading roughly:

```
SIGNALS INTELLIGENCE (decrypt of last week's enemy traffic - believed accurate):
  Timoshenko, Western Front:
    - 16th Army: attack Smolensk [id: smolensk]
    - 20th Army: advance to Orsha [id: orsha]
    - 19th Army: hold in reserve
```

Region names carry ids in brackets, matching the rest of the briefing.

### 4. Frequency

`Campaign.intel_chance`, defaulting to ~0.25 per side per turn — the same
pattern as `communique_chance`, so tests can force 1.0 or 0.0 and it is tunable
without touching code.

## Testing

- no intercept at chance 0; exactly one at chance 1
- the same seed picks the same commander
- a commander in contact is preferred over one far away
- the decrypt matches the **validated** orders, including a salvaged set
- `last_orders` round-trips through a save, and a save predating it loads
- **fog: a Soviet intercept never appears in the player's snapshot**
- the briefing block renders region names with ids

## Open questions — answer these before implementing

1. **Who on the receiving side sees the decrypt?** The design says every
   commander on that side, as an army-group-level intelligence product. The
   alternative is only the commander facing that sector, which is more
   plausible but much narrower and may waste most intercepts.
2. **Is 0.25 per side per turn "occasional" enough?** Over a 24-turn campaign
   that is roughly six intercepts each way.

## Next step

Once those are answered: finish the brainstorming flow (this spec is the
design-document step), then `superpowers:writing-plans` for the implementation
plan. Do not start implementing before the two questions above are settled.
