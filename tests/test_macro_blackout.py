from datetime import datetime, timezone

from core.macro_blackout import in_blackout, load_blackout


def _window(start: str, end: str):
    return (datetime.fromisoformat(start), datetime.fromisoformat(end))


def test_in_blackout_returns_true_when_now_inside_window():
    windows = [
        _window("2026-06-20T12:00:00+00:00", "2026-06-20T14:00:00+00:00"),
    ]

    assert in_blackout(windows, datetime(2026, 6, 20, 13, 0, tzinfo=timezone.utc)) is True


def test_in_blackout_returns_false_when_now_outside_all_windows():
    windows = [
        _window("2026-06-20T12:00:00+00:00", "2026-06-20T14:00:00+00:00"),
    ]

    assert in_blackout(windows, datetime(2026, 6, 20, 15, 0, tzinfo=timezone.utc)) is False


def test_load_blackout_returns_empty_list_when_file_missing(tmp_path):
    missing_path = tmp_path / "missing-blackout.json"

    assert load_blackout(str(missing_path)) == []
