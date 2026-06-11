"""Run the full symmetric campaign: every commander on both sides is an LLM.

Usage:
  python play_campaign.py [--turns 3] [--model qwen/qwen3.6-35b-a3b] [--resume]
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from commanders.campaign import Campaign
from commanders.llm import LMStudioClient

ROOT = Path(__file__).parent
SAVE = ROOT / "server" / "saves" / "campaign.json"

BOCK_DIRECTIVES = {
    "guderian": (
        "2nd Panzer Group breaks through on the Minsk axis and drives for the "
        "Dnieper crossings. Bypass resistance where possible; the infantry will "
        "reduce the pockets behind you."
    ),
    "hoth": (
        "3rd Panzer Group attacks through Vilnius toward Vitebsk to form the "
        "northern pincer. Link up with Guderian east of Minsk to close the pocket."
    ),
    "kluge": (
        "4th Army follows the panzer groups, reduces bypassed enemy formations "
        "and keeps the Minsk highway open. Secure the supply corridor."
    ),
    "strauss": (
        "9th Army advances via Grodno and Lida, clears the northern flank and "
        "supports Hoth's pincer."
    ),
    "weichs": (
        "2nd Army remains in army group reserve, following by rail. Mop up the "
        "Bialystok area and guard the southern flank along the Pripyat."
    ),
}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--model", default="qwen/qwen3.6-35b-a3b")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    client = LMStudioClient(model=args.model, log_dir=ROOT / "logs" / "campaign")
    if args.resume and SAVE.exists():
        campaign = Campaign.load(SAVE, client=client)
        print(f"Resumed campaign at turn {campaign.state.turn}.")
    else:
        campaign = Campaign.new(ROOT / "data", client=client)

    for _ in range(args.turns):
        turn_no = campaign.state.turn
        print(f"\n{'=' * 60}\nTURN {turn_no} - {campaign.state.date.isoformat()}\n{'=' * 60}")
        result = await campaign.play_turn(BOCK_DIRECTIVES)
        for d in result.dispatches:
            side = campaign.dossiers[d["commander"]].side
            print(f"\n--- {campaign.dossiers[d['commander']].name} ({side}) ---")
            print(d["text"])
        if result.report.combats:
            print("\nBATTLES:")
            for c in result.report.combats:
                print(
                    f"  {c['region']}: {','.join(c['attackers'])} vs "
                    f"{','.join(c['defenders'])} odds {c['odds']} -> {c['outcome']}"
                    + (" (ENCIRCLED)" if c["encircled"] else "")
                )
        campaign.save(SAVE)
        print(f"\n[saved to {SAVE}]")

    print("\nFront line snapshot:")
    axis = sorted({c.location for c in campaign.state.living_corps() if c.side == "axis"})
    print(f"  axis corps at: {', '.join(axis)}")
    print(f"  minsk: {campaign.state.control.get('minsk')}, "
          f"smolensk: {campaign.state.control.get('smolensk')}, "
          f"moscow: {campaign.state.control.get('moscow')}")


if __name__ == "__main__":
    asyncio.run(main())
