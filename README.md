# DIRECTIVE

A turn-based WW2 strategy game where you don't move units — you command *men*.

You are Field Marshal von Bock, commanding Army Group Center, June 1941. You set
objectives, allocate your standing, and decide who to trust. Your subordinates —
Guderian, Hoth, Kluge, and the rest — are LLM agents with historical
personalities, served by a local model through LM Studio. They interpret your
directives in character: sometimes brilliantly, sometimes liberally, sometimes
not at all. The Soviet commanders facing you work the same way.

Born from frustration with micromanagement wargames: a real theater commander
never moved a battalion. He wrote directives and read dispatches. So do you.

## Requirements

- Python 3.12+
- [LM Studio](https://lmstudio.ai/) with its local server running
  (`lms server start`) and a capable instruct model loaded.
  Recommended class: Qwen3.6-35B-A3B or similar MoE (~16 GB VRAM).

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
```

## Play

```powershell
lms load qwen/qwen3.6-35b-a3b -y
.\.venv\Scripts\python.exe -m uvicorn server.app:app --port 8000
```

Open http://localhost:8000. Write directives on the COMMANDERS tab, press
ISSUE ORDERS, and read what your generals have to say about it. A full turn
(nine commanders thinking) takes a couple of minutes on local hardware.

Using a different model? Set it in `server/app.py` (`DEFAULT_MODEL`) or pass
`--model` to the CLI tools.

## Headless tools

| Script | Purpose |
| --- | --- |
| `play_campaign.py --turns 3` | run the full symmetric LLM campaign in the terminal |
| `eval_guderian.py --turns 10 --swap-personality` | the Phase-2 evaluation: one LLM commander, with a personality-swap control |
| `trace_campaign.py` | fast scripted campaign trace (no LLM) |
| `print_briefing.py guderian` | show exactly what a commander sees |
| `analyze_logs.py campaign` | tally LLM outcomes and failure reasons from `logs/` |

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The engine is fully deterministic (seeded RNG) and the LLM layer is tested
against a mocked transport, so the suite runs in under a second with no model.

## Architecture

```
engine/      pure rules: map graph, corps, WEGO turns, combat, supply, fog,
             weather, victory — zero LLM or network imports
commanders/  the human layer: dossiers, briefings, prompts, LM Studio client
             (validate -> repair -> salvage -> fallback), campaign session
data/        Army Group Center map (named-location graph), 1941 OOB, dossiers
server/      FastAPI: snapshot API + the lamplit situation-map UI in web/
```

Design spec: `docs/superpowers/specs/2026-06-11-directive-design.md`.
