# "Directive" — LLM-Commander WW2 Strategy Game: Design

## Vision

A turn-based WW2 strategy game that is the philosophical opposite of Gary Grigsby's
War in the East 2: instead of micromanaging every unit, the player acts as a theater
commander who issues directives and manages *people*. Subordinate commanders are LLM
agents (served by LM Studio's local OpenAI-compatible API) with historical
personalities and evolving track records, who interpret directives in character —
including imperfectly or insubordinately. The realism comes from delegation, not
detail.

## Core decisions

- **Player role**: theater commander — directives, supply priority, reserves,
  hire/fire. Never moves a unit directly.
- **First scenario**: Barbarossa, Army Group Center, June–December 1941, weekly
  turns (~24). Player is von Bock.
- **Enemy side**: symmetric LLM commanders under a scripted strategic intent.
- **Commanders**: real historical figures. German: Guderian, Hoth, Kluge, Strauss,
  Weichs. Soviet: Pavlov, Timoshenko, Konev, Zhukov.
- **Command architecture** ("B + staff net"): commanders return structured JSON
  orders with full agency; engine-computed staff recommendations are included in
  the briefing as suggestions; validation with one repair retry, then fallback to
  "continue previous orders".
- **Map**: named-location graph (~60–80 regions; edges carry terrain and road/rail
  quality), NOT hexes. LLMs reason well about named places and terribly about
  coordinates.
- **Turn resolution**: WEGO (simultaneous), deterministic engine with seeded RNG.
- **Tech**: Python 3.12 + FastAPI backend; SPA frontend (SVG map + dispatch inbox);
  JSON save files.
- **LLM target**: LM Studio at `http://localhost:1234/v1`, MoE models in the
  Qwen3-30B-A3B class (user hardware: 16GB VRAM / 128GB RAM).

## Architecture

```
engine/        Pure Python, zero LLM/IO dependencies, fully unit-testable
  map.py       Region graph: Region, Edge (terrain, road/rail quality)
  units.py     Corps: strength, organization, fuel/ammo, experience
  orders.py    Order schema (dataclasses) + validation/repair logic
  movement.py  Graph movement, movement-point costs
  combat.py    Strength x terrain x supply x posture, seeded RNG
  supply.py    Railhead conversion + truck range, simplified
  fog.py       Per-side intel model
  turn.py      WEGO resolution: movement -> combat -> supply -> weather
  state.py     GameState: serializable single source of truth
commanders/
  dossier.py   Personality traits, bio, dynamic state, track-record log
  briefing.py  GameState + fog -> per-commander text situation briefing
               including staff-recommended options (engine-computed)
  llm.py       LM Studio client: async parallel calls, json_schema structured
               output, timeout, retry/repair, fallback
  prompts.py   System prompt templates (personality card + doctrine)
data/
  map_agc.json       Army Group Center region graph
  oob_1941.json      Order of battle, both sides, corps level
  commanders.json    Historical dossiers, both sides
server/
  app.py       FastAPI: game endpoints + static frontend
web/           SPA: SVG map, dispatch inbox, directive composer, dossiers
tests/
```

**Key boundary**: `engine/` never imports `commanders/` or anything async/network.
The LLM layer consumes `GameState` and produces validated `Orders`; the engine does
not know orders came from an LLM. The whole game is playable headlessly with
scripted orders for testing.

## Turn loop

1. Player reads dispatches, edits directives (free text + structured: objectives,
   supply priority, reserve release, assignments), ends turn.
2. `briefing.py` builds each commander a private briefing (own forces, supply,
   fog-limited intel, theater directive, 2–3 staff options).
3. `llm.py` fires parallel async calls for ALL commanders, both sides. Response
   schema: per-corps orders (objective region, axis, posture) + in-character
   dispatch text + brief reasoning.
4. Validation: schema + legality (own corps only, reachable objectives). One repair
   round-trip on failure; second failure → continue previous orders (logged,
   surfaced to player as "no new orders received from ...").
5. WEGO resolution in `turn.py`; track records and dynamic state updated; next
   dispatches assembled.

## The commander model

Each commander is a **dossier**: fixed personality traits (aggression, caution,
initiative/insubordination, logistics-mindedness, ego), a historical bio for the
prompt, and dynamic state (confidence, fatigue, relationship with the player). The
track record is an append-only log of summarized outcomes that feeds back into his
prompt — commanders remember and are shaped by their war.

**Insubordination is a feature.** A high-initiative commander given a cautious
directive may exceed it; the dispatch will tell you — after the fact, sometimes.
Sacking Guderian costs political capital and morale; tolerating him costs control.
That tension is the game.

## Implementation phases

1. **Engine core** (no LLM, no UI). Exit: scripted 24-turn headless game runs with
   a sane historical-ish outcome.
2. **One LLM commander — go/no-go milestone.** Wire Guderian alone into a scripted
   game. Exit: over ~10 turns, orders legal and tactically sane, dispatches in
   character, personality measurably affects choices. If a Qwen3-30B-class model
   cannot pass, fall back toward menu-picking architecture before building more.
3. **Full symmetric loop.** All commanders both sides, Soviet strategic intent
   script, track records, political capital + dismissal.
4. **Web UI.** SVG map, dispatch inbox (primary surface), directive composer,
   dossier screens, end-turn progress.
5. **Tuning.** Weather/mud/winter, victory conditions (Moscow before December,
   casualty thresholds), balance, save/load polish.

## Error handling

- LM Studio unreachable → turn cannot be ended; clear actionable message.
- Per-commander timeout (~120s configurable) → fallback orders, surfaced in UI.
- Invalid JSON/illegal orders → one repair attempt quoting validation errors, then
  fallback.
- All LLM requests/responses logged to disk for prompt debugging.

## Verification

- `pytest` for the engine (deterministic, seeded) and for validation/repair against
  a corpus of deliberately malformed LLM outputs.
- Phase 2 go/no-go evaluated against live LM Studio with transcript review.
- Headless full-game smoke test with scripted orders.
- End-to-end: play 2–3 turns in the browser with LM Studio running.
