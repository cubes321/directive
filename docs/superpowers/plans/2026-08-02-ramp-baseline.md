# The difficulty ramp: measured baseline and tuning

Task 5 of the "the army group wears out" plan. The constants added in Tasks 1-2
were first guesses. This is the measurement that judged them, and the one change
that came out of it.

Method: a scripted 24-turn trace (`scripted_orders`, all five German commanders
on `advance`/`moscow`, all four Soviet commanders on `defend`), run against the
seeded engine so it is reproducible. The script lives outside the repo and is
deliberately not committed.

**Caveat that colours every number below.** The scripted AI is a weak proxy for
real play. It is *passive* on the Soviet side — it never counterattacks, so the
Moscow hold clock is never actually contested — and it is *unimaginative* on the
German side: it funnels every assault down the single cheapest path and never
rotates a spent corps out of the line. Moscow has six neighbours
(`klin`, `mozhaisk`, `naro_fominsk`, `serpukhov`, `tula`, `volokolamsk`); the
scripted advance only ever attacks from `mozhaisk`, capping the assault at three
corps by stacking while eleven axis corps queue behind. The axis numbers here
are therefore a **floor**, not a ceiling. Do not tune to them.

## Before: the ramp as Tasks 1-4 left it

| turn | wx | axis str | sov str | ratio | avg axis supply | wastage | ceilings min/med | front |
|---|---|---|---|---|---|---|---|---|
| T5 | clear | 1352 | 1161 | 1.16 | 71 | 6 | 98/99 | smolensk |
| T8 | clear | 1333 | 1185 | 1.12 | 77 | 7 | 96/99 | +vyazma |
| T12 | clear | 1341 | 1223 | 1.10 | 84 | 0 | 96/99 | |
| T15 | clear | 1328 | 1268 | 1.05 | 95 | 3 | 94/99 | +mozhaisk |
| T19 | mud | 1298 | 1335 | 0.97 | 100 | 0 | 91/99 | **+moscow** |
| T24 | snow | 1298 | 1435 | 0.90 | 100 | 0 | 91/99 | |

- Moscow first fell **turn 19** — unchanged from the pre-ramp baseline.
- Axis took **132** strength of damage, regenerated 30. Of the 132,
  **51 was marching wastage** and 81 combat/pocket. (Pre-ramp: 71 damage, 29
  regenerated.) So the ramp roughly doubled the cost of the advance.
- Moscow was then held **six consecutive turns** unopposed → decisive axis
  victory. From T20 the campaign is frozen: identical strengths every turn, no
  movement, no combat, because the scripted Soviets never come back.

### What the "before" run exposed

Two findings, and only one of them is about constants.

**1. The wastage self-extinguishes.** Axis average supply climbs back to 100 by
T16 and stays there, so wastage is exactly zero for the last nine turns. That is
the mechanic working as designed — `RAILHEAD_SPEED = 1` catches up with a slow
advance, and staying inside your railhead is meant to be free — but it means all
51 points of wastage are charged in the first fifteen turns, and none at the
gates of Moscow. Wastage punishes *speed*, not distance-on-the-calendar. A player
who lunges will pay far more than this trace shows; a player who creeps pays
almost nothing after the midpoint.

**2. `sov_sib1` never arrived.** The Siberian Group Lukin (100 strength, 95 org,
the single largest counterweight in the schedule) was scheduled into `moscow` on
turn 16. `_arrive_reinforcements` correctly refuses to spawn into a region at the
stacking limit and retries next turn — but Moscow held three corps from T15
onward (the Mozhaisk garrison having retreated into it), and was axis-held from
T19. The unit stayed pending for the entire campaign and was silently deleted
from the game. Confirmed directly: at end of run,
`still pending: [(16, 'sov_sib1', 'moscow')]`, `sib1 in roster: False`.

This is not a constants problem. It is the reinforcement schedule being
neutralised by an interaction with the stacking rule, and it removed 100 strength
from the defence of Moscow in exactly the turns the ramp was supposed to bite.

## The change

**One change, in `data/oob_1941.json`:** the three Siberian arrivals moved from
turns 16/18/20 to **13/15/17**.

This is the re-timing the plan's decision rule prescribes when Moscow still falls
around turn 19. It also happens to be the fix for finding (2): at turn 13 Moscow
holds only `sov_49a`, so Lukin has room and actually arrives, and is in the line
before the Mozhaisk garrison falls back into the city.

No engine constant was changed. `WASTAGE_SUPPLY_STEP` stays 25,
`WASTAGE_WEATHER` stays `{clear 1.0, mud 2.0, snow 2.5}`,
`CADRE_LOSS_FRACTION` stays 0.25, `MIN_CADRE` stays 40, `MOSCOW_HOLD_TURNS`
stays 3. The reasoning for each is in "Risks checked" below.

## After

| turn | wx | axis str | sov str | ratio | avg axis supply | wastage | ceilings min/med | front |
|---|---|---|---|---|---|---|---|---|
| T5 | clear | 1352 | 1161 | 1.16 | 71 | 6 | 98/99 | smolensk |
| T8 | clear | 1333 | 1185 | 1.12 | 77 | 7 | 96/99 | +vyazma |
| T13 | clear | 1340 | 1289 | 1.04 | 95 | 0 | 95/99 | |
| T15 | clear | 1328 | 1468 | 0.90 | 95 | 3 | 94/99 | +mozhaisk |
| T19 | mud | 1285 | 1544 | 0.83 | 100 | 0 | 90/99 | (moscow soviet) |
| T24 | snow | 1211 | 1521 | 0.80 | 100 | 0 | 84/99 | (moscow soviet) |

- **Moscow never falls.** The axis takes Smolensk T5, Vyazma T8, Mozhaisk T15,
  and then grinds at the gates for nine turns without entering the city.
- Axis took **219** damage, regenerated 30. Wastage is unchanged at 51 (the
  advance is identical up to Mozhaisk); the extra 87 is all combat at the gates.
- Final force ratio **0.80** (was 0.90).
- Outcome: **marginal axis victory on objective points** (25 VP vs the 18
  threshold) — "a deep but indecisive advance."

The odds curve at Moscow is the interesting artefact. Full series, one value per
turn from T16 to T24:

```
T16 0.68   T17 0.91   T18 0.86   T19 0.79   T20 0.74   T21 0.70   T22 0.56   T23 0.42   T24 0.26
```

The same three panzer corps assault the same three defenders for nine turns.
The curve is not a monotonic decay: it rises from 0.68 to a peak of 0.91 at T17
before decaying to 0.26 by T24 — 46/51/56 strength by T24, against ceilings of
84/85/87. The early rise is not the ramp failing; the sustained decay after the
peak is the ramp doing what it was written to do: an army that keeps attacking
without pause gets progressively worse at it, just not from the very first
assault.

## Risks checked (Step 3)

**Double punishment — is an outrun spearhead punished or deleted?** Punished.
A corps at supply 20 marching in clear weather loses 3 strength and 6
organisation per turn. Over six turns of marching: 100 → 82 strength, 80 → 44
organisation. The organisation hit is the sharper one (it halves combat power),
which is the right shape — an outrun corps should stop being *useful* well
before it stops existing. Halt it, restore supply and rest it in reserve, and it
climbs back to its ceiling of 96 in eight turns. Pull back and recover, at a
cost: confirmed.

The wastage table in full (strength lost per marching turn):

| supply | 100 | 75 | 50 | 30 | 20 | 10 | 0 |
|---|---|---|---|---|---|---|---|
| clear | 0 | 1 | 2 | 3 | 3 | 4 | 4 |
| mud | 0 | 2 | 4 | 6 | 6 | 7 | 8 |
| snow | 0 | 2 | 5 | 7 | 8 | 9 | 10 |

The genuine outer edge is supply 0 in snow: 10 strength and 20 organisation per
turn, which destroys a full-strength corps in twelve consecutive marching turns.
That is reachable only by ordering a completely unsupplied corps to march every
single turn through a Russian winter while the briefing says not to. It is a
decision, not a trap, and left as is.

**`CADRE_LOSS_FRACTION` too harsh — can the axis still reach Moscow?** Yes, and
comfortably. End-of-campaign ceilings are `[84, 85, 87, 96, 97, 99, 99, 99, 100,
100, 100, 100, 100, 100]`. Nothing is near the `MIN_CADRE` floor of 40; the
median corps has barely been touched. All 14 axis corps are alive and mobile at
T24. 0.25 stays.

Worth naming honestly: in this trace the **wastage is doing the work and the
cadre ceiling is not**. Ceilings sit 30-40 points above actual strengths, so the
ceiling never binds — it caps a rebuild that no corps has time to attempt. It is
currently more a narrative fact the commander is told about than a live
constraint. That is acceptable: it is a *ceiling*, and it exists to make late
recovery incomplete, which only shows up in a campaign where the player rotates
formations out to refit. It should not be strengthened on the strength of a run
where nobody rests.

## Verdict

**The near-miss target is met, with one caveat that only a live playtest can
close.**

- The axis is not destroyed and is not stalled short of Smolensk (Smolensk T5,
  Vyazma T8) — no over-correction.
- The axis reaches the gates of Moscow at T15 and is stopped there, which is
  precisely the shape the spec asked for: "reaches the gates and is stopped."
- The campaign resolves as a marginal axis win on points, not a decisive one.
  Taking Moscow is no longer routine.
- No pathology: no corps pinned at `MIN_CADRE`, no immobilised army, no corps
  destroyed by wastage, force ratio degrades smoothly rather than collapsing.

Against a competent player Moscow should still be takeable, and that is
deliberate. The scripted trace fails to take it with three corps down one
corridor; a real player has six approach regions and eleven idle corps to bring
up, and can rest a spent panzer corps in reserve rather than throwing it at 0.26
odds. The intended experience — take the city, then try to hold it for three
turns against the Siberians — is still on the table.

**The caveat:** `MOSCOW_HOLD_TURNS = 3` is never *contested* by this method — not
untested outright. The clock is real and does run: in the "before" run the axis
took Moscow at T19 and held it for six consecutive turns; `moscow_held_turns`
reached the threshold two turns later and `check_victory` fired the
decisive-axis branch at turn 21, exactly as `MOSCOW_HOLD_TURNS = 3` specifies.
The campaign then froze because the scripted Soviets never come back to
retake the city. In the "after" run Moscow never falls, so the clock never
starts — but that is the axis being stopped at the gates, not the clock failing
to run. What this method cannot show is whether 3 is the *right* number,
because the scripted Soviets never counterattack once the axis is inside the
city: nothing ever tests whether a defender could retake Moscow before the
clock expires. That judgment needs commanders that actually launch the
counterattack. That is Step 5 (the live LLM playtest), which has not been run.

**Single-seed caveat.** Every number above comes from one seed
(`DEFAULT_SEED = 1941`). A 10-seed sweep with the re-timed schedule found the
direction robust but not universal: 9 of 10 seeds now never lose Moscow (versus
6 of 10 decisive-axis outcomes before the change), but at seed 7 the new
schedule still loses Moscow at turn 21 and holds it for the full 4 turns,
resolving as a decisive axis win. The re-timing improves the odds; it does not
guarantee the outcome. Do not read the single-seed trace above as "fixed."
