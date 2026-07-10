# Living commander morale — design

## Problem

Every commander's behaviour is driven only by *static* traits (aggression,
caution, ego, initiative, logistics). Guderian is ego-9 on turn 1 and identical
on turn 20, no matter what the campaign has done to him. `dossier.dynamic`
(`confidence` / `fatigue` / `relationship`) already exists and is saved, but
**nothing updates or reads it** — it is inert. (Note: the commander cards render
the static traits only; the morale values are echoed in the snapshot but not yet
drawn.)

Make morale *evolve* from what actually happens and from how the player treats
each commander, then feed the resulting mood into his prompt so his behaviour —
tone, aggression, and willingness to obey — responds to it.

## Approach (agreed)

**Psychological only.** Morale never touches the engine or combat maths. It
feeds a prose "current state" block into the commander's prompt; consequences
**emerge** from how the LLM responds. A confident Guderian lunges harder; an
estranged one bends or ignores the directive. This keeps the engine pure and the
emergent-personality value intact. No mechanical insubordination roll, no combat
modifier — both are easy later additions if wanted.

## Scale

`dossier.dynamic`, ints clamped **0–10**. Defaults unchanged: `confidence` 5,
`fatigue` 0, `relationship` 5. Small per-turn steps so mood drifts over weeks,
not snaps.

## Update logic — `update_morale(state, report, dossiers, player_side)`

Pure, in [commanders/records.py](../../../commanders/records.py), called each
turn next to `update_track_records`. Map corps → commander from `report.combats`
and `report.movements`. Per player-side commander, apply then clamp to [0, 10];
cap the net per-turn change to avoid wild swings.

**confidence** — from combat outcomes:
- +2 his corps encircled the enemy; else +1 he won an attack (defender retreated)
- −2 he lost his region (defender, position taken); else −1 his attack was repulsed

**fatigue** — from exertion:
- +1 if he fought or moved this turn
- −1 if he rested (no fight, no move — held/reserve)

**relationship** — from your command:
- +1 he won a fight under your command (success you led)
- −1 he was sent into an attack that was repulsed (his men spent for nothing)
- **signalling**: a *seeded, temperament-weighted chance* to +1 if you opened a
  SIGNAL to him this turn (see below). Not guaranteed — words alone rarely move
  the proud.

Deterministic signals (outcomes) always apply; only the social "attention"
signal is a roll — reproducible via a seeded RNG, consistent with the
determinism fix.

### Signalling chance (temperament-weighted)

`chance = clamp(BASE − EGO_WEIGHT * ego, floor, cap)` — high-ego commanders
rarely warm to words (Guderian ego 9 → low odds; you must prove it in results),
steadier ones respond to attention. Seeded `random.Random(state.seed * P +
report.turn)`, commanders evaluated in sorted id order for reproducibility.
"Signalled this turn" = a `role == "player"` line in `state.conversations[cid]`
at `report.turn`. Constants (`BASE`, `EGO_WEIGHT`, `floor`, `cap`) tuned so a
prickly general is ~15% and a collegial one ~45%.

## Peer dismissals

Handled in [commanders/campaign.py](../../../commanders/campaign.py)
`dismiss()`, not the turn updater (a dismissal is an event between turns): the
*remaining* same-side active commanders take relationship −1 (unsettling to see
a peer relieved). Applied immediately when the dismissal happens.

## Prompt feed

New `_current_state_block(dossier)` in
[commanders/prompts.py](../../../commanders/prompts.py), appended to
`build_persona_prompt` as **"YOUR CURRENT STATE:"** — *prose, never numbers*, so
it reaches both order-generation (`build_system_prompt`) and conversation
(`build_persona_prompt`). Only salient (non-mid) values produce a line; if all
are mid, the block is a single neutral line or omitted. Examples:

- confidence ≥8: "You are riding high — recent successes leave you certain."
- confidence ≤2: "Recent reverses have shaken you; you doubt your judgment."
- fatigue ≥7: "Your formations are exhausted, stretched past endurance."
- relationship ≤2: "Your patience with headquarters is worn thin; you
  increasingly act on your own judgment, whatever the directive says." ← the
  emergent-insubordination lever
- relationship ≥8: "You trust the theater commander; his intent and yours run
  together."

## Frontend

The commander card currently renders static traits only. **Add** morale bars
(confidence / fatigue / relationship) reading `cmd.dynamic` (already in the
snapshot), styled like the trait bars but visually distinct, with a CSS
width-transition so they animate as mood shifts turn to turn. Verified live in
the browser preview.

## Testing

- **pure `update_morale`**: win ↑confidence; encirclement ↑↑; repulse ↓;
  lost region ↓↓; fight/move ↑fatigue; rest ↓fatigue; won-under-command
  ↑relationship; repulsed attack ↓relationship; clamping at 0 and 10; net-change
  cap. Signalling: seeded, so a fixed seed gives a deterministic warm/no-warm;
  high-ego commander warms rarely, low-ego often (statistical over seeds).
- **prompt**: `_current_state_block` emits the right prose per band; mid values
  produce the neutral/absent block.
- **dismiss()**: relieving a commander drops the remaining same-side
  commanders' relationship by 1; the other side is untouched.
- **integration**: `play_turn` moves morale and it survives a save/load round
  trip (dynamic already serializes).
- **frontend**: morale bars render and animate — live preview.

## Out of scope (YAGNI)

No SIGNAL sentiment parsing (relationship moves on derivable signals only). No
combat/mechanical effect from morale. No morale-driven communiqué frequency
change (the communiqué selector already weights ego/initiative). These are
clean follow-ups.
