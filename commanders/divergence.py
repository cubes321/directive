"""Staff-option divergence: how far a commander's orders sit from what his own
staff suggested.

Turn time and order validity are already instrumented. Both can stay green
while the thing that actually matters rots: a smaller model that regresses to
taking staff option #1 every turn passes every schema check. This scores each
order against the options that corps was offered, so that regression shows up
as a number.

`off-menu` is the metric's strongest positive signal and therefore the bucket
worth defending. It means ONE thing: a legal, reachable objective the staff did
not list. Three impostors were measured leaking into it (44-77% of the bucket
on real logs) and are deliberately kept out:

- **the other move verb.** attack and advance are one order to the engine, so
  "advance to Minsk" against a staff "attack Minsk" is compliance, not
  independence (`_move_class`).
- **the other word for sitting still.** defend and reserve are the same
  inaction, and which one the staff offers depends on the corps's own supply
  (`_HOLD_POSTURES`).
- **an objective out of reach.** That order is rejected and forced to `defend`;
  it is a model failure, already reported by analyze_logs.py, and lands in
  `unscored` (`parse_in_range`).
- **an order the engine would not accept at all** - a move with no objective,
  or a posture outside `POSTURES`. `validate_orders` rejects both
  (`engine/orders.py:85` and `:92`) and `salvage_orders` forces them to
  `defend`. "Advance, objective null" was qwen3.5-4b's dominant first-attempt
  failure shape, and it was the metric's strongest praise (`_engine_would_reject`).

Pure functions only - strings and dicts in, counts out. The file IO lives in
analyze_divergence.py.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable

from engine.orders import POSTURES  # the postures the engine will actually accept

Option = tuple[str, str | None]  # (posture, objective region id)

BUCKETS = ("first", "middle", "hold", "off-menu")
UNSCORED = "unscored"  # not a bucket: "this order told us nothing"

# defend and reserve are the same physical inaction - they differ only in how
# much a corps recovers (engine/turn.py:268) - and which of the two the staff
# offers is a pure function of the corps's own supply/organization
# (commanders/briefing.py:110), not of the commander's independence.
_HOLD_POSTURES = ("defend", "reserve")

_CORPS_HEADER = re.compile(r"^For .+ \[([a-z0-9_]+)\]:$")
_OPTION_LINE = re.compile(r"^  \* (.+)$")
_IN_RANGE_LINE = re.compile(r"^  In range this week: (.*)$")
_REGION_ID = re.compile(r"\[id: ([a-z0-9_]+)\]")

# Prefix -> posture, mirroring commanders/briefing.py:_staff_options. "close up
# toward the front" is a move like any other, so it reads as an advance.
_MOVE_PREFIXES = (
    ("attack ", "attack"),
    ("advance to ", "advance"),
    ("close up toward the front at ", "advance"),
)


def _region_of(text: str) -> str:
    match = _REGION_ID.search(text)
    if match is None:
        raise ValueError(f"staff option names no region: {text!r}")
    return match.group(1)


def _option_from_text(text: str) -> Option:
    for prefix, posture in _MOVE_PREFIXES:
        if text.startswith(prefix):
            return (posture, _region_of(text))
    if text.startswith("hold in reserve"):
        return ("reserve", None)
    if text.startswith("hold current position"):
        return ("defend", None)
    raise ValueError(f"unrecognized staff option: {text!r}")


def _corps_blocks(briefing: str) -> list[tuple[str, list[str]]]:
    """(corps id, the lines of its block) for each corps under STAFF OPTIONS."""
    if "STAFF OPTIONS" not in briefing:
        return []
    blocks: list[tuple[str, list[str]]] = []
    for line in briefing.split("STAFF OPTIONS", 1)[1].splitlines():
        header = _CORPS_HEADER.match(line)
        if header:
            blocks.append((header.group(1), []))
        elif blocks:
            blocks[-1][1].append(line)
    return blocks


def parse_staff_options(briefing: str) -> dict[str, list[Option]]:
    """corps id -> the options it was offered, in the order the briefing gave
    them. Empty when the briefing has no STAFF OPTIONS section."""
    options: dict[str, list[Option]] = {}
    for corps_id, lines in _corps_blocks(briefing):
        options[corps_id] = [
            _option_from_text(entry.group(1))
            for entry in (_OPTION_LINE.match(line) for line in lines)
            if entry
        ]
    return options


def parse_in_range(briefing: str) -> dict[str, set[str]]:
    """corps id -> the region ids it may legally be sent to this week.

    Each corps block ends with "In range this week: ...", which is the legal
    destination set `validate_orders` will enforce. Ids come from the
    `[id: ...]` markers, so the "(FULL - no room)" annotation is ignored: a
    full region is still a legal objective, the move merely bounces.

    A corps whose block carries no such line is *absent* from the result - that
    is "we cannot tell", not "nothing is legal", and must not void its orders.
    """
    ranges: dict[str, set[str]] = {}
    for corps_id, lines in _corps_blocks(briefing):
        for line in lines:
            match = _IN_RANGE_LINE.match(line)
            if match:
                ranges[corps_id] = set(_REGION_ID.findall(match.group(1)))
                break
    return ranges


def _move_class(posture: str) -> str:
    """attack and advance are ONE order to the engine: engine/turn.py:138 is the
    only place either posture is read, and it reads them jointly. Scoring them
    apart let a model that always took staff option #1 while writing the other
    verb read as 100% off-menu - the metric defeated by the collapse it exists
    to detect."""
    return "move" if posture in ("attack", "advance") else posture


def _objective_of(order: dict) -> str | None:
    """The order's objective, normalized exactly as the engine normalizes it
    (`engine/orders.py:_corps_order_from_dict`): stray whitespace stripped and
    a blank string read as None. Comparing raw strings here would penalise
    qwen3.5-4b for the very quirk the engine already absorbs."""
    objective = order.get("objective")
    if isinstance(objective, str):
        return objective.strip() or None
    return objective


def _engine_would_reject(posture, objective: str | None) -> bool:
    """Orders `validate_orders` refuses outright, whatever the staff offered.

    Both shapes match no staff option (the staff only ever proposes a legal
    posture, and every move option it proposes names a region), so both used to
    fall through to `off-menu` - the bucket meaning "a legal, reachable
    objective the staff did not list". They are neither legal nor an objective:
    salvage_orders replaces them with `defend`. "Advance, objective null" was
    qwen3.5-4b's most common first-attempt failure and made up 37% of that
    run's off-menu bucket.
    """
    if posture not in POSTURES:                     # engine/orders.py:84
        return True
    return _move_class(posture) == "move" and objective is None   # engine/orders.py:92


def bucket_for(order: dict, options: list[Option], in_range: set[str] | None = None) -> str:
    """Which bucket this order falls in, given the options that corps was
    offered and (optionally) the regions it can legally reach. See BUCKETS;
    may also return UNSCORED.

    A one-entry list holding only the hold option makes index 0 both first and
    last; 'hold' wins, because taking the only offered option when that option
    is inaction is not a sign of a commander thinking for himself.

    `off-menu` means one thing only: a legal, reachable objective the staff did
    not list. Everything below exists to keep the impostors out of it - see the
    module docstring.
    """
    posture = order.get("posture")
    objective = _objective_of(order)
    # Checked before anything else, and before the range test in particular: a
    # move with no objective is illegal on its own, whether or not the briefing
    # told us what was in range.
    if _engine_would_reject(posture, objective):
        return UNSCORED
    # Inaction is inaction, whichever word the order used and whatever stray
    # objective it carried (the engine reads `objective` only for attack and
    # advance). Observed: sov_13a, sitting in Minsk, ordered "defend / minsk".
    if posture in _HOLD_POSTURES and options and options[-1][0] in _HOLD_POSTURES:
        return "hold"
    chosen = (_move_class(posture), objective)
    for index, option in enumerate(options):
        if (_move_class(option[0]), option[1]) != chosen:
            continue
        if index == len(options) - 1 and option[0] in _HOLD_POSTURES:
            return "hold"
        return "first" if index == 0 else "middle"
    if in_range is not None and objective is not None and objective not in in_range:
        # Not independence but a model failure: validate_orders rejects an
        # unreachable objective and salvage_orders forces it to 'defend'. Order
        # validity is analyze_logs.py's beat; here it says nothing about
        # character. (An offered option is never re-checked - the staff only
        # ever proposes regions it has already confirmed are in reach.)
        return UNSCORED
    return "off-menu"


def _first_attempt_orders(transcript: dict) -> list[dict] | None:
    """The orders the MODEL chose, before the engine touched them.

    salvage_orders forces illegal orders to 'defend', so scoring the validated
    set would count an engine repair as the model going passive. Returns None
    when the raw reply cannot be read at all.
    """
    attempts = transcript.get("attempts")
    if not attempts:
        # "Cannot be read at all" covers the fallback too: a transcript with
        # neither attempts nor a usable final order list tells us nothing.
        try:
            return list(transcript["orders"]["orders"])
        except (ValueError, TypeError, KeyError, AttributeError):
            return None
    try:
        # attempts[0] need not be a dict - a hand-edited or truncated log can
        # put a bare string there, and .get would raise AttributeError.
        return list(json.loads(attempts[0].get("response") or "")["orders"])
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def _briefing_of(transcript: dict) -> str:
    """The original briefing - never the repair message, which quotes
    validation errors rather than options."""
    return next(
        (m["content"] for m in transcript["request"]["messages"] if m["role"] == "user"),
        "",
    )


def score_transcript(transcript: dict) -> tuple[Counter, int]:
    """(bucket counts, unscored) for one commander-turn."""
    briefing = _briefing_of(transcript)
    options = parse_staff_options(briefing)
    ranges = parse_in_range(briefing)
    orders = _first_attempt_orders(transcript)
    if orders is None:
        # We cannot know what he chose, but we know how many corps he held.
        return Counter(), len(options)
    buckets: Counter = Counter()
    unscored = 0
    seen: set[str] = set()
    for order in orders:
        # A backend that doesn't strictly enforce the schema can hand back an
        # entry that isn't even a dict (e.g. "orders" decoded to an object,
        # and list(dict) yielded its keys as bare strings). That is a model
        # failure to surface, not a crash.
        if not isinstance(order, dict):
            unscored += 1
            continue
        # "corps" is kimi-k2.6's name for the key; the engine reads it too
        corps_id = order.get("corps_id", order.get("corps"))
        if isinstance(corps_id, str):
            corps_id = corps_id.strip()   # as engine/orders.py does; see _objective_of
        corps_options = options.get(corps_id)
        if not corps_options:
            unscored += 1
            continue
        # Mark the corps covered even if this particular order turns out to
        # be malformed below - it did receive an order, just not a usable
        # one, and that must not also count it as briefed-but-silent.
        seen.add(corps_id)
        if "posture" not in order:
            unscored += 1
            continue
        bucket = bucket_for(order, corps_options, ranges.get(corps_id))
        if bucket == UNSCORED:
            unscored += 1
        else:
            buckets[bucket] += 1
    # A corps that was briefed but never received any order (valid or
    # malformed) must not vanish from the denominator - a duplicate order
    # for one corps is deduplicated by `seen`, so it can't paper over
    # another corps that got nothing.
    unscored += sum(1 for corps_id in options if corps_id not in seen)
    return buckets, unscored


def menu_shapes(transcripts: Iterable[dict]) -> Counter:
    """options offered -> how many corps-briefings offered exactly that many.

    The menu shape is endogenous and it drives the aggregate: `middle` is only
    reachable on a three-long menu, and a model that advances reaches contact
    and *earns* three-long attack menus while a passive one keeps drawing
    two-long ones. Two runs are only comparable if their shape mixes are, so
    the mix is reported alongside the table.
    """
    shapes: Counter = Counter()
    for transcript in transcripts:
        for options in parse_staff_options(_briefing_of(transcript)).values():
            shapes[len(options)] += 1
    return shapes


def summarize(transcripts: Iterable[dict]) -> dict[str, tuple[Counter, int]]:
    """commander id -> (bucket counts, unscored), plus the total under "ALL"."""
    rows: dict[str, tuple[Counter, int]] = {}
    total: Counter = Counter()
    total_unscored = 0
    for transcript in transcripts:
        commander = transcript["commander"]
        buckets, unscored = score_transcript(transcript)
        prior, prior_unscored = rows.get(commander, (Counter(), 0))
        rows[commander] = (prior + buckets, prior_unscored + unscored)
        total += buckets
        total_unscored += unscored
    rows["ALL"] = (total, total_unscored)
    return rows
