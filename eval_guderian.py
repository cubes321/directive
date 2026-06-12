"""Phase 2 go/no-go evaluation: one LLM commander in a scripted war.

Runs the opening turns of Barbarossa with Guderian driven by LM Studio and
everyone else scripted. Optionally re-runs the same turns with a cautious
dossier swapped in over the same corps, to check that personality actually
changes behavior.

Usage:
  python eval_guderian.py [--turns 10] [--model MODEL] [--swap-personality]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path

from commanders.config import load_config
from commanders.dossier import Dossier, load_dossiers
from commanders.llm import LMStudioClient, LMStudioUnavailable
from commanders.scripted import scripted_orders
from engine.scenario import load_scenario
from engine.turn import resolve_turn

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
GERMAN_SCRIPTED = ["hoth", "kluge", "strauss", "weichs"]
SOVIET = ["pavlov", "timoshenko", "konev", "zhukov"]

CAUTIOUS_STAND_IN = {
    "traits": {"aggression": 2, "caution": 9, "initiative": 2, "logistics": 8, "ego": 3},
    "bio": (
        "A deliberate, supply-minded general of the old school. He believes wars are "
        "won by intact divisions and unbroken railheads, not by dashing spearheads. "
        "He advances only with secured flanks, full fuel depots, and clear superiority, "
        "and he regards any order to hurry as an invitation to disaster that must be "
        "managed prudently."
    ),
}


async def play(turns: int, model: str, dossier: Dossier, label: str) -> dict:
    state = load_scenario(DATA_DIR)
    state.directives[dossier.id] = (
        "Break through and take Smolensk as rapidly as possible. Minsk is your "
        "intermediate objective. Keep your group concentrated."
    )
    log_dir = ROOT / "logs" / f"eval_{label}"
    config = load_config()
    if model:
        config = replace(config, model=model)
    client = LMStudioClient.from_config(config, log_dir=log_dir)
    summary = {"label": label, "turns": [], "postures": {"attack": 0, "advance": 0, "defend": 0, "reserve": 0}}

    for _ in range(turns):
        llm_orders = await client.request_orders(state, dossier)
        for o in llm_orders.orders:
            summary["postures"][o.posture] += 1

        all_orders = {dossier.id: llm_orders}
        for cmd in GERMAN_SCRIPTED:
            all_orders[cmd] = scripted_orders(state, cmd, stance="advance", goal="moscow")
        for cmd in SOVIET:
            all_orders[cmd] = scripted_orders(state, cmd, stance="defend")

        turn_no = state.turn
        report = resolve_turn(state, all_orders)
        own = [state.corps[o.corps_id] for o in llm_orders.orders if o.corps_id in state.corps]
        print(f"\n=== Turn {turn_no} ({state.date.isoformat()}) [{label}] ===")
        print(f"DISPATCH: {llm_orders.dispatch}")
        print(f"reasoning: {llm_orders.reasoning}")
        for o in llm_orders.orders:
            print(f"  {o.corps_id}: {o.posture}" + (f" -> {o.objective}" if o.objective else ""))
        for c in report.combats:
            if set(c["attackers"]) & {x.id for x in own}:
                print(f"  combat at {c['region']}: odds {c['odds']} -> {c['outcome']}")
        summary["turns"].append(
            {
                "turn": turn_no,
                "dispatch": llm_orders.dispatch,
                "orders": [vars(o) for o in llm_orders.orders],
                "positions": {x.id: x.location for x in own},
            }
        )

    summary["final_positions"] = {c.id: c.location for c in state.corps_for(dossier.id)}
    summary["control_smolensk"] = state.control.get("smolensk")
    summary["control_minsk"] = state.control.get("minsk")
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=10)
    parser.add_argument("--model", default=None, help="override config.toml model")
    parser.add_argument("--swap-personality", action="store_true")
    args = parser.parse_args()

    dossiers = load_dossiers(DATA_DIR)
    guderian = dossiers["guderian"]

    try:
        results = [await play(args.turns, args.model, guderian, "guderian")]
        if args.swap_personality:
            cautious = Dossier.from_dict(
                {**guderian.to_dict(), **CAUTIOUS_STAND_IN, "name": "Generaloberst Lothar Bedacht"}
            )
            results.append(await play(args.turns, args.model, cautious, "cautious"))
    except LMStudioUnavailable as e:
        raise SystemExit(f"\nABORT: {e}")

    print("\n\n========== EVALUATION SUMMARY ==========")
    for r in results:
        total = sum(r["postures"].values())
        print(f"\n[{r['label']}] {total} corps-orders over {args.turns} turns")
        print(f"  postures: {r['postures']}")
        print(f"  final positions: {r['final_positions']}")
        print(f"  minsk: {r['control_minsk']}, smolensk: {r['control_smolensk']}")
    out = ROOT / "logs" / "eval_summary.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nFull summary written to {out}")


if __name__ == "__main__":
    asyncio.run(main())
