import json
from pathlib import Path

import httpx
import pytest

from commanders.dossier import load_dossiers
from commanders.llm import LMStudioClient, LMStudioUnavailable
from engine.scenario import load_scenario

DATA_DIR = Path(__file__).parent.parent / "data"


def make_client(responder, **kwargs):
    transport = httpx.MockTransport(responder)
    return LMStudioClient(model="test-model", transport=transport, **kwargs)


def chat_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(payload)}}]},
    )


def valid_payload():
    return {
        "orders": [
            {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
            {"corps_id": "xlvi_pz", "posture": "advance", "objective": "pripyat"},
            {"corps_id": "xlvii_pz", "posture": "defend", "objective": None},
        ],
        "dispatch": "The group strikes at dawn toward Baranovichi.",
        "reasoning": "Mass on the schwerpunkt.",
    }


def setup_state():
    state = load_scenario(DATA_DIR)
    dossiers = load_dossiers(DATA_DIR)
    return state, dossiers["guderian"]


async def test_valid_response_becomes_orders():
    state, dossier = setup_state()
    calls = []

    def responder(request):
        calls.append(json.loads(request.content))
        return chat_response(valid_payload())

    client = make_client(responder)
    orders = await client.request_orders(state, dossier)
    assert orders.commander == "guderian"
    assert orders.orders[0].objective == "baranovichi"
    assert "Baranovichi" in orders.dispatch
    assert len(calls) == 1
    # the request used structured output
    assert calls[0]["response_format"]["type"] == "json_schema"


async def test_invalid_orders_get_one_repair_attempt():
    state, dossier = setup_state()
    calls = []

    def responder(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            bad = valid_payload()
            bad["orders"][0]["corps_id"] = "sov_13a"  # not his corps
            return chat_response(bad)
        return chat_response(valid_payload())

    client = make_client(responder)
    orders = await client.request_orders(state, dossier)
    assert orders.orders[0].corps_id == "xxiv_pz"
    assert len(calls) == 2
    # the repair message quoted the validation problem
    repair_text = json.dumps(calls[1]["messages"])
    assert "sov_13a" in repair_text


async def test_persistent_garbage_falls_back_to_hold_orders():
    state, dossier = setup_state()

    def responder(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "I ATTACK EVERYWHERE!!"}}]}
        )

    client = make_client(responder)
    orders = await client.request_orders(state, dossier)
    assert all(o.posture == "defend" for o in orders.orders)
    assert {o.corps_id for o in orders.orders} == {"xxiv_pz", "xlvi_pz", "xlvii_pz"}


async def test_unreachable_server_raises():
    state, dossier = setup_state()

    def responder(request):
        raise httpx.ConnectError("connection refused")

    client = make_client(responder)
    with pytest.raises(LMStudioUnavailable):
        await client.request_orders(state, dossier)


async def test_transcripts_are_logged(tmp_path):
    state, dossier = setup_state()
    client = make_client(lambda r: chat_response(valid_payload()), log_dir=tmp_path)
    await client.request_orders(state, dossier)
    logs = list(tmp_path.glob("*.json"))
    assert logs, "expected a transcript log file"
    logged = json.loads(logs[0].read_text(encoding="utf-8"))
    assert logged["commander"] == "guderian"
    assert logged["request"]["messages"]
