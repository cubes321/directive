"""Gather one turn's orders from every commander, LLM and scripted alike.

LLM commanders are queried in parallel - on a local server the requests queue
up, but parallelism still lets prompt processing overlap generation, and it
makes the orchestration code identical when a faster backend appears.
"""

from __future__ import annotations

import asyncio

from commanders.dossier import Dossier
from commanders.llm import LMStudioClient
from commanders.scripted import scripted_orders
from engine.orders import CommanderOrders
from engine.state import GameState


async def gather_orders(
    state: GameState,
    dossiers: dict[str, Dossier],
    client: LMStudioClient,
    llm_commanders: set[str],
    scripted: dict[str, tuple[str, str | None]],
) -> dict[str, CommanderOrders]:
    llm_ids = sorted(llm_commanders)
    llm_results = await asyncio.gather(
        *(client.request_orders(state, dossiers[cid]) for cid in llm_ids)
    )
    all_orders = dict(zip(llm_ids, llm_results, strict=True))
    for cid, (stance, goal) in scripted.items():
        all_orders[cid] = scripted_orders(state, cid, stance=stance, goal=goal)
    return all_orders
