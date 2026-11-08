from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.collectors.manager import SyncManager
from app.services.exporter import (
    create_sqlite_export_snapshot,
    generate_excel_bytes,
)
from app.utils.channel_parser import parse_channel_input
from tests.conftest import FakeTelethonCollector, FakeWebCollector, make_post


async def _seed(db, posts=None, raw="@export_chan", initial_limit=10):
    web = FakeWebCollector()
    web.set_posts(posts or [make_post(1 + i, hours_ago=10 - i) for i in range(5)])
    manager = SyncManager(db=db, web_collector=web, telethon_collector=FakeTelethonCollector())
    channel = db.create_channel(
        parsed=parse_channel_input(raw),
        interval_value=6,
        interval_unit="hours",
        initial_limit=initial_limit,
        title="کانال خروجی",
        is_active=True,
    )
    await manager.sync_channel(int(channel["id"]))
    return int(channel["id"])


async def test_excel_export_is_rtl_and_contains_structured_columns(db):
    await _seed(db)
    posts = db.get_posts_for_export()
    channels = db.list_channels()

    content = generate_excel_bytes(posts=posts, channels=channels, tz_name="Asia/Tehran")
    assert content[:2] == b"PK"  # valid .xlsx (zip) container

    wb = load_workbook(io.BytesIO(content))
    assert wb.sheetnames == ["مطالب کانال‌ها", "لیست کانال‌ها"]
    ws = wb["مطالب کانال‌ها"]
    assert ws.sheet_view.rightToLeft is True

    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    for required in ["آدرس مستقیم مطلب", "تاریخ شمسی", "تاریخ میلادی", "ساعت انتشار", "متن مطلب"]:
        assert required in headers

    url_col = headers.index("آدرس مستقیم مطلب") + 1
    cell = ws.cell(row=2, column=url_col)
    assert cell.value == "https://t.me/test_channel/5"
    assert cell.hyperlink is not None

    # 5 posts + header row
    assert ws.max_row == 6

    channels_ws = wb["لیست کانال‌ها"]
    assert channels_ws.sheet_view.rightToLeft is True
    assert channels_ws.max_row >= 2


async def test_excel_export_sanitizes_formula_injection(db):
    await _seed(db, posts=[make_post(9, text="=HYPERLINK(\"http://evil\")", hours_ago=1)])
    posts = db.get_posts_for_export()
    wb = load_workbook(io.BytesIO(generate_excel_bytes(posts=posts, channels=db.list_channels())))
    ws = wb["مطالب کانال‌ها"]
    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    content_col = headers.index("متن مطلب") + 1
    value = ws.cell(row=2, column=content_col).value
    assert not value.startswith("=")


async def test_excel_export_handles_empty_archive(db):
    content = generate_excel_bytes(posts=[], channels=[], tz_name="Asia/Tehran")
    wb = load_workbook(io.BytesIO(content))
    ws = wb["مطالب کانال‌ها"]
    assert ws.max_row == 1  # headers only


async def test_sqlite_export_snapshot_real_behaviour(db, monkeypatch, tmp_path: Path):
    import app.services.exporter as exporter_module

    monkeypatch.setattr(exporter_module, "EXPORTS_DIR", tmp_path / "snapshots")
    await _seed(db)
    db.update_settings(
        {
            "telethon_api_id": "12345",
            "telethon_api_hash": "supersecret",
            "telethon_phone": "+989120000000",
            "proxy_username": "proxyuser",
            "proxy_password": "proxypass",
            "timezone": "Asia/Tehran",
        }
    )

    snapshot = create_sqlite_export_snapshot(db, filtered_post_ids=None, strip_sensitive_settings=True)
    assert snapshot.exists()
    assert snapshot.suffix == ".sqlite"

    conn = sqlite3.connect(str(snapshot))
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"channels", "posts", "fetch_logs", "settings"}.issubset(tables)

        keys = {r["key"] for r in conn.execute("SELECT key FROM settings")}
        assert "telethon_api_hash" not in keys
        assert "proxy_password" not in keys
        assert "timezone" in keys

        assert conn.execute("SELECT COUNT(*) AS c FROM posts").fetchone()["c"] == 5

        # Exported rows keep the separated date/time/url columns
        row = conn.execute("SELECT * FROM posts ORDER BY message_id DESC LIMIT 1").fetchone()
        assert row["post_url"].startswith("https://t.me/")
        assert row["published_date"] and row["published_jalali_date"] and row["published_time"]
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
    finally:
        conn.close()


async def test_sqlite_export_can_be_filtered_to_selected_posts(db, monkeypatch, tmp_path: Path):
    import app.services.exporter as exporter_module

    monkeypatch.setattr(exporter_module, "EXPORTS_DIR", tmp_path / "snapshots")
    await _seed(db)
    all_posts = db.get_posts_for_export()
    keep = [int(all_posts[0]["id"])]

    snapshot = create_sqlite_export_snapshot(db, filtered_post_ids=keep)
    conn = sqlite3.connect(str(snapshot))
    try:
        rows = conn.execute("SELECT id FROM posts").fetchall()
        assert [r[0] for r in rows] == keep
    finally:
        conn.close()


async def test_sqlite_export_with_empty_filter_deletes_all_posts(db, monkeypatch, tmp_path: Path):
    import app.services.exporter as exporter_module

    monkeypatch.setattr(exporter_module, "EXPORTS_DIR", tmp_path / "snapshots")
    await _seed(db)

    snapshot = create_sqlite_export_snapshot(db, filtered_post_ids=[])
    conn = sqlite3.connect(str(snapshot))
    try:
        assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
        # channels should remain intact so the schema stays meaningful
        assert conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0] == 1
    finally:
        conn.close()
