"""The client must cap in-flight requests to the server's parallelism, so
queued requests wait in our async queue (no timeout running) instead of the
server's queue (timeout burning). Root cause of the turn-fallback storm."""

import asyncio
import json
from pathlib import Path

import httpx

from commanders.dossier import load_dossiers
from commanders.llm import LMStudioClient
from engine.scenario import load_scenario

DATA_DIR = Path(__file__).parent.parent / "data"


class TrackingTransport(httpx.AsyncBaseTransport):
    """Records peak concurrent in-flight requests; each request yields so
    overlaps are real."""

    def __init__(self):
        self.inflight = 0
        self.peak = 0

    async def handle_async_request(self, request):
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        await asyncio.sleep(0.02)
        self.inflight -= 1
        payload = {
            "orders": [
                {"corps_id": "xxiv_pz", "posture": "defend", "objective": None},
                {"corps_id": "xlvi_pz", "posture": "defend", "objective": None},
                {"corps_id": "xlvii_pz", "posture": "defend", "objective": None},
            ],
            "dispatch": "Holding.",
            "reasoning": "",
        }
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )


async def test_inflight_requests_are_capped_at_max_concurrency():
    transport = TrackingTransport()
    client = LMStudioClient(model="m", transport=transport, max_concurrency=3)
    state = load_scenario(DATA_DIR)
    guderian = load_dossiers(DATA_DIR)["guderian"]
    await asyncio.gather(*(client.request_orders(state, guderian) for _ in range(9)))
    assert transport.peak <= 3


async def test_concurrency_gate_actually_overlaps():
    # a too-strict gate (1) would serialize everything; we want real parallelism
    transport = TrackingTransport()
    client = LMStudioClient(model="m", transport=transport, max_concurrency=3)
    state = load_scenario(DATA_DIR)
    guderian = load_dossiers(DATA_DIR)["guderian"]
    await asyncio.gather(*(client.request_orders(state, guderian) for _ in range(9)))
    assert transport.peak >= 2  # more than one ran at once


async def test_default_timeout_is_generous_enough_for_thinking_models():
    # the production failure was a 120s timeout against 50-217s generations
    client = LMStudioClient(model="m")
    assert client.timeout >= 240
