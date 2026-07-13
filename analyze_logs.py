"""Dev tool: tally LLM transcript outcomes and failure reasons."""

import json
import sys
from collections import Counter
from pathlib import Path

from commanders.runlog import resolve_log_dir

log_dir = resolve_log_dir(sys.argv[1] if len(sys.argv) > 1 else None,
                          Path(__file__).parent / "logs")
outcomes = Counter()
reasons = Counter()
for f in sorted(log_dir.glob("*.json")):
    t = json.loads(f.read_text(encoding="utf-8"))
    outcomes[t["outcome"]] += 1
    if t["outcome"] != "ok":
        # the repair message (last user message) quotes the validation errors
        for m in t["request"]["messages"]:
            if m["role"] == "user" and "rejected by the operations staff" in m["content"]:
                for line in m["content"].splitlines():
                    if line.startswith("- "):
                        # normalize: strip ids/names to group similar errors
                        key = line
                        for marker in ["objective '", "unknown region '", "no order given for "]:
                            if marker in line:
                                key = marker + "..."
                        reasons[key] += 1

print("OUTCOMES:", dict(outcomes))
print("\nFAILURE REASONS (from repair prompts):")
for reason, n in reasons.most_common(15):
    print(f"  {n:3}  {reason}")
