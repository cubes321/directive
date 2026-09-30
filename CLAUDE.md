# Directive — working notes for Claude

Turn-based WW2 strategy game: the player issues directives; LLM commanders
interpret them. Design spec: `docs/superpowers/specs/2026-06-11-directive-design.md`.
User-facing overview: `README.md`.

## Commands

Use the venv interpreter explicitly (Windows):

```powershell
.\.venv\Scripts\python.exe -m pytest            # full suite, ~1.5s, no model needed
.\.venv\Scripts\python.exe -m ruff check .      # lint (must be green)
.\.venv\Scripts\python.exe -m uvicorn server.app:app --port 8000   # play at localhost:8000
```

Tests are TDD-first and run against a mocked transport — the engine is
deterministic (seeded RNG), so the suite needs no live LLM. Add a failing test
before implementing; keep `ruff check` green.

Offline analysis of a finished run (free, no LLM calls — all default to the
newest `logs/run-*`):

```powershell
.\.venv\Scripts\python.exe analyze_logs.py          # ok / repaired / salvaged / fallback
.\.venv\Scripts\python.exe analyze_divergence.py    # is the model still playing a character?
.\.venv\Scripts\python.exe replay_campaign.py       # what would a rules change have done?
```

Each takes a `run-*` name or a path. A replay is faithful only up to the week
the rules first diverge: a change that moves corps makes later recorded orders
stop fitting (the salvage count). Change one rule at a time, keep everything
else as it was, and judge that first week. To test a *prompt* change for free,
resend recorded requests from `logs/run-*/campaign/turn*.json` to LM Studio
with only that text swapped.

**`server/saves/campaign.json` is a live game.** `play_campaign.py` saves over it
after every turn, so a headless playtest silently eats it — build the `Campaign`
yourself and save to a scratch path instead. Hash the save before and after and
say so when reporting.

## The one hard boundary

`engine/` is **pure**: rules, map, combat, supply, WEGO turns. Zero LLM or
network imports, no file IO. The LLM/human layer lives in `commanders/`; the
web/API in `server/` + `web/`. When something in the engine needs to reach the
outside (e.g. telemetry), the engine *builds the data* and a caller *writes it*
— see `engine/telemetry.py` (builds) vs `Campaign._write_turn_log` (writes IO).

## Principles this codebase follows

- **Determinism.** Seed every RNG. **Never iterate a `set` where output depends
  on order** — sort first. (A set-iteration bug made railheads vary across
  `PYTHONHASHSEED`; there's a cross-hash-seed regression test in `test_supply.py`.)
- **Report what actually happened, not what was requested.** Combat reports the
  losses *applied*, not the losses computed (`engine/turn.py:_distribute_losses`);
  a region changes hands only when no living defender is still standing on it,
  not because a retreat was *ordered*.
- **One label, five readers — never conflate two situations in an outcome.**
  `combat["outcome"]` is read by the battle report, the staff summary, the
  communiqué trigger, the track record *and* morale. When "the pocket is holding"
  shared the `defender_held` label with "you were repulsed", a 62:1 pocket
  reduction was shown to the player in red as a failed assault, written into the
  attacker's record as `assault repulsed`, and cost him confidence and patience
  for winning — while the trapped defender *gained* both for dying. Add a value
  (`pocket_holding`), then grep every consumer.
- **Every multiplicative factor gets a floor.** `combat_power` multiplies supply,
  organization and experience together, so any one of them reaching zero zeroes
  the unit — the defence then falls through to `max(defense, 1.0)` and "odds"
  becomes the attacker's raw power (598:1 was logged). `SUPPLY_FLOOR`/`ORG_FLOOR`
  exist for that; give any new factor the same treatment.
- **No staff option should be a dead end.** `_staff_options` once proposed moves
  only into *enemy-held* ground, so a corps in a quiet rear area was told
  "hold current position" and nothing else — and cautious commanders sat there
  for turns. Rejections must name the legal alternatives too
  (`engine/orders.py`), or the repair round-trip degrades an advance into a halt.
- **Single source of truth for derived formulas.** `combat_power` and
  `power_breakdown` share private helpers so telemetry can't drift from combat.
- **Surface config errors loudly; degrade only transient ones.** A backend 4xx
  (wrong model, bad param, bad key) raises `LMStudioUnavailable`; a timeout /
  5xx / 429 / 408 degrades to hold-orders. Don't launder config errors into
  empty responses (`commanders/llm.py:_chat`).
- **Generic passthrough over hardcoded provider quirks.** Backend-specific knobs
  go through `[llm.params]` in config, merged into every request — no vendor
  special-casing in code.
- **Briefings advise, the engine enforces.** Advisory hints to commanders (e.g.
  "region FULL") are *prose in the briefing*, never validation errors — because
  WEGO simultaneity can invalidate a start-of-turn fact. Don't harden advice
  into rules.
- **The order schema's enums come from the validator, never from the briefing.**
  `dynamic_order_schema` (`commanders/prompts.py`) rebuilds a per-corps `oneOf`
  every turn; its objective enum is `engine.orders.reach_options` — the same call
  `_order_errors` makes — plus the corps' own location, which the validator also
  accepts. `briefing._staff_options` looks like that list and is not: capped at
  `MAX_OPTIONS_PER_CORPS` and sorted for display, it would *forbid* orders the
  validator accepts, and any schema/validator disagreement is a guaranteed repair
  loop. `tests/test_dynamic_schema.py` pins both directions — representable ⇒
  validates clean, and accepted ⇒ representable — because each direction is blind
  to the mutations the other catches; check both still bite before trusting a
  change here. Measured on `qwen/qwen3.5-9b`, 12 turns per arm: 0/108 repairs
  against 6/100 under the static schema (misspelled region ids, out-of-reach
  objectives, a movement posture with a null objective).
- **The schema narrows, the validator decides.** Enforcement is a *backend*
  property: llama.cpp is airtight, but production logs show LM Studio returning
  fences and renamed keys despite `strict: true`. Never drop a validation rule
  because the schema "already covers it", and leave the repair/salvage/fallback
  ladder alone. A backend that rejects the per-turn schema degrades to the static
  `ORDER_SCHEMA` and records `schema: static-fallback` in the transcript — which
  is why `ORDER_SCHEMA` still exists.
- **Morale is psychological-only.** `dossier.dynamic` feeds the persona *prompt*;
  it never touches combat maths. Keep that boundary.
- **Derive a mood dial from state, don't integrate activity into it.** `fatigue`
  used to add 1 for moving-or-fighting and subtract 1 for resting — but in an
  offensive nobody rests, so it ratcheted to the ceiling in lockstep (six of nine
  commanders sat at exactly 6) and discriminated nobody. It now seeks a target
  derived from what the corps *are* (`_fatigue_target`: mean of
  `min(organization, supply)`), which moves both ways and cannot saturate.
- **Fog discipline in the UI.** Only ever surface the player's own side; the
  snapshot is already fog-filtered, and views (e.g. the movements tab) must
  filter to own corps.
- **An unfilled slot in a prompt is not neutral — it gets the statistically
  dominant filler.** The order prompt asked for "your report to the theater
  commander" and named nobody, so the model invented a salutation each turn:
  the Red Army side converged on "Comrade <rank>" (over-determined for 1941)
  while the German side, having no anchor at all, scattered over nine forms and
  twice landed on "Comrade Field Marshal". Both sides also reported past the
  player to the head of state. `prompts.py:_addressee_block` names the recipient;
  when you add a field to a prompt, say who or what fills it.
- **Naming a thing to forbid it primes it.** "Speak of Berlin and the Fuehrer as
  you like, but you are not writing to them" put Berlin/Führer into 23/120 German
  dispatch openings ("von Bock, Berlin salutes"). The same permission without the
  names ("Invoke higher authority as you like…") scored 5/60. Say what you want,
  not the word you don't.
- **Never replay a model's own past output as chat turns.** Old pop-ups sent back
  as assistant messages, undated and unbounded in age, were a template: Guderian
  sent one message word for word four weeks running, and SIGNAL replies copied
  his old "To the Theater Commander:" openings. History reaches the model as
  dated prose in the briefing (`week 4, C-in-C: …`). Only this week's live
  exchange is replayed as turns (`Campaign.converse`).
- **When wording won't move a verdict, change the shape of the decision.** The
  staff recommended halting 29/30 times whatever the week, through better facts
  and three rewordings. `STAFF_SCHEMA` makes it write the case for pressing on,
  then for halting, and only then decode the verdict (property order is the
  mechanism, as in `_corps_branches`). Now the verdict tracks the week. Score
  such changes by *discrimination* (does the answer differ where the facts
  differ?), not by the raw rate: schema alone just traded "halt" for
  "consolidate" everywhere.
- **Never let a metric's good news absorb its bad news.** `off-menu` in
  `commanders/divergence.py` was meant to mean "the commander chose an objective
  his staff never raised" — the strongest evidence of independence. It silently
  also counted `advance` where the staff said `attack` (the engine treats those
  as one order, `turn.py:138`), `defend` where the staff offered `reserve` (the
  same inaction), and objectives the engine rejects outright. 44-77% of the
  bucket was model *failure* scored as brilliance, and one commander published
  at 62% off-menu was really 100% hold. When a bucket is the answer you're
  hoping for, enumerate what else can land in it.
- **Measure what the model chose, not what the engine salvaged.** Scoring the
  validated order set counts a repair as the model going passive — the exact
  false positive an instrument like this exists to avoid. Score
  `attempts[0]`, fall back only when there is no raw attempt.
- **When the engine overrides a commander, tell him, and let him react.** The
  garrison hold-back (`turn.py:_hold_back_garrisons`) cancels one corps' move.
  The countermand goes into his war record and makes a pop-up likelier
  (`records.garrison_holds`), but nothing tells him how to feel. Hoth protested
  unprompted, in character, the week it first fired. Keep engine overrides
  minimal (one corps, not the whole order), and never script the reaction.
- **Protect emergent personality.** LLM commanders arguing, lunging, or bending
  orders is the product's core value — don't tune it away when adjusting prompts.
  Note that *voice* and *decisions* fail separately: on `kimi-k2.6` commanders
  quote an intercept and reason about it beautifully while still taking the
  staff's option #1. Before crediting a model with acting on new information,
  check whether `_staff_options` already suggested that move.

## Conventions

- Line endings normalized via `.gitattributes` (LF in repo). config.toml holds
  the API key and is gitignored; `config.example.toml` is the committed template.
- Logs are gitignored and **scoped per run**: each server session writes to
  `logs/run-<timestamp>/` (`campaign/` transcripts + `tokens.jsonl`, `turns/`
  telemetry). The newest `run-*` dir is the current run; `commanders/runlog.py`
  resolves it, and the analysis scripts default to it.
