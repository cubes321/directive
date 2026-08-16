"""Staff-option divergence: how far a commander's orders sit from what his own
staff suggested.

Turn time and order validity are already instrumented. Both can stay green
while the thing that actually matters rots: a smaller model that regresses to
taking staff option #1 every turn passes every schema check. This scores each
order against the options that corps was offered, so that regression shows up
as a number.

Pure functions only - strings and dicts in, counts out. The file IO lives in
analyze_divergence.py.
"""

from __future__ import annotations

import re

Option = tuple[str, str | None]  # (posture, objective region id)

BUCKETS = ("first", "middle", "hold", "off-menu")

_CORPS_HEADER = re.compile(r"^For .+ \[([a-z0-9_]+)\]:$")
_OPTION_LINE = re.compile(r"^  \* (.+)$")
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


def parse_staff_options(briefing: str) -> dict[str, list[Option]]:
    """corps id -> the options it was offered, in the order the briefing gave
    them. Empty when the briefing has no STAFF OPTIONS section."""
    if "STAFF OPTIONS" not in briefing:
        return {}
    options: dict[str, list[Option]] = {}
    current: str | None = None
    for line in briefing.split("STAFF OPTIONS", 1)[1].splitlines():
        header = _CORPS_HEADER.match(line)
        if header:
            current = header.group(1)
            options[current] = []
            continue
        entry = _OPTION_LINE.match(line)
        if entry and current is not None:
            options[current].append(_option_from_text(entry.group(1)))
    return options


def bucket_for(order: dict, options: list[Option]) -> str:
    """Which bucket this order falls in, given the options that corps was
    offered. See BUCKETS.

    A one-entry list holding only the hold option makes index 0 both first and
    last; 'hold' wins, because taking the only offered option when that option
    is inaction is not a sign of a commander thinking for himself.
    """
    chosen = (order["posture"], order.get("objective"))
    if chosen not in options:
        return "off-menu"
    index = options.index(chosen)
    if index == len(options) - 1 and chosen[0] in ("defend", "reserve"):
        return "hold"
    return "first" if index == 0 else "middle"
