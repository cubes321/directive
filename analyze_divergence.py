"""Dev tool: staff-option divergence per commander.

Answers "is this model still playing a character, or just taking the staff's
first suggestion every time?" - offline, free, no LLM calls.

  .\\.venv\\Scripts\\python.exe analyze_divergence.py            # newest run
  .\\.venv\\Scripts\\python.exe analyze_divergence.py run-20260816-170643/campaign

The scoring lives in commanders/divergence.py; this file is the IO shell, so
`main` takes its argv and logs root as arguments and returns an exit code.
"""

import json
import sys
from collections import Counter
from pathlib import Path

from commanders.divergence import BUCKETS, menu_shapes, summarize
from commanders.runlog import resolve_log_dir

LOGS_ROOT = Path(__file__).parent / "logs"


def models_used(directory: Path) -> str:
    tokens = directory / "tokens.jsonl"
    if not tokens.exists():
        return "unknown model"
    names = {
        json.loads(line)["model"]
        for line in tokens.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    return ", ".join(sorted(names)) or "unknown model"   # sorted: determinism


def menu_shape_line(shapes: Counter) -> str:
    """The menu-shape mix, so a reader can tell whether two runs are comparable.

    `middle` is only reachable on a three-option menu, and the shape is itself
    an output of model behaviour - an advancing model reaches contact and earns
    three-long attack menus - so the comparison is partly circular without it.
    """
    mix = ", ".join(
        f"{length} option{'' if length == 1 else 's'}: {shapes[length]}"
        for length in sorted(shapes)
    )
    return f"menu shape ({sum(shapes.values())} corps-briefings) {mix or 'none'}"


def main(argv: list[str], logs_root: Path = LOGS_ROOT) -> int:
    log_dir = resolve_log_dir(argv[0] if argv else None, logs_root)
    transcripts = [
        json.loads(f.read_text(encoding="utf-8")) for f in sorted(log_dir.glob("turn*.json"))
    ]
    if not transcripts:
        print(f"no commander transcripts in {log_dir}")
        return 0

    rows = summarize(transcripts)
    print(f"{log_dir.parent.name}  {models_used(log_dir)}")
    print(menu_shape_line(menu_shapes(transcripts)))
    header = (
        f"{'commander':12}{'n':>5}  " + "".join(f"{b:>9}" for b in BUCKETS) + f"{'unscored':>10}"
    )
    print(header)
    for commander in sorted(rows, key=lambda c: (c == "ALL", c)):
        buckets, unscored = rows[commander]
        n = sum(buckets.values())
        cells = "".join(f"{(100 * buckets[b] / n if n else 0):>8.0f}%" for b in BUCKETS)
        print(f"{commander:12}{n:>5}  {cells}{unscored:>10}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
