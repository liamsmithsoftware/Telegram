"""
تست‌های پشتیبان‌گیری (لیست کانال‌ها + تنظیمات) و بازیابی آن.
"""
from __future__ import annotations

import io
import json

from tests.conftest import make_post

BACKUP_FORMAT = "telegram-channel-collector-backup"


def _seed(app_client, fake_web):
    fake_web.set_posts([make_post(1 + i, username="bk_chan", hours_ago=5 - i) for i in range(3)])
    created = app_client.post(
        "/api/channels",
        json={
            "channel_input": "@bk_chan",
            "interval_value": 4,
            "interval_unit": "hours",
            "initial_limit": 10,
            "fetch_now": True,
        },
    ).json()["channel"]
    # عنوان پس از دریافت، از خود کانال خوانده می‌شود؛ اینجا صریحاً تغییرش می‌دهیم
    app_client.put(f"/api/channels/{created['id']}", json={"title": "کانال پشتیبان"})
    app_client.post(
        "/api/channels",
        json={
            "channel_input": "@bk_paused",
            "interval_value": 2,
            "interval_unit": "days",
            "is_active": False,
            "fetch_now": False,
        },
    )


# ---------------------------------------------------------------------------
# گرفتن پشتیبان
# ---------------------------------------------------------------------------
def test_export_backup_contains_channels_and_settings(app_client, fake_web):
    _seed(app_client, fake_web)

    res = app_client.get("/api/backup/export")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    assert "attachment" in res.headers["content-disposition"]
    assert ".json" in res.headers["content-disposition"]

    data = json.loads(res.content.decode("utf-8"))
    assert data["format"] == BACKUP_FORMAT
    assert data["format_version"] == 1
    assert data["counts"]["channels"] == 2
    assert data["counts"]["settings"] > 0
    assert len(data["channels"]) == 2

    chan = next(c for c in data["channels"] if c["username"] == "bk_chan")
    assert chan["title"] == "کانال پشتیبان"
    assert chan["interval_value"] == 4
    assert chan["interval_unit"] == "hours"
    assert chan["is_active"] is True
    assert chan["last_message_id"] == 3
    assert chan["channel_input"]

    paused = next(c for c in data["channels"] if c["username"] == "bk_paused")
    assert paused["is_active"] is False
    assert paused["interval_unit"] == "days"

    assert "timezone" in data["settings"]
    assert "collector_mode" in data["settings"]


def test_backup_excludes_secrets_by_default(app_client):
    app_client.put(
        "/api/settings",
        json={
            "telethon_api_id": "12345",
            "telethon_api_hash": "supersecretvalue",
            "telethon_phone": "+989120000000",
            "proxy_enabled": True,
            "proxy_host": "127.0.0.1",
            "proxy_port": "1080",
            "proxy_username": "proxyuser",
            "proxy_password": "proxypass",
        },
    )

    data = json.loads(app_client.get("/api/backup/export").content.decode("utf-8"))
    settings = data["settings"]
    assert "telethon_api_hash" not in settings
    assert "proxy_password" not in settings
    assert "proxy_username" not in settings
    assert "telethon_phone" not in settings
    # غیرحساس‌ها باید باشند
    assert settings["proxy_host"] == "127.0.0.1"
    assert settings["proxy_port"] == "1080"
    assert data["secrets_included"] is False


def test_backup_can_include_secrets_on_request(app_client):
    app_client.put("/api/settings", json={"telethon_api_hash": "supersecretvalue"})
    data = json.loads(
        app_client.get("/api/backup/export?include_secrets=true").content.decode("utf-8")
    )
    assert data["settings"]["telethon_api_hash"] == "supersecretvalue"
    assert data["secrets_included"] is True


def test_backup_without_settings(app_client, fake_web):
    _seed(app_client, fake_web)
    data = json.loads(
        app_client.get("/api/backup/export?include_settings=false").content.decode("utf-8")
    )
    assert data["settings"] == {}
    assert data["counts"]["settings"] == 0
    assert len(data["channels"]) == 2


def test_backup_only_active_channels(app_client, fake_web):
    _seed(app_client, fake_web)
    data = json.loads(
        app_client.get("/api/backup/export?only_active=true").content.decode("utf-8")
    )
    assert len(data["channels"]) == 1
    assert data["channels"][0]["username"] == "bk_chan"


def test_inspect_backup_summary(app_client, fake_web):
    _seed(app_client, fake_web)
    data = app_client.get("/api/backup/inspect").json()
    assert data["counts"]["channels"] == 2
    assert data["format"] == BACKUP_FORMAT
    assert len(data["channels"]) == 2
    assert "timezone" in data["settings"]
    # کلیدهای حساس نباید در پیش‌نمایش باشند
    assert "telethon_api_hash" not in data["settings"]


# ---------------------------------------------------------------------------
# بازیابی
# ---------------------------------------------------------------------------
def _upload(client, payload, filename="backup.json", query=""):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return client.post(
        f"/api/backup/restore-file{query}",
        files={"file": (filename, io.BytesIO(body), "application/json")},
    )


def test_restore_merge_into_fresh_install(app_client, fake_web):
    _seed(app_client, fake_web)
    backup = json.loads(app_client.get("/api/backup/export").content.decode("utf-8"))

    # شبیه‌سازی نصب تازه
    app_client.post("/api/posts/purge", json={"keep_channels": False})
    assert app_client.get("/api/channels").json()["items"] == []

    report = _upload(app_client, backup).json()
    assert report["added_channels"] == 2
    assert report["mode"] == "merge"
    assert "بازیابی" in report["message"]

    channels = {c["username"]: c for c in app_client.get("/api/channels").json()["items"]}
    assert set(channels) == {"bk_chan", "bk_paused"}
    assert channels["bk_chan"]["title"] == "کانال پشتیبان"
    assert channels["bk_chan"]["interval_value"] == 4
    assert channels["bk_paused"]["is_active"] is False


def test_restore_is_idempotent_in_merge_mode(app_client, fake_web):
    _seed(app_client, fake_web)
    backup = json.loads(app_client.get("/api/backup/export").content.decode("utf-8"))

    first = _upload(app_client, backup).json()
    assert first["added_channels"] == 0
    assert first["updated_channels"] == 2

    second = _upload(app_client, backup).json()
    assert second["added_channels"] == 0
    assert second["updated_channels"] == 2
    # هیچ کانال تکراری ساخته نمی‌شود
    assert len(app_client.get("/api/channels").json()["items"]) == 2


def test_restore_merge_keeps_other_channels(app_client, fake_web):
    _seed(app_client, fake_web)
    backup = json.loads(app_client.get("/api/backup/export").content.decode("utf-8"))

    # یک کانال دیگر که در فایل نیست
    app_client.post(
        "/api/channels",
        json={"channel_input": "@not_in_backup", "interval_value": 6, "interval_unit": "hours", "fetch_now": False},
    )

    report = _upload(app_client, backup).json()
    assert report["removed_channels"] == 0
    usernames = {c["username"] for c in app_client.get("/api/channels").json()["items"]}
    assert "not_in_backup" in usernames


def test_restore_replace_mode_wipes_existing(app_client, fake_web):
    _seed(app_client, fake_web)
    backup = json.loads(app_client.get("/api/backup/export").content.decode("utf-8"))

    app_client.post(
        "/api/channels",
        json={"channel_input": "@extra_one", "interval_value": 1, "interval_unit": "days", "fetch_now": False},
    )
    assert len(app_client.get("/api/channels").json()["items"]) == 3

    report = _upload(app_client, backup, query="?mode=replace").json()
    assert report["removed_channels"] == 3
    assert report["added_channels"] == 2

    usernames = {c["username"] for c in app_client.get("/api/channels").json()["items"]}
    assert usernames == {"bk_chan", "bk_paused"}


def test_restore_rejects_invalid_json(app_client):
    res = app_client.post(
        "/api/backup/restore-file",
        files={"file": ("bad.json", io.BytesIO(b"this is not json"), "application/json")},
    )
    assert res.status_code == 400
    assert "JSON" in res.json()["detail"]


def test_restore_rejects_foreign_json_file(app_client):
    res = _upload(app_client, {"hello": "world"})
    assert res.status_code == 400
    assert "پشتیبان" in res.json()["detail"]


def test_restore_rejects_unsupported_format_version(app_client):
    res = _upload(app_client, {"format": BACKUP_FORMAT, "format_version": 99, "channels": []})
    assert res.status_code == 400
    assert "نسخه" in res.json()["detail"]


def test_restore_empty_file_is_rejected(app_client):
    res = app_client.post(
        "/api/backup/restore-file",
        files={"file": ("empty.json", io.BytesIO(b""), "application/json")},
    )
    assert res.status_code == 400


def test_restore_settings_only_when_requested(app_client):
    app_client.put("/api/settings", json={"timezone": "UTC", "collector_mode": "web"})
    backup = json.loads(app_client.get("/api/backup/export").content.decode("utf-8"))
    assert backup["settings"]["timezone"] == "UTC"

    app_client.put("/api/settings", json={"timezone": "Asia/Tehran", "collector_mode": "auto"})

    report = _upload(app_client, backup, query="?restore_settings=false").json()
    assert report["restored_settings"] == 0
    assert app_client.get("/api/settings").json()["settings"]["timezone"] == "Asia/Tehran"


def test_restore_settings_without_overwrite_keeps_existing(app_client):
    app_client.put("/api/settings", json={"timezone": "UTC"})
    backup = json.loads(app_client.get("/api/backup/export").content.decode("utf-8"))

    app_client.put("/api/settings", json={"timezone": "Asia/Tehran"})
    # بدون overwrite، مقدار موجود (Asia/Tehran) باید حفظ شود
    _upload(app_client, backup, query="?restore_settings=true&overwrite_settings=false")
    assert app_client.get("/api/settings").json()["settings"]["timezone"] == "Asia/Tehran"

    # با overwrite، مقدار فایل اعمال می‌شود
    _upload(app_client, backup, query="?restore_settings=true&overwrite_settings=true")
    assert app_client.get("/api/settings").json()["settings"]["timezone"] == "UTC"


def test_restore_keeps_archive_and_cursor_when_posts_exist(app_client, fake_web):
    _seed(app_client, fake_web)
    backup = json.loads(app_client.get("/api/backup/export").content.decode("utf-8"))

    report = _upload(app_client, backup).json()
    # کانال bk_chan مطلب دارد، پس شناسه آخرین پیام بازگردانی می‌شود
    assert report["cursor_restored"] >= 1
    chan = next(
        c for c in app_client.get("/api/channels").json()["items"] if c["username"] == "bk_chan"
    )
    assert chan["last_message_id"] == 3
    assert app_client.get("/api/posts").json()["total"] == 3


def test_restore_skips_cursor_when_archive_is_empty(app_client, fake_web):
    _seed(app_client, fake_web)
    backup = json.loads(app_client.get("/api/backup/export").content.decode("utf-8"))
    app_client.post("/api/posts/purge", json={"keep_channels": False})

    report = _upload(app_client, backup).json()
    assert report["warnings"], "باید هشدار بدهد که شناسه بازگردانی نشد"
    chan = next(
        c for c in app_client.get("/api/channels").json()["items"] if c["username"] == "bk_chan"
    )
    assert chan["last_message_id"] is None


def test_validate_file_endpoint(app_client, fake_web):
    _seed(app_client, fake_web)
    backup = json.loads(app_client.get("/api/backup/export").content.decode("utf-8"))
    body = json.dumps(backup, ensure_ascii=False).encode("utf-8")

    res = app_client.post(
        "/api/backup/validate-file",
        files={"file": ("backup.json", io.BytesIO(body), "application/json")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is True
    assert data["channels_in_file"] == 2
    assert data["new_channels"] == 0
    assert data["existing_channels"] == 2
    assert data["format_version"] == 1
    assert data["valid"] is True


def test_validate_file_reports_new_channels(app_client, fake_web):
    _seed(app_client, fake_web)
    backup = json.loads(app_client.get("/api/backup/export").content.decode("utf-8"))
    app_client.post("/api/posts/purge", json={"keep_channels": False})

    body = json.dumps(backup, ensure_ascii=False).encode("utf-8")
    data = app_client.post(
        "/api/backup/validate-file",
        files={"file": ("backup.json", io.BytesIO(body), "application/json")},
    ).json()
    assert data["new_channels"] == 2
    assert data["existing_channels"] == 0


def test_restore_via_json_api(app_client, fake_web):
    _seed(app_client, fake_web)
    backup = json.loads(app_client.get("/api/backup/export").content.decode("utf-8"))
    app_client.post("/api/posts/purge", json={"keep_channels": False})

    res = app_client.post(
        "/api/backup/restore",
        json={"mode": "merge", "restore_settings": True, "payload": backup},
    )
    assert res.status_code == 200
    assert res.json()["added_channels"] == 2


def test_backup_ui_present(app_client):
    page = app_client.get("/").text
    assert 'data-tab="backup"' in page
    assert "btnDownloadBackup" in page
    assert "btnRestoreBackup" in page
    assert "btnValidateBackup" in page
    assert "backupFileInput" in page

    js = app_client.get("/static/js/app.js").text
    for fn in ("downloadBackup", "previewBackup", "restoreBackup", "validateBackupFile"):
        assert fn in js
