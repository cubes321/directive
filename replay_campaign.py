"""Dev tool: replay a recorded campaign's orders against the current rules.

The point is tuning. The scripted policy is a weak stand-in for real play - over
a full campaign it never lunges, never counterattacks and takes about a quarter
of the combat damage an LLM game does - so a rules change can look fine on the
scripted trace and be a rout in play. This asks the sharper question: holding
every command decision fixed, how would a real recorded game have gone?

Usage:
  python replay_campaign.py [run-20260802-134115] [--turns 24]

With no argument it replays the newest run. Watch the salvaged column: once it
climbs, the replay has drifted from the game it is reproducing and the later
numbers are indicative rather than exact.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from commanders.replay import load_recorded_orders, replay
from commanders.runlog import latest_run_dir
from engine.scenario import load_scenario
from engine.victory import check_victory

ROOT = Path(__file__).parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", nargs="?", default=None, help="run dir name under logs/")
    parser.add_argument("--turns", type=int, default=None)
    args = parser.parse_args()

    logs = ROOT / "logs"
    run_dir = (logs / args.run) if args.run else latest_run_dir(logs)
    if run_dir is None or not (run_dir / "campaign").is_dir():
        raise SystemExit(f"no recorded campaign found in {run_dir}")

    recorded = load_recorded_orders(run_dir / "campaign")
    if not recorded:
        raise SystemExit(f"{run_dir} has no usable order records")

    state = load_scenario(ROOT / "data")
    print(f"replaying {run_dir.name}: {len(recorded)} recorded turns\n")
    print(f"{'turn':<6}{'axis':>7}{'soviet':>8}{'salv':>6}{'moscow':>9}{'held':>6}"
          f"{'ceil':>6}  battles")

    result = replay(state, recorded, turns=args.turns)
    for row in result.history:
        print(f" T{row['turn']:<5}{row['axis']:>7}{row['soviet']:>8}{row['salvaged']:>6}"
              f"{str(row['moscow']):>9}{row['moscow_held_turns']:>6}"
              f"{row['min_ceiling']:>6}  {row['combats']}")

    verdict = check_victory(state)
    print(f"\nfidelity: {result.fidelity:.0%} of commander-turns replayed as recorded")
    print(f"verdict : {verdict['reason'] if verdict else 'campaign unresolved'}")


if __name__ == "__main__":
    main()
