import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ReportSchedulerState:
    last_daily: str | None = None
    last_weekly: str | None = None


def should_run_daily(now: datetime, last_date: str | None) -> bool:
    return now.date().isoformat() != last_date


def _week_key(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def should_run_weekly(now: datetime, last_week: str | None) -> bool:
    return _week_key(now) != last_week


def _env_enabled(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


async def run_due_reports(
    *,
    notifier,
    repo,
    now: datetime,
    last_daily: str | None,
    last_weekly: str | None,
    daily_enabled: bool = True,
    weekly_enabled: bool = True,
) -> ReportSchedulerState:
    next_daily = last_daily
    next_weekly = last_weekly
    if daily_enabled and should_run_daily(now, last_daily):
        if notifier is not None:
            await notifier.send_daily_summary(repo, day=now.date().isoformat())
        next_daily = now.date().isoformat()
    if weekly_enabled and should_run_weekly(now, last_weekly):
        if notifier is not None and hasattr(notifier, "send_weekly_summary"):
            await notifier.send_weekly_summary(repo)
        next_weekly = _week_key(now)
    return ReportSchedulerState(last_daily=next_daily, last_weekly=next_weekly)


async def run_report_scheduler(*, notifier, repo, interval_seconds: int = 60) -> None:
    state = ReportSchedulerState()
    while True:
        now = datetime.now(timezone.utc)
        try:
            state = await run_due_reports(
                notifier=notifier,
                repo=repo,
                now=now,
                last_daily=state.last_daily,
                last_weekly=state.last_weekly,
                daily_enabled=_env_enabled("DAILY_REPORT_ENABLED", True),
                weekly_enabled=_env_enabled("WEEKLY_REPORT_ENABLED", True),
            )
        except Exception as exc:
            if notifier is not None:
                await notifier.send(f"Scheduler report failure: {exc}")
        await asyncio.sleep(interval_seconds)
