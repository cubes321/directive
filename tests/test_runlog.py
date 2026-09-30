from commanders.runlog import latest_run_dir, new_run_dir, resolve_log_dir


def test_new_run_dir_is_under_root_and_prefixed(tmp_path):
    d = new_run_dir(tmp_path)
    assert d.parent == tmp_path
    assert d.name.startswith("run-")


def test_latest_run_dir_none_when_empty(tmp_path):
    assert latest_run_dir(tmp_path) is None


def test_latest_run_dir_returns_the_newest(tmp_path):
    # names are timestamp-based and sort chronologically
    (tmp_path / "run-20250101-000000").mkdir()
    (tmp_path / "run-20250601-120000").mkdir()
    newest = tmp_path / "run-20260101-090000"
    newest.mkdir()
    assert latest_run_dir(tmp_path) == newest


def test_resolve_log_dir_explicit_arg_wins(tmp_path):
    assert resolve_log_dir("eval_guderian", tmp_path) == tmp_path / "eval_guderian"


def test_resolve_log_dir_defaults_to_latest_run_campaign(tmp_path):
    (tmp_path / "run-20260101-090000").mkdir()
    assert resolve_log_dir(None, tmp_path) == tmp_path / "run-20260101-090000" / "campaign"


def test_resolve_log_dir_falls_back_to_legacy_flat_dir(tmp_path):
    assert resolve_log_dir(None, tmp_path) == tmp_path / "campaign"  # no run dirs yet


def test_resolve_log_dir_descends_into_a_named_runs_campaign_dir(tmp_path):
    # The transcripts live in run-*/campaign/; naming the run itself used to
    # glob the run dir, find nothing and report an empty tally.
    run = tmp_path / "run-20260930-064509"
    (run / "campaign").mkdir(parents=True)
    assert resolve_log_dir("run-20260930-064509", tmp_path) == run / "campaign"


def test_resolve_log_dir_takes_an_existing_path_as_given(tmp_path, monkeypatch):
    # "logs/run-X/campaign" from the repo root used to become logs/logs/...
    (tmp_path / "logs" / "run-1" / "campaign").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    got = resolve_log_dir("logs/run-1/campaign", tmp_path / "logs")
    assert got.resolve() == (tmp_path / "logs" / "run-1" / "campaign").resolve()


def test_analysis_scripts_fail_loudly_on_a_dir_with_no_transcripts(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).parent.parent
    for script in ("analyze_logs.py", "analyze_failures.py"):
        done = subprocess.run(
            [sys.executable, str(root / script), str(tmp_path / "missing")],
            capture_output=True, text=True, cwd=root,
        )
        assert done.returncode != 0, script
        assert "no commander transcripts" in done.stderr, (script, done.stderr)
