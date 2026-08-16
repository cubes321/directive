import json as _json
from collections import Counter
from pathlib import Path

import pytest

from commanders.briefing import build_briefing
from commanders.divergence import bucket_for, parse_staff_options, score_transcript, summarize
from engine.scenario import load_scenario

DATA_DIR = Path(__file__).parent.parent / "data"


def test_parses_each_corps_options_in_order():
    state = load_scenario(DATA_DIR)
    options = parse_staff_options(build_briefing(state, "guderian"))
    assert options["xxiv_pz"] == [
        ("attack", "baranovichi"),
        ("advance", "pripyat"),
        ("defend", None),
    ]


def test_parses_every_briefed_corps():
    state = load_scenario(DATA_DIR)
    options = parse_staff_options(build_briefing(state, "guderian"))
    assert set(options) == {"xxiv_pz", "xlvi_pz", "xlvii_pz"}


def test_a_worn_corps_is_offered_reserve_not_hold():
    # _staff_options swaps "hold current position" for "hold in reserve" below
    # 70 supply or organization; both must map to a posture.
    state = load_scenario(DATA_DIR)
    corps = state.corps_for("guderian")[0]
    corps.supply = 50
    options = parse_staff_options(build_briefing(state, "guderian"))
    assert options[corps.id][-1] == ("reserve", None)


def test_an_unrecognized_option_line_raises():
    # Silence here would be the worst failure mode: unparsed options make every
    # order look off-menu, i.e. personality appears to rise as the metric blinds.
    briefing = "STAFF OPTIONS:\nFor X Corps [x_ak]:\n  * dig in and pray\n"
    with pytest.raises(ValueError, match="dig in and pray"):
        parse_staff_options(briefing)


def test_a_briefing_without_staff_options_yields_nothing():
    assert parse_staff_options("SITUATION BRIEFING - no options here") == {}


ATTACK = ("attack", "minsk")
ADVANCE = ("advance", "slonim")
HOLD = ("defend", None)


def _order(posture, objective=None, corps_id="xxiv_pz"):
    return {"corps_id": corps_id, "posture": posture, "objective": objective}


def test_the_staffs_lead_suggestion_is_first():
    assert bucket_for(_order("attack", "minsk"), [ATTACK, ADVANCE, HOLD]) == "first"


def test_a_later_move_suggestion_is_middle():
    assert bucket_for(_order("advance", "slonim"), [ATTACK, ADVANCE, HOLD]) == "middle"


def test_the_trailing_hold_option_is_hold():
    assert bucket_for(_order("defend"), [ATTACK, ADVANCE, HOLD]) == "hold"


def test_index_one_is_hold_when_the_list_is_only_two_long():
    # A quiet sector offers one move and then the hold. Raw rank would call
    # this "middle" and read as independence; it is the opposite.
    assert bucket_for(_order("defend"), [ATTACK, HOLD]) == "hold"


def test_the_only_option_being_hold_scores_as_hold_not_first():
    # Starving infantry in the mud can reach nothing at all.
    assert bucket_for(_order("defend"), [HOLD]) == "hold"


def test_an_objective_the_staff_never_raised_is_off_menu():
    assert bucket_for(_order("advance", "slutsk"), [ATTACK, ADVANCE, HOLD]) == "off-menu"


def test_the_right_region_with_the_wrong_posture_is_off_menu():
    assert bucket_for(_order("advance", "minsk"), [ATTACK, ADVANCE, HOLD]) == "off-menu"


def test_a_missing_objective_key_is_treated_as_none():
    assert bucket_for({"corps_id": "x", "posture": "defend"}, [ATTACK, HOLD]) == "hold"


def _transcript(state, commander, attempts=None, final_orders=None):
    briefing = build_briefing(state, commander)
    out = {
        "commander": commander,
        "request": {"messages": [
            {"role": "system", "content": "persona"},
            {"role": "user", "content": briefing},
        ]},
        "orders": {"orders": final_orders or []},
    }
    if attempts is not None:
        out["attempts"] = attempts
    return out


def test_scores_the_orders_of_a_clean_transcript():
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": [
        {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
        {"corps_id": "xlvi_pz", "posture": "advance", "objective": "pripyat"},
        {"corps_id": "xlvii_pz", "posture": "defend", "objective": None},
    ]})
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": reply}])
    )
    assert buckets == Counter({"first": 1, "middle": 1, "hold": 1})
    assert unscored == 0


def test_scores_the_first_attempt_not_the_salvaged_result():
    # The model ordered an attack; salvage forced all three to defend. Scoring
    # the final set would report this commander as passive when he was not.
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": [
        {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
    ]})
    forced = [{"corps_id": "xxiv_pz", "posture": "defend", "objective": None}]
    buckets, _ = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": reply}, {"response": "x"}],
                    final_orders=forced)
    )
    assert buckets == Counter({"first": 1})


def test_an_unreadable_first_attempt_scores_nothing_and_counts_its_corps():
    state = load_scenario(DATA_DIR)
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": "not json at all"}])
    )
    assert buckets == Counter()
    assert unscored == 3          # guderian was briefed on three corps


def test_falls_back_to_the_final_orders_when_there_are_no_attempts():
    state = load_scenario(DATA_DIR)
    final = [{"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"}]
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", final_orders=final)
    )
    assert buckets == Counter({"first": 1})
    # xlvi_pz and xlvii_pz were briefed but this fixture's final orders only
    # cover xxiv_pz - they now count as unscored (see
    # test_a_briefed_corps_with_no_order_is_unscored).
    assert unscored == 2


def test_an_order_for_an_unbriefed_corps_is_unscored():
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": [
        {"corps_id": "ghost_pz", "posture": "attack", "objective": "minsk"},
    ]})
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": reply}])
    )
    assert buckets == Counter()
    # ghost_pz itself, plus all three of guderian's real briefed corps, which
    # got no order at all in this reply (see test_a_briefed_corps_with_no_order...).
    assert unscored == 4


def test_a_briefed_corps_with_no_order_is_unscored():
    # A first attempt that is valid JSON but silently omits one of the three
    # briefed corps must not let that corps vanish from the denominator.
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": [
        {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
        {"corps_id": "xlvi_pz", "posture": "advance", "objective": "pripyat"},
        # xlvii_pz never receives an order.
    ]})
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": reply}])
    )
    assert buckets == Counter({"first": 1, "middle": 1})
    assert unscored == 1


def test_a_duplicate_order_for_the_same_corps_does_not_inflate_unscored():
    # Two entries for the same corps must not make the missing-corps count
    # come out wrong (a naive len(options) - len(orders) diff would).
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": [
        {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
        {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
    ]})
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": reply}])
    )
    assert buckets == Counter({"first": 2})
    # xlvi_pz and xlvii_pz got nothing; xxiv_pz counts as covered once.
    assert unscored == 2


def test_orders_decoding_to_a_dict_degrades_entries_to_unscored():
    # Some backends don't strictly enforce the schema (see moonshot/kimi notes).
    # If "orders" comes back as an object instead of an array, list(dict)
    # succeeds and yields bare strings as "orders" - those must not reach
    # order.get()/order[...] uncaught.
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": {"corps_id": "xxiv_pz"}})
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": reply}])
    )
    assert buckets == Counter()
    # the one bogus string entry, plus all three briefed corps missing.
    assert unscored == 4


def test_an_order_missing_posture_is_unscored_not_a_crash():
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": [
        {"corps_id": "xxiv_pz", "objective": "baranovichi"},
    ]})
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": reply}])
    )
    assert buckets == Counter()
    # the malformed xxiv_pz order, plus the two other briefed corps missing.
    assert unscored == 3


def test_falls_back_to_final_orders_when_attempts_is_an_empty_list():
    # `if not attempts:` also catches attempts: [], not just a missing key.
    state = load_scenario(DATA_DIR)
    final = [
        {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
        {"corps_id": "xlvi_pz", "posture": "advance", "objective": "pripyat"},
        {"corps_id": "xlvii_pz", "posture": "defend", "objective": None},
    ]
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", attempts=[], final_orders=final)
    )
    assert buckets == Counter({"first": 1, "middle": 1, "hold": 1})
    assert unscored == 0


def test_summarize_groups_by_commander_and_totals_under_all():
    state = load_scenario(DATA_DIR)
    aggressive = _json.dumps({"orders": [
        {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
    ]})
    passive = _json.dumps({"orders": [
        {"corps_id": "xxxix_pz", "posture": "defend", "objective": None},
    ]})
    rows = summarize([
        _transcript(state, "guderian", attempts=[{"response": aggressive}]),
        _transcript(state, "hoth", attempts=[{"response": passive}]),
    ])
    assert rows["guderian"][0] == Counter({"first": 1})
    assert rows["hoth"][0] == Counter({"hold": 1})
    assert rows["ALL"][0] == Counter({"first": 1, "hold": 1})
