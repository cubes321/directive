"""Dev tool: per-commander outcome breakdown and empty-response detection."""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from commanders.runlog import resolve_log_dir

log_dir = resolve_log_dir(sys.argv[1] if len(sys.argv) > 1 else None,
                          Path(__file__).parent / "logs")

per_cmd = defaultdict(Counter)
empty_per_cmd = Counter()
nonempty_lengths = []

for f in sorted(log_dir.glob("*.json")):
    t = json.loads(f.read_text(encoding="utf-8"))
    cmd = t["commander"]
    per_cmd[cmd][t["outcome"]] += 1
    for attempt in t["attempts"]:
        resp = attempt["response"]
        if resp.strip() == "":
            empty_per_cmd[cmd] += 1
        else:
            nonempty_lengths.append(len(resp))

print("PER-COMMANDER OUTCOMES:")
for cmd in sorted(per_cmd):
    c = per_cmd[cmd]
    total = sum(c.values())
    ok = c.get("ok", 0) + c.get("repaired", 0) + c.get("salvaged", 0)
    print(f"  {cmd:12} {dict(c)}  ({ok}/{total} usable)")

print("\nEMPTY RESPONSES (the 'char 0' failures) per commander:")
for cmd, n in empty_per_cmd.most_common():
    print(f"  {cmd:12} {n}")

if nonempty_lengths:
    nonempty_lengths.sort()
    print(f"\nNon-empty response chars: min {nonempty_lengths[0]}, "
          f"median {nonempty_lengths[len(nonempty_lengths)//2]}, max {nonempty_lengths[-1]}")
