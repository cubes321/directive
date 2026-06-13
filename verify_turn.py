"""Verification: run one full 9-commander turn against the live model with the
concurrency gate, and report per-commander outcomes from the transcripts."""

import asyncio
import json
from pathlib import Path

from commanders.campaign import Campaign
from commanders.config import load_config
from commanders.llm import LMStudioClient

ROOT = Path(__file__).parent
LOG_DIR = ROOT / "logs" / "verify"


async def main():
    for f in LOG_DIR.glob("*.json"):
        f.unlink()
    cfg = load_config()
    print(f"model {cfg.model} | timeout {cfg.timeout_seconds}s | "
          f"max_concurrency {cfg.max_concurrency}")
    campaign = Campaign.new(ROOT / "data", client=LMStudioClient.from_config(cfg, log_dir=LOG_DIR))
    import time
    t0 = time.monotonic()
    result = await campaign.play_turn({})
    wall = time.monotonic() - t0

    outcomes = {}
    for f in sorted(LOG_DIR.glob("turn01_*.json")):
        t = json.loads(f.read_text(encoding="utf-8"))
        outcomes[t["commander"]] = t["outcome"]
    print(f"\nturn resolved in {wall:.0f}s")
    print("outcomes:", outcomes)
    usable = sum(1 for o in outcomes.values() if o != "fallback")
    print(f"usable: {usable}/{len(outcomes)}  (fallbacks: "
          f"{sum(1 for o in outcomes.values() if o == 'fallback')})")
    print(f"staff report: {result.dispatches[-1]['text'][:80]}...")


if __name__ == "__main__":
    asyncio.run(main())
