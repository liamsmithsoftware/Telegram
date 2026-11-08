from __future__ import annotations

import io
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.config import DEFAULT_TIMEZONE, EXPORTS_DIR
from app.database import DatabaseManager
from app.utils.jalali import format_local_display

MEDIA_LABELS_FA = {
    "text": "متن",
    "photo": "تصویر",
    "video": "ویدیو",
    "voice": "صوت",
    "document": "فایل",
    "poll": "نظرسنجی",
}

UNIT_LABELS_FA = {
    "minutes": "دقیقه",
    "hours": "ساعت",
    "days": "روز",
}


def _clean_excel_str(value: Optional[Any]) -> str:
    if value is None:
        return ""
    cleaned = ILLEGAL_CHARACTERS_RE.sub("", str(value))
    # Prevent accidental Excel formula interpretation when post text begins with '=', '+', '-', '@'
    if cleaned.startswith(("=", "+", "-", "@")):
        cleaned = "\u200c" + cleaned
    return cleaned


def _format_interval_fa(val: Any, unit: str) -> str:
    try:
        fval = float(val)
        num_str = str(int(fval)) if fval.is_integer() else str(fval)
    except (TypeError, ValueError):
        num_str = str(val)
    return f"هر {num_str} {UNIT_LABELS_FA.get(unit, unit)}"


def generate_excel_bytes(
    *,
    posts: List[Dict[str, Any]],
    channels: List[Dict[str, Any]],
    tz_name: str = DEFAULT_TIMEZONE,
) -> bytes:
    wb = Workbook()

    # Styles
    header_fill = PatternFill(start_color="0F4C81", end_color="0F4C81", fill_type="solid")
    zebra_fill = PatternFill(start_color="F4F8FB", end_color="F4F8FB", fill_type="solid")
    header_font = Font(name="Tahoma", size=10, bold=True, color="FFFFFF")
    body_font = Font(name="Tahoma", size=10, color="1E293B")
    link_font = Font(name="Tahoma", size=10, color="0284C7", underline="single")

    thin_side = Side(border_style="thin", color="CBD5E1")
    cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    align_center = Alignment(horizontal="center", vertical="center", wrap_text=False)
    align_rtl_wrap = Alignment(horizontal="right", vertical="top", wrap_text=True, readingOrder=2)
    align_ltr = Alignment(horizontal="left", vertical="center", wrap_text=False)

    # ------------------------------------------------------------------
    # Sheet 1: Posts (مطالب کانال‌ها)
    # ------------------------------------------------------------------
    ws = wb.active
    ws.title = "مطالب کانال‌ها"
    ws.views.sheetView[0].rightToLeft = True
    ws.freeze_panes = "A2"

    post_headers = [
        ("ردیف", 8),
        ("عنوان کانال", 24),
        ("شناسه کانال", 18),
        ("شناسه پیام", 13),
        ("آدرس مستقیم مطلب", 34),
        ("تاریخ شمسی", 14),
        ("تاریخ میلادی", 14),
        ("ساعت انتشار", 13),
        ("نوع محتوا", 12),
        ("بازدید", 12),
        ("متن مطلب", 65),
        ("زمان دریافت", 20),
    ]

    ws.row_dimensions[1].height = 28
    for col_idx, (title, width) in enumerate(post_headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=title)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = align_center
        cell.border = cell_border
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    for idx, post in enumerate(posts, start=1):
        row_num = idx + 1
        post_url = str(post.get("post_url") or "")
        media_fa = MEDIA_LABELS_FA.get(str(post.get("media_type") or "text"), str(post.get("media_type") or "متن"))
        fetched_local = format_local_display(post.get("fetched_at"), tz_name=tz_name) or post.get("fetched_at") or ""

        row_values = [
            idx,
            _clean_excel_str(post.get("channel_title")),
            _clean_excel_str(post.get("channel_username")),
            int(post["message_id"]) if post.get("message_id") is not None else "",
            post_url,
            _clean_excel_str(post.get("published_jalali_date")),
            _clean_excel_str(post.get("published_date")),
            _clean_excel_str(post.get("published_time")),
            media_fa,
            int(post["views"]) if post.get("views") is not None else "",
            _clean_excel_str(post.get("content")),
            _clean_excel_str(fetched_local),
        ]

        is_even = idx % 2 == 0
        for col_idx, val in enumerate(row_values, start=1):
            c = ws.cell(row=row_num, column=col_idx, value=val)
            c.font = body_font
            c.border = cell_border
            if is_even:
                c.fill = zebra_fill

            if col_idx == 5 and post_url.startswith("http"):
                c.hyperlink = post_url
                c.font = link_font
                c.alignment = align_ltr
            elif col_idx == 11:
                c.alignment = align_rtl_wrap
            elif col_idx in (2,):
                c.alignment = Alignment(horizontal="right", vertical="center", readingOrder=2)
            elif col_idx == 3:
                c.alignment = align_ltr
            else:
                c.alignment = align_center

    if posts:
        ws.auto_filter.ref = f"A1:L{len(posts) + 1}"

    # ------------------------------------------------------------------
    # Sheet 2: Channels Summary (لیست کانال‌ها)
    # ------------------------------------------------------------------
    ws_ch = wb.create_sheet(title="لیست کانال‌ها")
    ws_ch.views.sheetView[0].rightToLeft = True
    ws_ch.freeze_panes = "A2"

    ch_headers = [
        ("ردیف", 8),
        ("عنوان کانال", 26),
        ("آدرس کانال", 32),
        ("بازه بررسی خودکار", 18),
        ("تعداد دریافت اولیه", 16),
        ("آخرین شناسه پیام", 18),
        ("تعداد مطالب ذخیره‌شده", 20),
        ("وضعیت کانال", 14),
        ("آخرین بررسی", 22),
        ("بررسی بعدی", 22),
    ]

    ws_ch.row_dimensions[1].height = 28
    for col_idx, (title, width) in enumerate(ch_headers, start=1):
        cell = ws_ch.cell(row=1, column=col_idx, value=title)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = align_center
        cell.border = cell_border
        ws_ch.column_dimensions[get_column_letter(col_idx)].width = width

    for idx, ch in enumerate(channels, start=1):
        row_num = idx + 1
        ch_url = str(ch.get("canonical_url") or "")
        status_fa = "فعال" if ch.get("is_active") else "متوقف"
        ch_values = [
            idx,
            _clean_excel_str(ch.get("title")),
            ch_url,
            _format_interval_fa(ch.get("interval_value"), str(ch.get("interval_unit") or "hours")),
            int(ch.get("initial_limit") or 10),
            int(ch["last_message_id"]) if ch.get("last_message_id") is not None else "—",
            int(ch.get("posts_count") or 0),
            status_fa,
            format_local_display(ch.get("last_fetched_at"), tz_name=tz_name) or "—",
            format_local_display(ch.get("next_fetch_at"), tz_name=tz_name) or "—",
        ]
        for col_idx, val in enumerate(ch_values, start=1):
            c = ws_ch.cell(row=row_num, column=col_idx, value=val)
            c.font = body_font
            c.border = cell_border
            if idx % 2 == 0:
                c.fill = zebra_fill
            if col_idx == 3 and ch_url.startswith("http"):
                c.hyperlink = ch_url
                c.font = link_font
                c.alignment = align_ltr
            elif col_idx == 2:
                c.alignment = Alignment(horizontal="right", vertical="center", readingOrder=2)
            else:
                c.alignment = align_center

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def create_sqlite_export_snapshot(
    db: DatabaseManager,
    *,
    filtered_post_ids: Optional[List[int]] = None,
    strip_sensitive_settings: bool = True,
) -> Path:
    """
    Creates an atomic, portable `.sqlite` snapshot file ready for download.
    Removes sensitive API credentials/proxy passwords from exported settings table!
    """
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = EXPORTS_DIR / f"export_{uuid.uuid4().hex}.sqlite"
    db.backup_sqlite_to_file(snapshot_path)

    conn = sqlite3.connect(str(snapshot_path))
    try:
        if strip_sensitive_settings:
            conn.execute(
                """
                DELETE FROM settings
                WHERE key IN ('telethon_api_id', 'telethon_api_hash', 'telethon_phone', 'proxy_username', 'proxy_password')
                """
            )

        if filtered_post_ids is not None:
            if len(filtered_post_ids) == 0:
                conn.execute("DELETE FROM posts")
            else:
                conn.execute("CREATE TEMP TABLE _keep_ids (id INTEGER PRIMARY KEY)")
                conn.executemany(
                    "INSERT INTO _keep_ids (id) VALUES (?)",
                    [(int(pid),) for pid in filtered_post_ids],
                )
                conn.execute("DELETE FROM posts WHERE id NOT IN (SELECT id FROM _keep_ids)")
                conn.execute("DROP TABLE _keep_ids")

        conn.commit()
        conn.execute("VACUUM;")
    finally:
        conn.close()

    return snapshot_path
