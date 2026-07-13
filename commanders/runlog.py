"""Per-run log directories.

Each server session that starts or loads a campaign gets its own
``logs/run-<timestamp>/`` directory (holding ``campaign/`` transcripts +
``tokens.jsonl`` and ``turns/`` telemetry), so separate playthroughs no longer
intermix in one flat folder. The newest ``run-*`` directory is the current run.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

RUN_PREFIX = "run-"


def new_run_dir(logs_root: Path) -> Path:
    """A fresh run directory named for the current time (sorts chronologically)."""
    return Path(logs_root) / f"{RUN_PREFIX}{datetime.now():%Y%m%d-%H%M%S}"


def latest_run_dir(logs_root: Path) -> Path | None:
    """The most recent run directory under ``logs_root``, or None if there are
    none (e.g. a fresh checkout, or logs predating per-run scoping)."""
    runs = sorted(Path(logs_root).glob(f"{RUN_PREFIX}*"))
    return runs[-1] if runs else None


def resolve_log_dir(arg: str | None, logs_root: Path) -> Path:
    """Where an analysis tool should read transcripts from:
    - an explicit ``arg`` -> ``logs_root/arg`` (e.g. "eval_guderian" or a
      specific "run-XXXX/campaign"),
    - otherwise the latest run's ``campaign`` dir, falling back to the legacy
      flat ``logs_root/campaign`` for logs predating per-run scoping."""
    logs_root = Path(logs_root)
    if arg:
        return logs_root / arg
    latest = latest_run_dir(logs_root)
    return (latest / "campaign") if latest else logs_root / "campaign"
