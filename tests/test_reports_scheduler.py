from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from scheduler.reports import (
    ReportSchedulerState,
    load_report_state,
    run_due_reports,
    save_report_state,
    should_run_daily,
    should_run_weekly,
)


def test_should_run_daily_once_per_date():
    now = datetime(2026, 6, 17, 0, 5, tzinfo=timezone.utc)
    assert should_run_daily(now, last_date=None) is True
    assert should_run_daily(now, last_date="2026-06-17") is False


def test_should_run_weekly_once_per_iso_week():
    now = datetime(2026, 6, 17, 0, 5, tzinfo=timezone.utc)
    week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    assert should_run_weekly(now, last_week=None) is True
    assert should_run_weekly(now, last_week=week) is False


def test_load_report_state_seeds_current_period_when_missing(tmp_path):
    now = datetime(2026, 6, 17, 0, 5, tzinfo=timezone.utc)

    state = load_report_state(tmp_path / "missing.json", now=now)

    assert state.last_daily == "2026-06-17"
    assert state.last_weekly == "2026-W25"


def test_save_and_load_report_state(tmp_path):
    path = tmp_path / "reports.json"
    save_report_state(path, ReportSchedulerState(last_daily="2026-06-16", last_weekly="2026-W24"))

    state = load_report_state(path, now=datetime(2026, 6, 17, tzinfo=timezone.utc))

    assert state == ReportSchedulerState(last_daily="2026-06-16", last_weekly="2026-W24")


@pytest.mark.asyncio
async def test_run_due_reports_sends_daily_and_weekly_once():
    now = datetime(2026, 6, 17, 0, 5, tzinfo=timezone.utc)
    notifier = AsyncMock()
    repo = object()

    state = await run_due_reports(
        notifier=notifier,
        repo=repo,
        now=now,
        last_daily=None,
        last_weekly=None,
    )

    notifier.send_daily_summary.assert_awaited_once_with(repo, day="2026-06-17")
    notifier.send_weekly_summary.assert_awaited_once_with(repo)
    assert state.last_daily == "2026-06-17"
    assert state.last_weekly == "2026-W25"


@pytest.mark.asyncio
async def test_run_due_reports_skips_already_sent_periods():
    now = datetime(2026, 6, 17, 0, 5, tzinfo=timezone.utc)
    notifier = AsyncMock()

    await run_due_reports(
        notifier=notifier,
        repo=object(),
        now=now,
        last_daily="2026-06-17",
        last_weekly="2026-W25",
    )

    notifier.send_daily_summary.assert_not_called()
    notifier.send_weekly_summary.assert_not_called()


@pytest.mark.asyncio
async def test_run_due_reports_respects_report_enabled_flags():
    now = datetime(2026, 6, 17, 0, 5, tzinfo=timezone.utc)
    notifier = AsyncMock()

    state = await run_due_reports(
        notifier=notifier,
        repo=object(),
        now=now,
        last_daily=None,
        last_weekly=None,
        daily_enabled=False,
        weekly_enabled=False,
    )

    notifier.send_daily_summary.assert_not_called()
    notifier.send_weekly_summary.assert_not_called()
    assert state.last_daily is None
    assert state.last_weekly is None
