from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/pull-request-release-safety.yml")
EXPECTED_PYTEST_COMMAND = (
    ".venv/bin/python -m pytest "
    "tests/test_api.py "
    "tests/test_telegram.py "
    "tests/test_telegram_multiloop.py "
    "tests/test_telegram_health_monitor.py "
    "tests/test_reports_scheduler.py "
    "tests/test_trading_loop_daily_reset.py "
    "tests/test_go_live_safety.py "
    "tests/test_live_controller.py "
    "tests/test_shutdown_cleanup.py "
    "-q"
)


def test_pr_release_safety_workflow_exists_and_targets_pull_requests():
    assert WORKFLOW_PATH.exists()

    workflow_text = WORKFLOW_PATH.read_text()

    assert "pull_request:" in workflow_text
    assert "branches:" in workflow_text
    assert "- main" in workflow_text
    assert "release-safety" in workflow_text


def test_pr_release_safety_workflow_runs_expected_pytest_gate():
    workflow_text = WORKFLOW_PATH.read_text()

    assert "actions/setup-python" in workflow_text
    assert 'pip install -e ".[dev]"' in workflow_text
    assert EXPECTED_PYTEST_COMMAND in workflow_text
