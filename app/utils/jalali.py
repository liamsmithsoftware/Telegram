from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import jdatetime

from app.utils.channel_parser import normalize_digits


@dataclass(frozen=True)
class SplitDateTime:
    published_at_utc: str
    published_date: str
    published_jalali_date: str
    published_time: str


def get_zoneinfo(tz_name: str = "Asia/Tehran") -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo("UTC")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def format_iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def split_datetime(dt: datetime, tz_name: str = "Asia/Tehran") -> SplitDateTime:
    """
    Convert a datetime into structured fields:
    - published_at_utc: ISO-8601 UTC timestamp (YYYY-MM-DDTHH:MM:SSZ)
    - published_date: Gregorian date in target timezone (YYYY-MM-DD)
    - published_jalali_date: Solar Hijri (Shamsi) date in target timezone (YYYY/MM/DD)
    - published_time: Time in target timezone (HH:MM:SS)
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    dt_utc = dt.astimezone(timezone.utc)
    local_tz = get_zoneinfo(tz_name)
    dt_local = dt_utc.astimezone(local_tz)

    jalali_dt = jdatetime.datetime.fromgregorian(datetime=dt_local)

    return SplitDateTime(
        published_at_utc=dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        published_date=dt_local.strftime("%Y-%m-%d"),
        published_jalali_date=jalali_dt.strftime("%Y/%m/%d"),
        published_time=dt_local.strftime("%H:%M:%S"),
    )


def format_local_display(iso_utc: Optional[str], tz_name: str = "Asia/Tehran") -> Optional[str]:
    if not iso_utc:
        return None
    try:
        cleaned = iso_utc.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        parts = split_datetime(dt, tz_name=tz_name)
        return f"{parts.published_jalali_date} - {parts.published_time}"
    except ValueError:
        return iso_utc


def parse_filter_date_to_gregorian(date_str: Optional[str]) -> Optional[str]:
    """
    Accepts either Gregorian (2026-11-08 / 2026/11/08) or Jalali (1405/08/17 / ۱۴۰۵-۰۸-۱۷)
    and returns standard Gregorian 'YYYY-MM-DD' for SQL filtering.
    """
    if not date_str:
        return None
    cleaned = normalize_digits(date_str.strip()).replace("/", "-")
    if not cleaned:
        return None

    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", cleaned)
    if not m:
        raise ValueError(
            f"فرمت تاریخ «{date_str}» معتبر نیست. لطفاً به صورت ۱۴۰۵/۰۸/۱۷ یا 2026-11-08 وارد کنید."
        )

    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if 1300 <= year <= 1599:
        try:
            greg = jdatetime.date(year, month, day).togregorian()
            return greg.strftime("%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"تاریخ شمسی «{date_str}» معتبر نیست.") from exc
    else:
        try:
            greg = datetime(year, month, day).date()
            return greg.strftime("%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"تاریخ میلادی «{date_str}» معتبر نیست.") from exc
