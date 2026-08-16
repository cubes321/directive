# Signals intelligence: intercepted enemy orders

**Status: PROPOSED — one open question left (frequency); the delivery model is settled.**
**Date:** 2026-08-02

## The idea

Occasional intelligence briefings, 100% correct, available to both sides.
Related to the long-standing backlog item "signals intercepts (leak enemy
dispatch fragments as intel)".

## Decisions taken

The first two were chosen during brainstorming on 2026-08-02; the third settled
open question 1 on 2026-08-16.

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

3. **The player distributes his own side's intelligence; the AI side
   broadcasts.** A decrypt his side makes lands in his inbox and reaches no
   commander until he signals one. The Soviet side puts it in every Soviet
   briefing, because there is no player there to distribute it. The asymmetry is
   deliberate: it keeps intelligence inside the loop the game is actually about
   — the player deciding what his subordinates know — and it costs no new
   briefing plumbing on the player's side, since relaying rides the existing
   conversation channel.

Rejected: unreliable or partial intelligence. The drama should come from acting
on a true decrypt, not from second-guessing it. Also rejected for decision 3:
broadcasting into every friendly briefing (removes the player's judgment), and
delivering only to the commander facing that sector (one cautious general can
swallow a whole campaign's worth of intercepts).

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

- **Asymmetric by design, because only one side has a player** (decided
  2026-08-16, see Decisions taken).
  - *The player's side:* the decrypt goes to his **inbox only**. It reaches a
    commander's briefing when the player relays it, through the existing
    conversation channel — `Campaign.converse` writes into the commander's
    thread and `build_briefing` already renders it under `RECENT EXCHANGES WITH
    YOUR COMMANDER-IN-CHIEF`. No new briefing plumbing on this path.
  - *The Soviet side:* into the `SIGNALS INTELLIGENCE` block of **every**
    Soviet commander's briefing, alongside `ENEMY CONTACTS`. There is no player
    there to distribute it, so broadcast is the only rule that lets the AI side
    act on intelligence at all.
- **Into the player's inbox** as a dispatch from `"intel"`, styled like the
  `staff` and `okh` cards, when his own side intercepted.
- **The card must say, in its own text, that the commanders have not been told.**
  A player who assumes the decrypt was distributed will watch his commanders
  ignore it and read that as the LLM being stupid, when in fact nobody informed
  them — the worst kind of confusion, because it discredits the commanders for
  the player's own omission. One closing line on the card carries it, e.g.
  *"This decrypt has not been circulated. Signal a commander if you want him to
  act on it."* It is prose on the card, not a rule the engine enforces, in
  keeping with "briefings advise, the engine enforces".
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
- **an axis intercept reaches the player's inbox and NO axis briefing** — the
  asymmetry of decision 3, and the one most likely to be quietly "fixed" back
  into a broadcast by a later change
- a soviet intercept reaches every soviet briefing
- the player's intel card states that the decrypt has not been circulated

## Open questions

1. ~~**Who on the receiving side sees the decrypt?**~~ **Settled 2026-08-16:
   the player decides on his own side; the AI side broadcasts.** An intercept
   his side makes reaches his inbox and goes no further until he signals a
   commander himself. Rejected: broadcasting into every friendly briefing, which
   takes the player's judgment out of a game whose premise is that he commands
   by directive; and delivering only to the commander facing that sector, which
   with roughly six intercepts a campaign can be swallowed whole by one cautious
   general. The Soviet side broadcasts because there is no player there to
   distribute it — the asymmetry is the point, not an inconsistency.

   Consequence: **the inbox card must state that the commanders have not been
   told** (see Delivery). Without that line the feature reads as broken.

2. **Is 0.25 per side per turn "occasional" enough?** Over a 24-turn campaign
   that is roughly six intercepts each way. Note that decision 1 raises the cost
   of each one: an intercept the player does not relay does nothing, and
   relaying spends a conversation turn. That argues for keeping the rate low —
   a decrypt should feel like a prize, not an inbox chore — but it is worth
   re-checking against real play before fixing the number.

## Next step

Delivery is settled; only the frequency number is open, and it is a tuning
constant (`Campaign.intel_chance`) rather than a design fork — it can ship at
0.25 and be adjusted after play. So this spec is ready for
`superpowers:writing-plans`.
