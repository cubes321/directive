"""Diagnostic: does per-request latency blow past the timeout under concurrency?

Fires identical chat-completion requests at the configured endpoint, first
one-at-a-time, then all at once, and reports latency + empty/timeout outcomes.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from commanders.config import load_config

cfg = load_config()
PROMPT = (
    "You are a German corps commander in 1941. In 120 words, describe your "
    "intended advance for the coming week and the supply situation you face. "
    "Write in character."
)


async def one(client: httpx.AsyncClient, i: int, timeout: float) -> dict:
    body = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0.7,
    }
    t0 = time.monotonic()
    try:
        r = await client.post(f"{cfg.base_url}/chat/completions", json=body, timeout=timeout)
        msg = r.json()["choices"][0]["message"]
        content = msg.get("content") or msg.get("reasoning_content") or ""
        return {"i": i, "secs": time.monotonic() - t0, "chars": len(content),
                "empty": content.strip() == ""}
    except Exception as e:
        return {"i": i, "secs": time.monotonic() - t0, "error": type(e).__name__}


async def run_batch(label: str, n: int, concurrency: int, timeout: float) -> None:
    print(f"\n=== {label}: {n} requests, concurrency {concurrency}, timeout {timeout}s ===")
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient() as client:
        async def guarded(i):
            async with sem:
                return await one(client, i, timeout)
        t0 = time.monotonic()
        results = await asyncio.gather(*(guarded(i) for i in range(n)))
    wall = time.monotonic() - t0
    for r in sorted(results, key=lambda x: x["i"]):
        if "error" in r:
            detail = r["error"]
        else:
            detail = f"{r['chars']} chars{' EMPTY' if r.get('empty') else ''}"
        print(f"  req {r['i']}: {r['secs']:5.1f}s  {detail}")
    secs = [r["secs"] for r in results]
    empties = sum(1 for r in results if r.get("empty") or r.get("error"))
    print(f"  wall {wall:.1f}s | per-req min {min(secs):.1f} max {max(secs):.1f} "
          f"| failures {empties}/{n}")


async def main() -> None:
    print(f"endpoint {cfg.base_url} model {cfg.model}")
    await run_batch("all-at-once (current behavior)", 9, 9, 120)
    await run_batch("gated to 3 (proposed fix)", 9, 3, 240)


if __name__ == "__main__":
    asyncio.run(main())
