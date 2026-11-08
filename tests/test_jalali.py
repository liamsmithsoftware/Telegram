from __future__ import annotations

from datetime import datetime, timezone

import jdatetime
import pytest

from app.utils.jalali import (
    format_local_display,
    parse_filter_date_to_gregorian,
    split_datetime,
)


def test_split_datetime_produces_all_structured_fields():
    dt = datetime(2026, 11, 8, 12, 30, 45, tzinfo=timezone.utc)
    parts = split_datetime(dt, tz_name="Asia/Tehran")

    # Tehran is UTC+3:30 (no DST since 2022)
    assert parts.published_time == "16:00:45"
    assert parts.published_date == "2026-11-08"
    assert parts.published_jalali_date == "1405/08/17"
    assert parts.published_at_utc == "2026-11-08T12:30:45Z"


def test_split_datetime_crosses_midnight_boundary():
    dt = datetime(2026, 11, 8, 21, 0, 0, tzinfo=timezone.utc)
    parts = split_datetime(dt, tz_name="Asia/Tehran")
    assert parts.published_time == "00:30:00"
    assert parts.published_date == "2026-11-09"
    assert parts.published_jalali_date == jdatetime.date.fromgregorian(
        date=datetime(2026, 11, 9)
    ).strftime("%Y/%m/%d")


def test_split_datetime_utc_timezone():
    dt = datetime(2026, 3, 20, 23, 59, 59, tzinfo=timezone.utc)
    parts = split_datetime(dt, tz_name="UTC")
    assert parts.published_date == "2026-03-20"
    assert parts.published_time == "23:59:59"
    assert parts.published_jalali_date == "1404/12/29"


def test_split_datetime_naive_datetime_is_treated_as_utc():
    dt = datetime(2026, 11, 8, 12, 30, 45)
    parts = split_datetime(dt, tz_name="UTC")
    assert parts.published_at_utc == "2026-11-08T12:30:45Z"
    assert parts.published_time == "12:30:45"


@pytest.mark.parametrize(
    "value, expected",
    [
        ("1405/08/17", "2026-11-08"),
        ("1405-08-17", "2026-11-08"),
        ("۱۴۰۵/۰۸/۱۷", "2026-11-08"),
        ("2026-11-08", "2026-11-08"),
        ("2026/11/08", "2026-11-08"),
        ("2026-1-5", "2026-01-05"),
        ("  1405/08/17  ", "2026-11-08"),
    ],
)
def test_parse_filter_date_accepts_jalali_and_gregorian(value: str, expected: str):
    assert parse_filter_date_to_gregorian(value) == expected


@pytest.mark.parametrize("value", [None, "", "   "])
def test_parse_filter_date_empty_returns_none(value):
    assert parse_filter_date_to_gregorian(value) is None


@pytest.mark.parametrize("value", ["abc", "1405/13/40", "2026-02-30", "1405/8", "17/08/1405"])
def test_parse_filter_date_rejects_invalid_formats(value: str):
    with pytest.raises(ValueError):
        parse_filter_date_to_gregorian(value)


def test_format_local_display_uses_jalali_and_time():
    assert format_local_display("2026-11-08T12:30:45Z", tz_name="Asia/Tehran") == "1405/08/17 - 16:00:45"


def test_format_local_display_handles_empty_and_bad_values():
    assert format_local_display(None) is None
    assert format_local_display("") is None
    assert format_local_display("not-a-date") == "not-a-date"
