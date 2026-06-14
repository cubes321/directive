"""Targeted live check: does a real commander produce a sensible unprompted
communiqué? Exercises Campaign._one_communique against the configured model
without running a full turn or touching any save."""

import asyncio
from pathlib import Path

from commanders.campaign import Campaign
from commanders.config import load_config
from commanders.llm import LMStudioClient

ROOT = Path(__file__).parent


async def main():
    cfg = load_config()
    campaign = Campaign.new(ROOT / "data", client=LMStudioClient.from_config(cfg))
    # give Guderian something to be unprompted about
    for c in campaign.state.corps_for("guderian"):
        c.supply = 15
    salient = ["XXIV Panzer Corps is in supply crisis (15/100)", "carried Minsk, a key objective"]
    text = await campaign._one_communique("guderian", salient)
    print("=== Guderian, unprompted ===\n")
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
