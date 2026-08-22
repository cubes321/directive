import json
import logging
from pathlib import Path

import httpx
import pytest

from commanders.dossier import load_dossiers
from commanders.llm import LMStudioClient, LMStudioUnavailable
from commanders.prompts import ORDER_SCHEMA, dynamic_order_schema
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


async def test_answer_in_reasoning_content_is_used():
    # LM Studio + thinking models (e.g. Qwen3.6) can leave "content" empty and
    # put the whole output, including the final JSON, in "reasoning_content".
    state, dossier = setup_state()

    def responder(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": json.dumps(valid_payload()) + "\n",
                        }
                    }
                ]
            },
        )

    client = make_client(responder)
    orders = await client.request_orders(state, dossier)
    assert orders.orders[0].objective == "baranovichi"


async def test_json_is_extracted_from_thinking_preamble():
    state, dossier = setup_state()
    content = "<think>\nMinsk is the key.\n</think>\n" + json.dumps(valid_payload())

    def responder(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    client = make_client(responder)
    orders = await client.request_orders(state, dossier)
    assert orders.orders[0].objective == "baranovichi"


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


async def test_config_error_surfaces_instead_of_silent_fallback():
    # A 4xx (wrong model, bad param, bad key) is a configuration error that
    # affects every commander; it must stop the turn with a clear message, not
    # be laundered into empty "invalid JSON" responses and hold-orders.
    state, dossier = setup_state()

    def responder(request):
        return httpx.Response(
            404,
            json={"error": {"message": "Not found the model kimi-k2.6p"}},
        )

    client = make_client(responder)
    with pytest.raises(LMStudioUnavailable) as excinfo:
        await client.request_orders(state, dossier)
    msg = str(excinfo.value)
    assert "404" in msg
    assert "kimi-k2.6p" in msg  # the server's own explanation is surfaced


async def test_server_error_still_degrades_to_hold_orders():
    # A 5xx or overload is transient and per-request; degrade that one
    # commander to hold-orders and keep the turn going, as before.
    state, dossier = setup_state()

    def responder(request):
        return httpx.Response(503, text="upstream overloaded")

    client = make_client(responder)
    orders = await client.request_orders(state, dossier)
    assert all(o.posture == "defend" for o in orders.orders)


async def test_request_timeout_408_degrades_not_raises():
    # 408 is a 4xx but transient (the request timed out), not a config error;
    # it must degrade to hold-orders like a read timeout, not halt the turn.
    state, dossier = setup_state()

    def responder(request):
        return httpx.Response(408, text="request timeout")

    client = make_client(responder)
    orders = await client.request_orders(state, dossier)
    assert all(o.posture == "defend" for o in orders.orders)


async def test_token_usage_is_logged(tmp_path):
    state, dossier = setup_state()

    def responder(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(valid_payload())}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
        })

    client = make_client(responder, log_dir=tmp_path)
    await client.request_orders(state, dossier)
    token_log = tmp_path / "tokens.jsonl"
    assert token_log.exists()
    entries = [json.loads(x) for x in token_log.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert entries[-1]["role"] == "guderian"
    assert entries[-1]["prompt_tokens"] == 100
    assert entries[-1]["completion_tokens"] == 40
    assert entries[-1]["total_tokens"] == 140


async def test_transcripts_are_logged(tmp_path):
    state, dossier = setup_state()
    client = make_client(lambda r: chat_response(valid_payload()), log_dir=tmp_path)
    await client.request_orders(state, dossier)
    logs = list(tmp_path.glob("*.json"))
    assert logs, "expected a transcript log file"
    logged = json.loads(logs[0].read_text(encoding="utf-8"))
    assert logged["commander"] == "guderian"
    assert logged["request"]["messages"]


async def test_warm_up_sends_one_cheap_request_per_distinct_model():
    # LM Studio JIT-loads a model on first use. A cold model answers with
    # usage.completion_tokens > 0 but EMPTY content and empty reasoning_content,
    # so _chat returns "" - observed costing a repair round-trip on 8 of 9
    # commanders in turn 1 of every game against qwen/qwen3.5-9b.
    seen = []

    def responder(request):
        seen.append(json.loads(request.content))
        return chat_response(valid_payload())

    client = make_client(responder, models={"staff": "other-model", "hoth": "test-model"})
    await client.warm_up()
    assert {r["model"] for r in seen} == {"test-model", "other-model"}
    assert all(r["max_tokens"] == 1 for r in seen), "warm-up must not generate a reply"


async def test_warm_up_is_a_no_op_once_the_models_are_resident():
    seen = []

    def responder(request):
        seen.append(json.loads(request.content))
        return chat_response(valid_payload())

    client = make_client(responder)
    await client.warm_up()
    await client.warm_up()
    assert len(seen) == 1


async def test_warm_up_carries_the_configured_params():
    # Without reasoning_effort the warm-up itself would think, which on a cold
    # 9b is exactly the multi-second stall it exists to absorb.
    seen = []

    def responder(request):
        seen.append(json.loads(request.content))
        return chat_response(valid_payload())

    client = make_client(responder, params={"reasoning_effort": "none"})
    await client.warm_up()
    assert seen[0]["reasoning_effort"] == "none"


async def test_warm_up_never_raises_when_the_backend_is_down():
    # A convenience must not become a new way for the game to fail to start.
    # The real request that follows still surfaces the error loudly.
    def responder(request):
        raise httpx.ConnectError("connection refused")

    await make_client(responder).warm_up()  # must not raise


# --------------------------------------------------------------------------
# The per-turn order schema. Spec:
# docs/superpowers/specs/2026-08-22-dynamic-order-schema.md
# --------------------------------------------------------------------------


def _sent_schema(call: dict) -> dict | None:
    return call.get("response_format", {}).get("json_schema")


def _is_dynamic(call: dict) -> bool:
    schema = _sent_schema(call)
    return bool(schema) and "oneOf" in schema["schema"]["properties"]["orders"]["items"]


async def test_the_orders_request_carries_a_schema_built_from_this_turns_state():
    state, dossier = setup_state()
    calls = []

    def responder(request):
        calls.append(json.loads(request.content))
        return chat_response(valid_payload())

    client = make_client(responder)
    await client.request_orders(state, dossier)
    assert _sent_schema(calls[0]) == dynamic_order_schema(state, "guderian")
    branches = _sent_schema(calls[0])["schema"]["properties"]["orders"]["items"]["oneOf"]
    assert len(branches) == 6  # two per living corps
    # and the enums really are this turn's reach, not the whole map
    enums = [b["properties"]["objective"].get("enum", []) for b in branches]
    assert all("moscow" not in enum for enum in enums)


async def test_the_schema_follows_the_state_rather_than_being_fixed_once():
    # Per briefing, not per process: a corps lost last week has to disappear
    # from this week's grammar, or the model can still be handed its id.
    state, dossier = setup_state()
    state.corps["xxiv_pz"].strength = 0
    calls = []

    def responder(request):
        calls.append(json.loads(request.content))
        payload = valid_payload()
        payload["orders"] = payload["orders"][1:]
        return chat_response(payload)

    client = make_client(responder)
    await client.request_orders(state, dossier)
    orders_block = _sent_schema(calls[0])["schema"]["properties"]["orders"]
    ids = {b["properties"]["corps_id"]["const"] for b in orders_block["items"]["oneOf"]}
    assert ids == {"xlvi_pz", "xlvii_pz"}
    assert orders_block["minItems"] == orders_block["maxItems"] == 2


async def test_the_repair_round_trip_reuses_the_same_dynamic_schema():
    state, dossier = setup_state()
    calls = []

    def responder(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            bad = valid_payload()
            bad["orders"][0]["objective"] = "moscow"  # far out of reach
            return chat_response(bad)
        return chat_response(valid_payload())

    client = make_client(responder)
    await client.request_orders(state, dossier)
    assert len(calls) == 2
    assert _sent_schema(calls[1]) == _sent_schema(calls[0])


async def test_a_backend_that_rejects_the_dynamic_schema_falls_back_to_the_static_one():
    # A cloud backend that refuses oneOf/const-heavy schemas must not brick the
    # campaign: retry that one call with the schema that has always worked.
    state, dossier = setup_state()
    calls = []

    def responder(request):
        call = json.loads(request.content)
        calls.append(call)
        if _is_dynamic(call):
            return httpx.Response(400, json={"error": {"message": "oneOf is not supported"}})
        return chat_response(valid_payload())

    client = make_client(responder)
    orders = await client.request_orders(state, dossier)  # must not raise
    assert [_is_dynamic(c) for c in calls] == [True, False]
    assert _sent_schema(calls[1]) == ORDER_SCHEMA
    assert orders.orders[0].objective == "baranovichi"


async def test_the_schema_fallback_says_loudly_which_schema_was_used(caplog):
    state, dossier = setup_state()

    def responder(request):
        if _is_dynamic(json.loads(request.content)):
            return httpx.Response(400, json={"error": {"message": "oneOf is not supported"}})
        return chat_response(valid_payload())

    client = make_client(responder)
    with caplog.at_level(logging.WARNING):
        await client.request_orders(state, dossier)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "static" in text.lower()
    assert "oneOf is not supported" in text  # the backend's own explanation


async def test_the_schema_fallback_is_recorded_in_the_transcript(tmp_path):
    # Offline analysis has to be able to tell which grammar produced a run;
    # a silent degrade would show up as the model getting worse.
    state, dossier = setup_state()

    def responder(request):
        if _is_dynamic(json.loads(request.content)):
            return httpx.Response(400, json={"error": {"message": "oneOf is not supported"}})
        return chat_response(valid_payload())

    client = make_client(responder, log_dir=tmp_path)
    await client.request_orders(state, dossier)
    logged = json.loads(next(iter(tmp_path.glob("*.json"))).read_text(encoding="utf-8"))
    assert logged["schema"] == "static-fallback"


async def test_a_normal_run_records_that_the_dynamic_schema_was_used(tmp_path):
    state, dossier = setup_state()
    client = make_client(lambda r: chat_response(valid_payload()), log_dir=tmp_path)
    await client.request_orders(state, dossier)
    logged = json.loads(next(iter(tmp_path.glob("*.json"))).read_text(encoding="utf-8"))
    assert logged["schema"] == "dynamic"


async def test_a_backend_that_rejects_both_schemas_still_raises():
    state, dossier = setup_state()
    calls = []

    def responder(request):
        calls.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"message": "json_schema unsupported"}})

    client = make_client(responder)
    with pytest.raises(LMStudioUnavailable) as excinfo:
        await client.request_orders(state, dossier)
    assert "400" in str(excinfo.value)
    assert len(calls) == 2  # the dynamic request, then one static retry - no more


async def test_a_transient_4xx_does_not_trigger_the_schema_fallback():
    # 429 and 408 are per-request and say nothing about the schema; they degrade
    # to hold-orders exactly as before, still under the per-turn grammar.
    state, dossier = setup_state()
    calls = []

    def responder(request):
        calls.append(json.loads(request.content))
        return httpx.Response(429, text="slow down")

    client = make_client(responder)
    orders = await client.request_orders(state, dossier)
    assert all(o.posture == "defend" for o in orders.orders)
    assert all(_is_dynamic(c) for c in calls)


async def test_an_unreachable_server_is_not_retried_with_a_different_schema():
    # No schema fixes a refused connection; a retry would only double the wait
    # before the turn stops.
    state, dossier = setup_state()
    calls = []

    def responder(request):
        calls.append(request)
        raise httpx.ConnectError("connection refused")

    client = make_client(responder)
    with pytest.raises(LMStudioUnavailable):
        await client.request_orders(state, dossier)
    assert len(calls) == 1


async def test_a_commander_with_no_living_corps_is_never_sent_to_the_model():
    # There is no schema to build (an empty oneOf matches nothing) and nothing
    # to ask. Today a wiped-out commander still burned one call every turn for
    # the rest of the campaign.
    state, dossier = setup_state()
    for corps in state.corps_for("guderian"):
        corps.strength = 0
    calls = []

    def responder(request):
        calls.append(json.loads(request.content))
        return chat_response(valid_payload())

    client = make_client(responder)
    orders = await client.request_orders(state, dossier)
    assert calls == []
    assert orders.commander == "guderian"
    assert orders.orders == ()


async def test_conversational_requests_still_carry_no_schema():
    # request_text serves staff reports and commander conversations. A schema
    # there would push prose toward order-JSON; it is deliberately absent.
    seen = []

    def responder(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Understood."}}]})

    client = make_client(responder)
    await client.request_text([{"role": "user", "content": "Report."}])
    assert "response_format" not in seen[0]
