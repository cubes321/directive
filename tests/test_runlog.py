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
