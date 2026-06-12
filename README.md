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
- Any OpenAI-compatible chat-completions server and a capable instruct model.
  The default setup assumes [LM Studio](https://lmstudio.ai/) with its local
  server running (`lms server start`); Ollama, llama.cpp, vLLM, or a hosted
  provider like OpenRouter work too — see *Configuring the AI backend*.
  Recommended model class: Qwen3.6-35B-A3B or similar MoE (~16 GB VRAM).

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

Each week your chief of staff (Genmaj. von Greiffenberg) opens the inbox with
a dry assessment of what actually happened. Use the ⚡ SIGNAL button on a
commander's card to talk to him directly — recent exchanges are quoted in his
next briefing, so a conversation is a real channel of influence, not flavor.

## Configuring the AI backend

The game talks to any **OpenAI-compatible chat-completions endpoint**. With no
configuration at all it targets LM Studio at `http://localhost:1234/v1` with
`qwen/qwen3.6-35b-a3b`. To change that, copy the committed example and edit:

```powershell
Copy-Item config.example.toml config.toml
```

`config.toml` is **gitignored**, so an API key placed there never reaches
version control. A full example:

```toml
[llm]
base_url = "http://localhost:1234/v1"   # where the server lives (see table below)
api_key = ""                            # empty = no auth header (local servers)
model = "qwen/qwen3.6-35b-a3b"          # default model for every role
temperature = 0.7
timeout_seconds = 120                   # per-commander request timeout

[llm.models]                            # optional per-role overrides
staff = "qwen/qwen3.5-9b"               # chief-of-staff report: cheap and fast
strauss = "qwen/qwen3.5-9b"             # quiet sectors don't need the big brain
weichs = "qwen/qwen3.5-9b"
guderian = "glm-4.7-flash"              # spend the tokens where the drama is
```

### Endpoints

| Server | `base_url` | `api_key` |
| --- | --- | --- |
| LM Studio | `http://localhost:1234/v1` | not needed |
| Ollama | `http://localhost:11434/v1` | not needed |
| llama.cpp server | `http://localhost:8080/v1` | not needed |
| vLLM | `http://localhost:8000/v1` (mind the port clash with the game server) | usually not needed |
| OpenRouter | `https://openrouter.ai/api/v1` | required |

The `model` value must be the name *that server* knows: `lms ps` for LM Studio,
`ollama list` for Ollama, the provider's model id for hosted APIs.

### Per-role models

Keys under `[llm.models]` are commander ids — `guderian`, `hoth`, `kluge`,
`strauss`, `weichs`, `pavlov`, `timoshenko`, `konev`, `zhukov`, any bench
commander you promote (`schmidt`, `reinhardt`, `model`, `yeremenko`,
`rokossovsky`, `vatutin`) — plus `staff` for the weekly chief-of-staff report.
Conversations with a commander use his model too. Roles not listed use the
default `model`.

This is the main lever on turn time: nine commanders plus the staff report run
per turn, and putting the quiet ones on a small model shortens the wait
considerably. If a small model starts fumbling orders for a sector, the
validate→repair→salvage net catches it, but you'll see more *"no new orders
received"* from that commander — run `analyze_logs.py campaign` to check a
model's ok/salvaged/fallback rates before trusting it with a flank.

### Overrides

Environment variables beat the file, useful for one-off runs and scripts:

| Variable | Overrides |
| --- | --- |
| `DIRECTIVE_LLM_BASE_URL` | `base_url` |
| `DIRECTIVE_LLM_API_KEY` | `api_key` |
| `DIRECTIVE_LLM_MODEL` | `model` (the default; per-role entries still apply) |
| `DIRECTIVE_LLM_TEMPERATURE` | `temperature` |
| `DIRECTIVE_LLM_TIMEOUT` | `timeout_seconds` |

The CLI tools (`play_campaign.py`, `eval_guderian.py`) also accept `--model`
to override the default model for a single run — handy for comparing models
in the eval harness. Restart the game server after changing `config.toml`;
it reads the file when it builds the client.

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
