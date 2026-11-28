"""Quiet hours push a reminder to their end, in the workspace's timezone (roadmap 7.1)."""

import datetime as dt

import pytest

from app.modules.conversations.reminders import outside_quiet_hours

JAKARTA = dt.timezone(dt.timedelta(hours=7))
NIGHT = {"start": "22:00", "end": "06:00"}
LUNCH = {"start": "12:00", "end": "13:00"}


def _at(day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 11, day, hour, minute, tzinfo=JAKARTA)


@pytest.mark.parametrize(
    ("quiet", "at", "expected"),
    [
        (None, _at(28, 23), _at(28, 23)),
        (NIGHT, _at(28, 12), _at(28, 12)),
        (NIGHT, _at(28, 23), _at(29, 6)),  # before midnight: the next morning
        (NIGHT, _at(29, 3), _at(29, 6)),  # after midnight: the same morning
        (NIGHT, _at(29, 6), _at(29, 6)),  # the end itself is allowed
        (NIGHT, _at(28, 22), _at(29, 6)),  # the start is quiet
        (LUNCH, _at(28, 12, 30), _at(28, 13)),
        (LUNCH, _at(28, 13, 1), _at(28, 13, 1)),
    ],
)
def test_outside_quiet_hours(
    quiet: dict[str, str] | None, at: dt.datetime, expected: dt.datetime
) -> None:
    assert outside_quiet_hours(at, "Asia/Jakarta", quiet) == expected
