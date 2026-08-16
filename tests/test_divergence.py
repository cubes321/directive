import json as _json
from collections import Counter
from pathlib import Path

import pytest

from commanders.briefing import build_briefing
from commanders.divergence import (
    bucket_for,
    menu_shapes,
    parse_in_range,
    parse_staff_options,
    score_transcript,
    summarize,
)
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


def test_parses_the_in_range_line_including_regions_marked_full():
    # The legal-objective set is already in the briefing. A FULL region is still
    # a legal target (the move merely bounces), so the annotation must be
    # ignored - ids come from the [id: ...] markers, not from the prose.
    state = load_scenario(DATA_DIR)
    ranges = parse_in_range(build_briefing(state, "guderian"))
    assert ranges["xxiv_pz"] == {"baranovichi", "pripyat", "siedlce", "warsaw"}


def test_a_corps_with_nothing_in_range_parses_as_an_empty_set():
    # "(nowhere)" means every objective is illegal - which is not the same as
    # "we could not read the line", where nothing can be judged.
    briefing = (
        "STAFF OPTIONS:\nFor X Corps [x_ak]:\n"
        "  * hold current position\n  In range this week: (nowhere)\n"
    )
    assert parse_in_range(briefing) == {"x_ak": set()}


def test_a_corps_block_without_an_in_range_line_is_absent_from_the_ranges():
    briefing = "STAFF OPTIONS:\nFor X Corps [x_ak]:\n  * hold current position\n"
    assert parse_in_range(briefing) == {}


ATTACK = ("attack", "minsk")
ADVANCE = ("advance", "slonim")
HOLD = ("defend", None)
RESERVE = ("reserve", None)
IN_RANGE = {"minsk", "slonim", "slutsk"}


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


def test_the_same_region_under_the_other_move_posture_is_the_staffs_option():
    # WAS asserted as off-menu, which encoded a bug. attack and advance are ONE
    # order to the engine - engine/turn.py:138 is the only place either posture
    # is read and it reads them jointly - so "advance to Minsk" against a staff
    # option of "attack Minsk" is taking the suggestion, not diverging from it.
    # Scored the old way, a model that always took option #1 but wrote the other
    # verb would have read as 0% first / 100% off-menu: the metric defeated by
    # the very collapse it exists to detect.
    assert bucket_for(_order("advance", "minsk"), [ATTACK, ADVANCE, HOLD]) == "first"


def test_an_attack_matches_a_staff_advance_option():
    assert bucket_for(_order("attack", "slonim"), [ATTACK, ADVANCE, HOLD]) == "middle"


def test_a_missing_objective_key_is_treated_as_none():
    assert bucket_for({"corps_id": "x", "posture": "defend"}, [ATTACK, HOLD]) == "hold"


def test_reserve_is_hold_when_the_staff_offered_hold_current_position():
    # defend and reserve are the same physical inaction (they differ only in
    # recovery, engine/turn.py:268), and which one the staff offers is a pure
    # function of the corps's own supply/organization (briefing.py:110). Letting
    # the mismatch fall through to off-menu put "sat still" in the bucket
    # reserved for the strongest sign of independence.
    assert bucket_for(_order("reserve"), [ATTACK, ADVANCE, HOLD]) == "hold"


def test_defend_is_hold_when_the_staff_offered_reserve():
    assert bucket_for(_order("defend"), [ATTACK, ADVANCE, RESERVE]) == "hold"


def test_reserve_is_hold_when_the_staff_offered_reserve():
    assert bucket_for(_order("reserve"), [ATTACK, ADVANCE, RESERVE]) == "hold"


def test_the_only_option_being_reserve_scores_as_hold_not_first():
    assert bucket_for(_order("reserve"), [RESERVE]) == "hold"


def test_a_defend_naming_the_region_it_already_holds_is_hold():
    # Observed: sov_13a at Minsk ordered "defend / minsk". The engine ignores
    # `objective` for defend and reserve entirely, so it cannot make inaction
    # into independence.
    assert bucket_for(_order("defend", "minsk"), [ATTACK, ADVANCE, HOLD], IN_RANGE) == "hold"


def test_an_unreachable_objective_is_unscored_not_off_menu():
    # An objective out of reach is rejected by validate_orders and forced to
    # 'defend' by salvage_orders - a model failure, already reported by
    # analyze_logs.py. Scoring it as off-menu credited a broken order as the
    # commander's best independent thinking.
    assert bucket_for(_order("advance", "moscow"), [ATTACK, ADVANCE, HOLD], IN_RANGE) == "unscored"


def test_a_reachable_objective_the_staff_never_raised_is_still_off_menu():
    assert bucket_for(_order("advance", "slutsk"), [ATTACK, ADVANCE, HOLD], IN_RANGE) == "off-menu"


def test_an_unknown_in_range_set_leaves_legality_unjudged():
    # No "In range" line in the briefing means we cannot tell legal from
    # illegal; degrade to the old reading rather than voiding every order.
    assert bucket_for(_order("advance", "moscow"), [ATTACK, ADVANCE, HOLD], None) == "off-menu"


def test_nothing_in_range_makes_an_unoffered_objective_unscored():
    # A corps whose staff could only say "hold" has nothing legal to name.
    assert bucket_for(_order("advance", "minsk"), [HOLD], set()) == "unscored"


def test_an_offered_option_is_never_second_guessed_against_the_range():
    # The staff only ever offers reachable regions; the range check exists for
    # objectives the staff did NOT list.
    assert bucket_for(_order("attack", "minsk"), [ATTACK, ADVANCE, HOLD], set()) == "first"


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


def test_an_order_out_of_reach_is_unscored_rather_than_off_menu():
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": [
        {"corps_id": "xxiv_pz", "posture": "advance", "objective": "moscow"},
        {"corps_id": "xlvi_pz", "posture": "advance", "objective": "pripyat"},
        {"corps_id": "xlvii_pz", "posture": "defend", "objective": None},
    ]})
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": reply}])
    )
    assert buckets == Counter({"middle": 1, "hold": 1})
    assert unscored == 1


def test_an_advance_on_a_region_the_staff_offered_as_an_attack_is_first():
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": [
        {"corps_id": "xxiv_pz", "posture": "advance", "objective": "baranovichi"},
    ]})
    buckets, _ = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": reply}])
    )
    assert buckets == Counter({"first": 1})


def test_a_corps_id_with_a_stray_leading_space_still_scores():
    # engine/orders.py:_corps_order_from_dict strips these (observed from
    # qwen3.5-4b). Comparing raw strings here would systematically penalise the
    # very model whose quirk the engine already documents.
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": [
        {"corps_id": " xxiv_pz", "posture": "attack", "objective": " baranovichi "},
    ]})
    buckets, _ = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": reply}])
    )
    assert buckets == Counter({"first": 1})


def test_a_blank_objective_string_is_treated_as_none():
    state = load_scenario(DATA_DIR)
    reply = _json.dumps({"orders": [
        {"corps_id": "xxiv_pz", "posture": "defend", "objective": "  "},
    ]})
    buckets, _ = score_transcript(
        _transcript(state, "guderian", attempts=[{"response": reply}])
    )
    assert buckets == Counter({"hold": 1})


def test_a_transcript_with_no_attempts_and_no_orders_scores_nothing():
    # _first_attempt_orders promises None when the raw reply cannot be read at
    # all; the final-orders fallback must honour that instead of raising.
    state = load_scenario(DATA_DIR)
    transcript = _transcript(state, "guderian")
    del transcript["orders"]
    buckets, unscored = score_transcript(transcript)
    assert buckets == Counter()
    assert unscored == 3


def test_a_first_attempt_that_is_not_a_dict_scores_nothing():
    # attempts[0].get(...) raises AttributeError on a bare string, which was
    # outside the caught tuple.
    state = load_scenario(DATA_DIR)
    buckets, unscored = score_transcript(
        _transcript(state, "guderian", attempts=["a bare string, not an attempt"])
    )
    assert buckets == Counter()
    assert unscored == 3


def test_menu_shapes_counts_corps_briefings_by_option_count():
    # `middle` is only reachable on a 3-long menu, and the menu shape is itself
    # an output of model behaviour - so two runs are only comparable if their
    # shape mixes are.
    state = load_scenario(DATA_DIR)
    shapes = menu_shapes([_transcript(state, "guderian")])
    assert shapes == Counter({3: 3})   # all three corps draw two moves plus a hold
    # a second commander's corps join the same mix - it is a per-run tally, not
    # a per-commander one.
    both = menu_shapes([_transcript(state, "guderian"), _transcript(state, "hoth")])
    assert sum(both.values()) == 3 + len(parse_staff_options(build_briefing(state, "hoth")))


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
