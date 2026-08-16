"""Dev tool: staff-option divergence per commander.

Answers "is this model still playing a character, or just taking the staff's
first suggestion every time?" - offline, free, no LLM calls.

  .\\.venv\\Scripts\\python.exe analyze_divergence.py            # newest run
  .\\.venv\\Scripts\\python.exe analyze_divergence.py run-20260816-170643/campaign
"""

import json
import sys
from pathlib import Path

from commanders.divergence import BUCKETS, summarize
from commanders.runlog import resolve_log_dir

log_dir = resolve_log_dir(sys.argv[1] if len(sys.argv) > 1 else None,
                          Path(__file__).parent / "logs")


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


transcripts = [
    json.loads(f.read_text(encoding="utf-8")) for f in sorted(log_dir.glob("turn*.json"))
]
if not transcripts:
    print(f"no commander transcripts in {log_dir}")
    raise SystemExit(0)

rows = summarize(transcripts)
print(f"{log_dir.parent.name}  {models_used(log_dir)}")
header = f"{'commander':12}{'n':>5}  " + "".join(f"{b:>9}" for b in BUCKETS) + f"{'unscored':>10}"
print(header)
for commander in sorted(rows, key=lambda c: (c == "ALL", c)):
    buckets, unscored = rows[commander]
    n = sum(buckets.values())
    cells = "".join(f"{(100 * buckets[b] / n if n else 0):>8.0f}%" for b in BUCKETS)
    print(f"{commander:12}{n:>5}  {cells}{unscored:>10}")
