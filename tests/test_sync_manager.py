from __future__ import annotations

from typing import List

import pytest

from app.collectors.manager import SyncManager
from app.utils.channel_parser import parse_channel_input
from tests.conftest import FakeTelethonCollector, FakeWebCollector, make_post


def build_manager(db, web: FakeWebCollector) -> SyncManager:
    return SyncManager(db=db, web_collector=web, telethon_collector=FakeTelethonCollector())


def create_channel(db, raw: str = "@test_channel", initial_limit: int = 10, interval_value: float = 6):
    return db.create_channel(
        parsed=parse_channel_input(raw),
        interval_value=interval_value,
        interval_unit="hours",
        initial_limit=initial_limit,
        title=None,
        is_active=True,
    )


async def test_first_sync_stores_only_last_ten_posts(db):
    web = FakeWebCollector()
    # Channel has 30 posts on the page; first run must import only the newest 10.
    web.set_posts([make_post(100 + i, hours_ago=30 - i) for i in range(30)])
    manager = build_manager(db, web)

    channel = create_channel(db)
    assert channel["last_message_id"] is None

    result = await manager.sync_channel(int(channel["id"]), trigger_type="manual")

    assert result["status"] == "success"
    assert result["fetched_count"] == 10
    assert result["new_saved_count"] == 10
    assert result["previous_last_message_id"] is None
    assert result["new_last_message_id"] == 129

    stored = db.list_posts(page_size=100)
    assert stored["total"] == 10
    ids: List[int] = sorted(p["message_id"] for p in stored["items"])
    assert ids == list(range(120, 130))

    refreshed = db.get_channel(int(channel["id"]))
    assert refreshed["last_message_id"] == 129
    assert refreshed["last_status"] == "ok"
    assert refreshed["last_fetched_at"] is not None
    assert refreshed["next_fetch_at"] is not None


async def test_second_sync_only_imports_newer_posts(db):
    web = FakeWebCollector()
    web.set_posts([make_post(100 + i, hours_ago=30 - i) for i in range(30)])
    manager = build_manager(db, web)
    channel = create_channel(db)
    ch_id = int(channel["id"])

    await manager.sync_channel(ch_id, trigger_type="scheduled")
    assert db.list_posts(page_size=100)["total"] == 10

    # Three new messages published since the last run
    web.set_posts([make_post(130 + i, hours_ago=2 - i) for i in range(3)])
    result = await manager.sync_channel(ch_id, trigger_type="scheduled")

    assert result["new_saved_count"] == 3
    assert result["previous_last_message_id"] == 129
    assert result["new_last_message_id"] == 132
    assert db.list_posts(page_size=100)["total"] == 13


async def test_no_new_posts_does_not_duplicate_or_move_cursor_backwards(db):
    web = FakeWebCollector()
    web.set_posts([make_post(100 + i, hours_ago=30 - i) for i in range(30)])
    manager = build_manager(db, web)
    ch_id = int(create_channel(db)["id"])

    await manager.sync_channel(ch_id)
    # Same page returned again: nothing new should be saved
    result = await manager.sync_channel(ch_id)

    assert result["status"] == "success"
    assert result["new_saved_count"] == 0
    assert result["new_last_message_id"] == 129
    assert db.list_posts(page_size=100)["total"] == 10


async def test_database_unique_constraint_blocks_duplicate_message_ids(db):
    web = FakeWebCollector()
    web.set_posts([make_post(500 + i, hours_ago=10 - i) for i in range(5)])
    manager = build_manager(db, web)
    channel = create_channel(db, initial_limit=10)

    first = await manager.sync_channel(int(channel["id"]))
    assert first["new_saved_count"] == 5

    # Force a re-fetch with the cursor cleared -> INSERT OR IGNORE must dedupe by (channel_id, message_id)
    db.reset_channel_cursor(int(channel["id"]), delete_posts=False)
    second = await manager.sync_channel(int(channel["id"]))

    assert second["fetched_count"] == 5
    assert second["new_saved_count"] == 0
    assert db.list_posts(page_size=100)["total"] == 5


async def test_structured_post_columns_are_populated(db):
    web = FakeWebCollector()
    web.set_posts([make_post(77, text="سلام دنیا", hours_ago=1, media_type="photo", views=4200)])
    manager = build_manager(db, web)
    ch_id = int(create_channel(db, raw="@structured_chan")["id"])

    await manager.sync_channel(ch_id)
    post = db.list_posts(page_size=10)["items"][0]

    assert post["channel_username"] == "structured_chan"
    assert post["message_id"] == 77
    assert post["post_url"] == "https://t.me/test_channel/77"
    assert post["content"] == "سلام دنیا"
    assert post["media_type"] == "photo"
    assert post["views"] == 4200
    # Gregorian and Jalali date + separate time column
    assert len(post["published_date"]) == 10 and post["published_date"].count("-") == 2
    assert len(post["published_jalali_date"]) == 10 and post["published_jalali_date"].count("/") == 2
    assert len(post["published_time"]) == 8 and post["published_time"].count(":") == 2
    assert post["published_at_utc"].endswith("Z")
    assert post["fetched_at"].endswith("Z")


async def test_initial_limit_is_configurable_per_channel(db):
    web = FakeWebCollector()
    web.set_posts([make_post(1 + i, hours_ago=20 - i) for i in range(20)])
    manager = build_manager(db, web)
    ch_id = int(create_channel(db, initial_limit=3)["id"])

    result = await manager.sync_channel(ch_id)
    assert result["fetched_count"] == 3
    ids = sorted(p["message_id"] for p in db.list_posts(page_size=50)["items"])
    assert ids == [18, 19, 20]


async def test_sync_error_is_recorded_and_cursor_untouched(db):
    class BrokenWebCollector(FakeWebCollector):
        async def fetch_channel_posts(self, **kwargs):
            raise __import__("app.collectors.base", fromlist=["CollectorError"]).CollectorError(
                "شبکه در دسترس نیست"
            )

    manager = build_manager(db, BrokenWebCollector())
    ch_id = int(create_channel(db)["id"])

    result = await manager.sync_channel(ch_id)
    assert result["status"] == "error"
    channel = db.get_channel(ch_id)
    assert channel["last_status"] == "error"
    assert "شبکه در دسترس نیست" in (channel["last_error"] or "")
    assert channel["last_message_id"] is None
    assert db.list_posts(page_size=10)["total"] == 0

    logs = db.list_fetch_logs(limit=10)
    assert logs[0]["status"] == "error"


async def test_sync_all_active_skips_inactive_and_demo(db):
    web = FakeWebCollector()
    web.set_posts([make_post(10 + i, hours_ago=6 - i) for i in range(4)])
    manager = build_manager(db, web)

    active1 = create_channel(db, raw="@active_one")
    paused = create_channel(db, raw="@paused_two")
    db.update_channel(int(paused["id"]), is_active=False)

    # A demo channel must never be sent to the network
    demo = db.create_channel(
        parsed=parse_channel_input("@demo_three"),
        interval_value=1,
        interval_unit="days",
        initial_limit=10,
        title="نمونه",
        is_active=True,
        is_demo=True,
    )

    res = await manager.sync_all_active(trigger_type="manual")

    assert res["checked_channels"] == 1
    assert res["success_count"] == 1
    assert res["total_new_posts"] == 4
    assert int(active1["id"]) == res["results"][0]["channel_id"]
    assert db.get_channel(int(paused["id"]))["last_message_id"] is None
    assert db.get_channel(int(demo["id"]))["last_message_id"] is None


async def test_reset_cursor_with_delete_posts_clears_archive(db):
    web = FakeWebCollector()
    web.set_posts([make_post(200 + i, hours_ago=5 - i) for i in range(5)])
    manager = build_manager(db, web)
    ch_id = int(create_channel(db)["id"])
    await manager.sync_channel(ch_id)

    db.reset_channel_cursor(ch_id, delete_posts=True)
    refreshed = db.get_channel(ch_id)
    assert refreshed["last_message_id"] is None
    assert db.list_posts(page_size=10)["total"] == 0


def test_filter_and_prepare_posts_dedupes_within_batch():
    raw = [make_post(5), make_post(5, text="نسخه جایگزین"), make_post(4), make_post(6)]
    prepared = SyncManager.filter_and_prepare_posts(
        raw,
        last_message_id=None,
        initial_limit=10,
        tz_name="Asia/Tehran",
    )
    assert [p["message_id"] for p in prepared] == [4, 5, 6]
    assert prepared[1]["content"] == "نسخه جایگزین"


def test_filter_and_prepare_posts_respects_last_message_id():
    raw = [make_post(i) for i in range(1, 11)]
    prepared = SyncManager.filter_and_prepare_posts(
        raw,
        last_message_id=7,
        initial_limit=10,
        tz_name="Asia/Tehran",
    )
    assert [p["message_id"] for p in prepared] == [8, 9, 10]
