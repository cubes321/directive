"""The per-briefing dynamic order schema, and the guard that keeps it in
lockstep with the validator.

Measured on this game's own captured briefings (spec:
docs/superpowers/specs/2026-08-22-dynamic-order-schema.md): the static schema
leaves the objective range and the defend/reserve conditional unexpressed
(0.982 constraint compliance on qwen3.6-35b-a3b); one branch pair per corps
closes both (1.000).
"""

import json
from pathlib import Path

import pytest

from commanders.prompts import ORDER_SCHEMA, dynamic_order_schema
from engine.orders import POSTURES, CommanderOrders, CorpsOrder, validate_orders
from engine.scenario import load_scenario

DATA_DIR = Path(__file__).parent.parent / "data"
GUDERIAN_CORPS = ("xlvi_pz", "xlvii_pz", "xxiv_pz")


def _state():
    return load_scenario(DATA_DIR)


def _orders_block(schema: dict) -> dict:
    return schema["schema"]["properties"]["orders"]


def _branches_for(schema: dict, corps_id: str) -> list[dict]:
    return [
        b
        for b in _orders_block(schema)["items"]["oneOf"]
        if b["properties"]["corps_id"]["const"] == corps_id
    ]


def _movement_branch(schema: dict, corps_id: str) -> dict:
    return next(
        b for b in _branches_for(schema, corps_id)
        if "attack" in b["properties"]["posture"]["enum"]
    )


def _static_branch(schema: dict, corps_id: str) -> dict:
    return next(
        b for b in _branches_for(schema, corps_id)
        if "defend" in b["properties"]["posture"]["enum"]
    )


def test_every_living_corps_gets_exactly_two_branches():
    schema = dynamic_order_schema(_state(), "guderian")
    branches = _orders_block(schema)["items"]["oneOf"]
    assert len(branches) == 2 * len(GUDERIAN_CORPS)
    for corps_id in GUDERIAN_CORPS:
        assert len(_branches_for(schema, corps_id)) == 2


def test_movement_branch_offers_only_the_moving_postures():
    schema = dynamic_order_schema(_state(), "guderian")
    branch = _movement_branch(schema, "xxiv_pz")
    assert branch["properties"]["posture"]["enum"] == ["attack", "advance"]
    assert branch["properties"]["objective"]["enum"]  # a real list of region ids


def test_static_branch_pins_the_objective_to_null():
    # The residue the static schema could not express: the 35B habitually filled
    # `objective` with the place it was defending. The conditional corrects the
    # field, not the decision - posture is generated first.
    schema = dynamic_order_schema(_state(), "guderian")
    branch = _static_branch(schema, "xxiv_pz")
    assert branch["properties"]["posture"]["enum"] == ["defend", "reserve"]
    assert branch["properties"]["objective"] == {"const": None}


def test_properties_are_ordered_corps_then_posture_then_objective():
    # Property order is what makes the conditional bind AFTER the model's own
    # posture choice; reorder it and the objective constrains the posture.
    schema = dynamic_order_schema(_state(), "guderian")
    for branch in _orders_block(schema)["items"]["oneOf"]:
        assert list(branch["properties"]) == ["corps_id", "posture", "objective"]
        assert branch["required"] == ["corps_id", "posture", "objective"]
        assert branch["additionalProperties"] is False


def test_objective_enums_are_sorted():
    # Determinism (CLAUDE.md): the enums come from reachable(), and an unsorted
    # set would make the request body itself vary across PYTHONHASHSEED.
    schema = dynamic_order_schema(_state(), "guderian")
    for corps_id in GUDERIAN_CORPS:
        enum = _movement_branch(schema, corps_id)["properties"]["objective"]["enum"]
        assert enum == sorted(enum)


def test_current_location_is_always_a_legal_objective():
    # validate_orders accepts objective == corps.location (attacking/advancing
    # in place); the schema must accept it too or it forbids a legal order.
    state = _state()
    schema = dynamic_order_schema(state, "guderian")
    for corps_id in GUDERIAN_CORPS:
        enum = _movement_branch(schema, corps_id)["properties"]["objective"]["enum"]
        assert state.corps[corps_id].location in enum


def test_a_corps_with_nothing_in_reach_still_gets_a_movement_branch():
    # An empty enum is a branch nothing can satisfy. A stranded corps can still
    # be ordered to attack or advance where it stands.
    state = _state()
    state.weather = "mud"
    for corps_id in GUDERIAN_CORPS:
        state.corps[corps_id].supply = 10  # halves an already-halved mud budget
    schema = dynamic_order_schema(state, "guderian")
    branch = _movement_branch(schema, "xxiv_pz")
    assert branch["properties"]["objective"]["enum"] == [state.corps["xxiv_pz"].location]


def test_item_count_is_pinned_to_the_living_corps_count():
    # Coverage (each corps exactly once) is not expressible in JSON Schema;
    # pinning the count plus the existing validator carries it.
    schema = dynamic_order_schema(_state(), "guderian")
    block = _orders_block(schema)
    assert block["minItems"] == len(GUDERIAN_CORPS)
    assert block["maxItems"] == len(GUDERIAN_CORPS)


def test_the_schema_bytes_do_not_depend_on_the_corps_mapping_order():
    # Determinism (CLAUDE.md): nothing whose iteration order is incidental may
    # reach an output - and this output is the request body itself.
    state = _state()
    shuffled = _state()
    shuffled.corps = dict(reversed(list(shuffled.corps.items())))
    assert json.dumps(dynamic_order_schema(shuffled, "guderian")) == json.dumps(
        dynamic_order_schema(state, "guderian")
    )


def test_destroyed_corps_get_no_branches():
    state = _state()
    state.corps["xxiv_pz"].strength = 0
    schema = dynamic_order_schema(state, "guderian")
    assert _branches_for(schema, "xxiv_pz") == []
    assert _orders_block(schema)["minItems"] == len(GUDERIAN_CORPS) - 1


def test_top_level_shape_is_identical_to_the_static_schema():
    schema = dynamic_order_schema(_state(), "guderian")
    assert schema["name"] == ORDER_SCHEMA["name"]
    assert schema["strict"] is ORDER_SCHEMA["strict"]
    static, dynamic = ORDER_SCHEMA["schema"], schema["schema"]
    assert dynamic["type"] == static["type"]
    assert list(dynamic["properties"]) == list(static["properties"])
    assert dynamic["required"] == static["required"]
    assert dynamic["additionalProperties"] is False
    assert dynamic["properties"]["dispatch"] == static["properties"]["dispatch"]
    assert dynamic["properties"]["reasoning"] == static["properties"]["reasoning"]


def test_a_commander_with_no_living_corps_is_refused():
    # An empty oneOf is a grammar that matches nothing; there is no schema to
    # build and no reason to call the model.
    state = _state()
    for corps_id in GUDERIAN_CORPS:
        state.corps[corps_id].strength = 0
    with pytest.raises(ValueError):
        dynamic_order_schema(state, "guderian")


# --------------------------------------------------------------------------
# The load-bearing test: schema and validator must describe the same order set.
# Decision 1 of the spec (the enum comes from the validator's own reach set,
# never the briefing's capped display list) lives or dies here. A narrower
# schema forbids legal orders; a wider one costs a repair round-trip each time.
# --------------------------------------------------------------------------


def _accepts(state, commander: str, order: CorpsOrder) -> bool:
    """Does the validator accept this one order, with the rest of the command
    holding? (validate_orders also checks coverage, so the set must be full.)"""
    own = [
        c for c in state.corps.values()
        if c.commander == commander and not c.is_destroyed
    ]
    orders = [order] + [
        CorpsOrder(c.id, "defend", None) for c in own if c.id != order.corps_id
    ]
    problems = validate_orders(
        CommanderOrders(commander, orders, "", ""),
        state.game_map,
        list(state.corps.values()),
        state.control,
        state.weather,
    )
    return not problems


def _representable(schema: dict, order: CorpsOrder) -> bool:
    for branch in _branches_for(schema, order.corps_id):
        props = branch["properties"]
        if order.posture not in props["posture"]["enum"]:
            continue
        objective = props["objective"]
        allowed = objective["enum"] if "enum" in objective else [objective["const"]]
        if order.objective in allowed:
            return True
    return False


def test_every_order_the_schema_can_represent_is_accepted_by_the_validator():
    state = _state()
    schema = dynamic_order_schema(state, "guderian")
    checked = 0
    for branch in _orders_block(schema)["items"]["oneOf"]:
        props = branch["properties"]
        corps_id = props["corps_id"]["const"]
        objective = props["objective"]
        objectives = objective["enum"] if "enum" in objective else [objective["const"]]
        for posture in props["posture"]["enum"]:
            for obj in objectives:
                order = CorpsOrder(corps_id, posture, obj)
                assert _accepts(state, "guderian", order), f"schema allows rejected {order}"
                checked += 1
    assert checked > 20, "the sweep must actually cover the branch space"


def test_every_order_the_validator_accepts_is_representable_by_a_branch():
    # The converse direction. The engine reads `objective` only for attack and
    # advance (turn.py:138); on defend and reserve it is ignored, so the
    # schema's null is a normalization of an accepted order rather than a
    # narrowing of it - canonicalize before comparing.
    state = _state()
    schema = dynamic_order_schema(state, "guderian")
    candidates = [None, *sorted(state.game_map.regions)]
    for corps_id in GUDERIAN_CORPS:
        for posture in POSTURES:
            for objective in candidates:
                accepted = _accepts(state, "guderian", CorpsOrder(corps_id, posture, objective))
                canonical = None if posture in ("defend", "reserve") else objective
                representable = _representable(schema, CorpsOrder(corps_id, posture, canonical))
                assert accepted == representable, (
                    f"{corps_id} {posture} -> {objective}: "
                    f"validator={accepted} schema={representable}"
                )
