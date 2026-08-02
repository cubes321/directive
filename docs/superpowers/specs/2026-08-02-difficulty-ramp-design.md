# Difficulty ramp: the army group wears out

**Status:** approved, not yet implemented
**Date:** 2026-08-02

## The problem

The campaign should get harder the closer it gets to Moscow. It does not.

The starting instinct was "add the Siberian divisions". They are already there —
`data/oob_1941.json` schedules six Soviet reinforcements and no German ones:

| turn | formation | arrives at |
| --- | --- | --- |
| 8 | 30th Army | Vyazma |
| 11 | 31st Army | Kaluga |
| 14 | 1st Shock Army | Klin |
| 16 | Siberian Group Lukin | Moscow |
| 18 | Siberian Group Belov | Tula |
| 20 | Siberian Group Kuznetsov | Kalinin |

Weather ramps too: mud from turn 16, snow from turn 22 (`engine/weather.py`).

A scripted 24-turn trace confirms the ramp is real — German superiority peaks
around turn 7 and is gone by turn 19:

```
turn   weather  axis   soviet  ratio   axis_n  sov_n
 T7    clear    1391    1135   1.23      14      16
 T14   clear    1388    1299   1.07      14      18
 T19   mud      1358    1347   1.01      14      19   <- Moscow falls
 T24   snow     1358    1447   0.94      14      20
```

Two things are wrong, and neither is the absence of Siberians.

**The ramp crests after the game is decided.** Moscow falls on turn 19; the last
Siberian group lands on turn 20 and the snow on turn 22.

**Nothing wears the Germans out.** Over 24 turns the axis took 71 strength of
damage across 14 corps — five points per corps for an entire campaign — and
regenerated 29 of it free. Combat is the only source of damage in the game, so a
corps that marches 600 km to Moscow arrives at full strength. Historically the
opposite: panzer divisions were at 30–50% runners by Smolensk largely through
breakdowns, horses and sickness rather than battle.

## Decisions

1. **A well-played campaign is a near-miss.** A good player reaches the gates and
   is stopped, or takes Moscow and cannot hold it. Taking *and keeping* it is
   exceptional.
2. **The pressure comes from the German army wearing out**, not from the enemy
   piling on. This makes the player's own decisions the cause of their
   difficulty, and it is thematically the centre of the game — logistics
   currently costs combat power only while a corps is out of supply, never
   permanently.
3. **Marching wastage is the engine of the ramp**, with a light cadre-decay so
   what it takes does not come straight back.

### Rejected

- **A replacement pool** the player allocates. Historically apt, but it is a
  resource-management minigame and the design thesis is that the player writes
  intent rather than pushing counters. It would be the first screen that asks
  the player to allocate something.
- **Wastage for static corps.** A corps standing still already pays, in the
  ground it is not taking. This also keeps the existing rule that containing a
  pocket without assaulting it costs the pocket nothing
  (`test_contained_pocket_is_not_destroyed_by_containment_alone`).

## Design

### 1. Marching wastage — `engine/turn.py`

A new resolution step, after recovery. Corps that **moved** this turn lose
strength and organisation, scaled by supply shortfall and weather:

```python
WASTAGE_SUPPLY_STEP = 25
WASTAGE_WEATHER = {"clear": 1.0, "mud": 2.0, "snow": 2.5}

loss = round((100 - corps.supply) / WASTAGE_SUPPLY_STEP * WASTAGE_WEATHER[weather])
```

Organisation takes double the strength loss, mirroring the ratio combat uses.

| situation | supply | weather | strength/turn |
| --- | --- | --- | --- |
| marching inside the railhead | 100 | clear | 0 |
| one leg past it | 75 | clear | 1 |
| outrun spearhead | 20 | clear | 3 |
| outrun spearhead in October | 20 | mud | 6 |
| cut off in the snow | 0 | snow | 10 |

The load-bearing property: **staying within supply costs nothing.** Wear begins
the moment a corps outruns its railhead and compounds with distance, so the ramp
arrives as a function of how far east you are rather than of the calendar. It
also creates a weekly decision — push on and bleed, or halt and give the
Siberians time.

Applies to movement only. A corps that fought but did not move is already paying
in combat losses.

### 2. Cadre decay — `engine/units.py`

`Corps` gains **one** field, `damage_taken: int = 0`, and a derived ceiling:

```python
CADRE_LOSS_FRACTION = 0.25
MIN_CADRE = 40

@property
def max_strength(self) -> int:
    return max(MIN_CADRE, 100 - round(self.damage_taken * CADRE_LOSS_FRACTION))
```

`take_losses` adds the strength actually removed to `damage_taken`; `recover()`
clamps to `max_strength` instead of 100.

The ceiling must be **derived from cumulative damage, not decremented per loss
event**. `_distribute_losses` applies combat damage one point at a time, so a
per-call `round(1 * 0.25)` would round to zero every time and decay nothing. A
running total is immune to how the damage arrives.

Wastage feeds this too — it is strength loss like any other — so a long march
past the railhead permanently lowers what a corps can ever be rebuilt to. That is
the whole point of pairing the two.

A corps ground from 100 to 60 can rebuild, but only to 90, and the next mauling
costs it more. Old saves round-trip unchanged: `Corps.from_dict` is
`cls(**data)`, so a defaulted field simply appears.

### 3. Moscow must be held — `engine/victory.py`

Delete the instant-win branch. `GameState` gains `moscow_held_turns`, incremented
while Moscow is axis-controlled and reset to zero the moment it is not. Decisive
axis victory requires `MOSCOW_HOLD_TURNS = 3` consecutive turns; otherwise the
campaign runs to turn 24 and is scored on objective points as it already is.

This turns the Siberian arrivals from scenery into the climax: take Moscow around
turn 20, then survive three weeks of counterattack in the snow with a spent army
group.

### 4. Visibility

Wear the player cannot see is the game cheating.

- FORCES tab shows `strength / max_strength` rather than `/100`.
- The briefing reports each corps' ceiling, so a commander whose divisions can
  never be whole again can say so.

## Testing

Unit tests per rule:

- no wastage for a corps at full supply; none for a corps that did not move
- wastage scales with supply shortfall and with weather
- `max_strength` declines with cumulative damage and clamps `recover()`
- a corps cannot be rebuilt past its ceiling
- damage arriving one point at a time (as `_distribute_losses` delivers it)
  lowers the ceiling by the same amount as one bulk loss of the same size
- wastage lowers the ceiling as combat damage does
- Moscow held one and two turns is not a victory; three is
- losing Moscow resets the counter
- regression: a contained pocket still loses nothing

Then the honest check: re-run the scripted 24-turn trace and compare against
today's baseline (Moscow falls turn 19, axis 1397 → 1358, 71 damage taken).

## Tuning

**The constants above are first guesses and are expected to be wrong.** The
trace is the instrument. Specifically:

- If wastage alone pushes Moscow past turn 22, the reinforcement and weather
  schedule needs no re-timing. If it does not, move the Siberian arrivals and
  the mud earlier.
- Watch for double-punishment: a corps at supply 20 already fights at a 0.2
  power factor and will now bleed as well. That is intended, but the combined
  effect may be too steep.
- `CADRE_LOSS_FRACTION` at 0.25 may make a long campaign unwinnable regardless
  of play. Check the axis can still reach Moscow at all.
