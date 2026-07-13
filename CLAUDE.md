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
  losses *applied*, not the losses computed (`engine/turn.py:_distribute_losses`).
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
- **Morale is psychological-only.** `dossier.dynamic` feeds the persona *prompt*;
  it never touches combat maths. Keep that boundary.
- **Fog discipline in the UI.** Only ever surface the player's own side; the
  snapshot is already fog-filtered, and views (e.g. the movements tab) must
  filter to own corps.
- **Protect emergent personality.** LLM commanders arguing, lunging, or bending
  orders is the product's core value — don't tune it away when adjusting prompts.

## Conventions

- Line endings normalized via `.gitattributes` (LF in repo). config.toml holds
  the API key and is gitignored; `config.example.toml` is the committed template.
- Logs are gitignored and **scoped per run**: each server session writes to
  `logs/run-<timestamp>/` (`campaign/` transcripts + `tokens.jsonl`, `turns/`
  telemetry). The newest `run-*` dir is the current run; `commanders/runlog.py`
  resolves it, and the analysis scripts default to it.
