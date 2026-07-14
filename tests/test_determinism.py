"""The engine must be fully deterministic: the same game seed yields the same
result regardless of the interpreter's string-hash randomization. The railhead
bug (a set iterated in hash order) is the reason this guard exists - here we
hash the ENTIRE opening-turn state, so the next such bug anywhere is caught."""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def _opening_state_hash(hashseed: int) -> str:
    code = (
        "import json, hashlib; from pathlib import Path; import asyncio;"
        "from commanders.campaign import Campaign;"
        "c = Campaign.new(Path('data'));"
        "asyncio.run(c.play_turn({}));"
        "blob = json.dumps(c.state.to_dict(), sort_keys=True, default=str);"
        "print(hashlib.sha256(blob.encode()).hexdigest())"
    )
    env = {**os.environ, "PYTHONHASHSEED": str(hashseed)}
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env, cwd=REPO_ROOT,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip().splitlines()[-1]


def test_opening_turn_is_identical_across_hash_seeds():
    hashes = {_opening_state_hash(s) for s in (1, 2, 6)}
    assert len(hashes) == 1, f"opening-turn state diverged across hash seeds: {hashes}"
