from __future__ import annotations

import io
import sqlite3

import pytest
from openpyxl import load_workbook

from tests.conftest import make_post


def test_healthz_and_root_page(app_client):
    health = app_client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    page = app_client.get("/")
    assert page.status_code == 200
    assert "dir=\"rtl\"" in page.text
    assert "آرشیو هوشمند کانال‌های تلگرام" in page.text
    # No external CDN/font dependency so it works fully offline
    assert "cdn" not in page.text.lower()
    assert "fonts.googleapis" not in page.text.lower()


def test_static_assets_are_served(app_client):
    css = app_client.get("/static/css/style.css")
    assert css.status_code == 200
    assert "direction: rtl" in css.text

    js = app_client.get("/static/js/app.js")
    assert js.status_code == 200
    assert "/api/overview" in js.text


def test_overview_starts_empty(app_client):
    data = app_client.get("/api/overview").json()
    assert data["stats"]["total_channels"] == 0
    assert data["stats"]["total_posts"] == 0
    assert data["scheduler"]["running"] is False  # scheduler disabled in tests
    assert data["collector_mode"] == "auto"
    assert data["telethon"]["authorized"] is False


def test_create_channel_triggers_initial_ten_posts(app_client, fake_web):
    fake_web.set_posts([make_post(1 + i, hours_ago=40 - i) for i in range(25)])

    res = app_client.post(
        "/api/channels",
        json={
            "channel_input": "https://t.me/s/Fresh_Channel",
            "interval_value": 3,
            "interval_unit": "hours",
            "initial_limit": 10,
            "fetch_now": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    channel = body["channel"]
    assert channel["username"] == "Fresh_Channel"
    assert channel["interval_minutes"] == 180
    assert channel["is_active"] is True
    assert channel["last_message_id"] == 25
    assert channel["posts_count"] == 10
    assert body["sync_result"]["new_saved_count"] == 10
    assert channel["last_fetched_display"] is not None
    assert channel["next_fetch_display"] is not None


def test_create_channel_validation_errors(app_client):
    bad = app_client.post(
        "/api/channels",
        json={"channel_input": "https://example.com/not-telegram", "interval_value": 6, "interval_unit": "hours"},
    )
    assert bad.status_code == 400

    bad_interval = app_client.post(
        "/api/channels",
        json={"channel_input": "@valid_channel", "interval_value": 0, "interval_unit": "hours"},
    )
    assert bad_interval.status_code == 422  # pydantic gt=0


def test_duplicate_channel_is_rejected(app_client, fake_web):
    fake_web.set_posts([make_post(1, hours_ago=1)])
    payload = {"channel_input": "@dup_channel", "interval_value": 6, "interval_unit": "hours", "fetch_now": False}
    assert app_client.post("/api/channels", json=payload).status_code == 200
    second = app_client.post("/api/channels", json={**payload, "channel_input": "https://t.me/dup_channel"})
    assert second.status_code == 400
    assert "قبلاً" in second.json()["detail"]


def test_update_toggle_and_delete_channel(app_client, fake_web):
    fake_web.set_posts([make_post(1, hours_ago=1)])
    created = app_client.post(
        "/api/channels",
        json={"channel_input": "@edit_me", "interval_value": 6, "interval_unit": "hours", "fetch_now": False},
    ).json()["channel"]
    ch_id = created["id"]

    updated = app_client.put(
        f"/api/channels/{ch_id}",
        json={"title": "عنوان جدید", "interval_value": 2, "interval_unit": "days", "is_active": False},
    )
    assert updated.status_code == 200
    ch = updated.json()["channel"]
    assert ch["title"] == "عنوان جدید"
    assert ch["interval_minutes"] == 2880
    assert ch["is_active"] is False

    assert app_client.put("/api/channels/99999", json={"title": "x"}).status_code == 404

    assert app_client.delete(f"/api/channels/{ch_id}").status_code == 200
    assert app_client.delete(f"/api/channels/{ch_id}").status_code == 404
    assert app_client.get("/api/channels").json()["items"] == []


def test_manual_sync_endpoint_is_idempotent(app_client, fake_web):
    fake_web.set_posts([make_post(10 + i, hours_ago=10 - i) for i in range(10)])
    ch_id = app_client.post(
        "/api/channels",
        json={"channel_input": "@sync_me", "interval_value": 1, "interval_unit": "hours", "fetch_now": True},
    ).json()["channel"]["id"]

    again = app_client.post(f"/api/channels/{ch_id}/sync").json()
    assert again["sync_result"]["new_saved_count"] == 0
    assert again["sync_result"]["new_last_message_id"] == 19
    assert again["channel"]["posts_count"] == 10

    fake_web.set_posts([make_post(20, hours_ago=1), make_post(21, hours_ago=0.5)])
    newer = app_client.post(f"/api/channels/{ch_id}/sync").json()
    assert newer["sync_result"]["new_saved_count"] == 2
    assert newer["sync_result"]["new_last_message_id"] == 21

    assert app_client.post("/api/channels/99999/sync").status_code == 404


def test_sync_all_endpoint(app_client, fake_web):
    fake_web.set_posts([make_post(1, hours_ago=1)])
    app_client.post(
        "/api/channels",
        json={"channel_input": "@all_one", "interval_value": 6, "interval_unit": "hours", "fetch_now": False},
    )
    res = app_client.post("/api/channels/sync-all")
    assert res.status_code == 200
    body = res.json()
    assert body["checked_channels"] == 1
    assert body["success_count"] == 1


def test_reset_endpoint(app_client, fake_web):
    fake_web.set_posts([make_post(1 + i, hours_ago=5 - i) for i in range(3)])
    ch_id = app_client.post(
        "/api/channels",
        json={"channel_input": "@reset_me", "interval_value": 6, "interval_unit": "hours", "fetch_now": True},
    ).json()["channel"]["id"]
    assert app_client.get("/api/posts").json()["total"] == 3

    reset = app_client.post(f"/api/channels/{ch_id}/reset", json={"delete_posts": True})
    assert reset.status_code == 200
    assert reset.json()["channel"]["last_message_id"] is None
    assert app_client.get("/api/posts").json()["total"] == 0


def test_posts_pagination_and_filters(app_client, fake_web):
    fake_web.set_posts(
        [
            make_post(1, text="خبر داغ اقتصادی", hours_ago=72, media_type="text"),
            make_post(2, text="ویدیوی آموزشی", hours_ago=48, media_type="video"),
            make_post(3, text="تصویر گزارش", hours_ago=24, media_type="photo"),
        ]
    )
    app_client.post(
        "/api/channels",
        json={"channel_input": "@filter_chan", "interval_value": 6, "interval_unit": "hours", "fetch_now": True},
    )

    page1 = app_client.get("/api/posts?page=1&page_size=2").json()
    assert page1["total"] == 3
    assert page1["total_pages"] == 2
    assert len(page1["items"]) == 2
    # newest first
    assert page1["items"][0]["message_id"] == 3

    page2 = app_client.get("/api/posts?page=2&page_size=2").json()
    assert len(page2["items"]) == 1

    by_media = app_client.get("/api/posts?media_type=video").json()
    assert by_media["total"] == 1
    assert by_media["items"][0]["content"] == "ویدیوی آموزشی"

    by_search = app_client.get("/api/posts?search=اقتصادی").json()
    assert by_search["total"] == 1

    jalali_filter = app_client.get("/api/posts?date_from=1405/08/01&date_to=1405/08/30").json()
    assert jalali_filter["total"] == 3

    empty_range = app_client.get("/api/posts?date_from=1405/01/01&date_to=1405/01/10").json()
    assert empty_range["total"] == 0

    invalid_date = app_client.get("/api/posts?date_from=not-a-date")
    assert invalid_date.status_code == 400

    assert app_client.get("/api/posts?page=0").status_code == 422


def test_post_delete_endpoint(app_client, fake_web):
    fake_web.set_posts([make_post(5, hours_ago=1)])
    app_client.post(
        "/api/channels",
        json={"channel_input": "@del_post", "interval_value": 6, "interval_unit": "hours", "fetch_now": True},
    )
    post = app_client.get("/api/posts").json()["items"][0]
    assert app_client.delete(f"/api/posts/{post['id']}").status_code == 200
    assert app_client.delete(f"/api/posts/{post['id']}").status_code == 404
    assert app_client.get("/api/posts").json()["total"] == 0


def test_logs_endpoint_and_clear(app_client, fake_web):
    fake_web.set_posts([make_post(1, hours_ago=1)])
    app_client.post(
        "/api/channels",
        json={"channel_input": "@log_chan", "interval_value": 6, "interval_unit": "hours", "fetch_now": True},
    )
    logs = app_client.get("/api/logs").json()["items"]
    assert len(logs) == 1
    assert logs[0]["status"] == "success"
    assert logs[0]["trigger_type"] == "manual"
    assert logs[0]["new_saved_count"] == 1
    assert logs[0]["created_display"] is not None

    assert app_client.delete("/api/logs").json()["cleared"] == 1
    assert app_client.get("/api/logs").json()["items"] == []


def test_excel_export_endpoint(app_client, fake_web):
    fake_web.set_posts([make_post(1 + i, hours_ago=5 - i) for i in range(3)])
    app_client.post(
        "/api/channels",
        json={"channel_input": "@excel_chan", "interval_value": 6, "interval_unit": "hours", "fetch_now": True},
    )

    res = app_client.get("/api/exports/excel")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in res.headers["content-disposition"]
    assert res.content[:2] == b"PK"

    wb = load_workbook(io.BytesIO(res.content))
    assert "مطالب کانال‌ها" in wb.sheetnames
    assert wb["مطالب کانال‌ها"].max_row == 4

    # Filtered export honours the media_type filter
    filtered = app_client.get("/api/exports/excel?media_type=photo")
    assert filtered.status_code == 200
    wb2 = load_workbook(io.BytesIO(filtered.content))
    assert wb2["مطالب کانال‌ها"].max_row == 1


def test_sqlite_export_endpoint(app_client, fake_web):
    fake_web.set_posts([make_post(1 + i, hours_ago=5 - i) for i in range(4)])
    app_client.post(
        "/api/channels",
        json={"channel_input": "@sqlite_chan", "interval_value": 6, "interval_unit": "hours", "fetch_now": True},
    )

    res = app_client.get("/api/exports/sqlite")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/vnd.sqlite3")
    assert ".sqlite" in res.headers["content-disposition"]

    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        tmp.write(res.content)
        tmp_path = Path(tmp.name)

    try:
        conn = sqlite3.connect(str(tmp_path))
        try:
            assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 4
            assert conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0] == 1
        finally:
            conn.close()
    finally:
        tmp_path.unlink(missing_ok=True)


def test_settings_get_and_update(app_client):
    data = app_client.get("/api/settings").json()
    assert data["settings"]["collector_mode"] == "auto"
    assert data["settings"]["timezone"] == "Asia/Tehran"
    assert data["settings"]["default_initial_limit"] == 10
    assert data["settings"]["telethon_api_hash_set"] is False

    updated = app_client.put(
        "/api/settings",
        json={
            "collector_mode": "web",
            "timezone": "UTC",
            "default_initial_limit": 15,
            "telethon_api_id": "۱۲۳۴۵",
            "proxy_enabled": True,
            "proxy_type": "http",
            "proxy_host": "127.0.0.1",
            "proxy_port": "۸۰۸۰",
            "proxy_username": "u",
            "proxy_password": "p",
        },
    )
    assert updated.status_code == 200, updated.text
    s = updated.json()["settings"]
    assert s["collector_mode"] == "web"
    assert s["timezone"] == "UTC"
    assert s["default_initial_limit"] == 15
    assert s["telethon_api_id"] == "12345"
    assert s["proxy_enabled"] is True
    assert s["proxy_type"] == "http"
    assert s["proxy_port"] == "8080"
    assert s["proxy_password_set"] is True

    bad_port = app_client.put("/api/settings", json={"proxy_port": "99999"})
    assert bad_port.status_code == 400


def test_settings_masks_secrets(app_client):
    app_client.put(
        "/api/settings",
        json={"telethon_api_hash": "abcdef123456", "proxy_password": "secret"},
    )
    data = app_client.get("/api/settings").json()["settings"]
    assert "abcdef123456" not in str(data)
    assert data["telethon_api_hash_set"] is True
    assert "secret" not in str(data)
    assert data["proxy_password_set"] is True


def test_demo_seed_and_clear(app_client):
    seeded = app_client.post("/api/demo/seed").json()
    assert seeded["seeded"] is True
    assert seeded["created_channels"] == 2
    assert seeded["inserted_posts"] == 15

    channels = app_client.get("/api/channels").json()["items"]
    assert len(channels) == 2
    assert all(ch["is_demo"] for ch in channels)
    assert all(ch["is_active"] is False for ch in channels)

    posts = app_client.get("/api/posts?page_size=100").json()
    assert posts["total"] == 15
    for post in posts["items"]:
        assert post["published_date"] and post["published_jalali_date"] and post["published_time"]

    cleared = app_client.delete("/api/demo").json()
    assert cleared["cleared_channels"] == 2
    assert app_client.get("/api/channels").json()["items"] == []
    assert app_client.get("/api/posts").json()["total"] == 0


def test_demo_data_is_exportable_both_formats(app_client):
    app_client.post("/api/demo/seed")
    excel = app_client.get("/api/exports/excel")
    assert excel.status_code == 200
    wb = load_workbook(io.BytesIO(excel.content))
    assert wb["مطالب کانال‌ها"].max_row == 16

    sqlite_res = app_client.get("/api/exports/sqlite?filtered_only=true&channel_id=1")
    assert sqlite_res.status_code == 200


def test_telethon_endpoints_fail_gracefully_without_configuration(app_client):
    res = app_client.post("/api/telethon/send-code", json={"phone": "+989120000000"})
    assert res.status_code == 400
    assert "detail" in res.json()

    logout = app_client.post("/api/telethon/logout")
    assert logout.status_code == 200
    assert logout.json()["logged_out"] is True
