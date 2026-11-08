from __future__ import annotations

from datetime import timedelta

from app.collectors.manager import SyncManager
from app.services.scheduler import ChannelSchedulerService
from app.utils.channel_parser import parse_channel_input
from app.utils.jalali import format_iso_utc, utc_now
from tests.conftest import FakeTelethonCollector, FakeWebCollector, make_post


def _make_channel(db, raw: str, active: bool = True):
    return db.create_channel(
        parsed=parse_channel_input(raw),
        interval_value=1,
        interval_unit="hours",
        initial_limit=10,
        title=None,
        is_active=active,
    )


def test_due_channels_only_returns_active_and_due(db):
    due = _make_channel(db, "@due_chan")
    future = _make_channel(db, "@future_chan")
    paused = _make_channel(db, "@paused_chan", active=False)

    now = utc_now()
    # Force one channel into the past and one into the future
    with db.transaction() as conn:
        conn.execute(
            "UPDATE channels SET next_fetch_at = ? WHERE id = ?",
            (format_iso_utc(now - timedelta(minutes=5)), int(due["id"])),
        )
        conn.execute(
            "UPDATE channels SET next_fetch_at = ? WHERE id = ?",
            (format_iso_utc(now + timedelta(hours=3)), int(future["id"])),
        )
        conn.execute(
            "UPDATE channels SET next_fetch_at = ? WHERE id = ?",
            (format_iso_utc(now - timedelta(hours=5)), int(paused["id"])),
        )

    due_ids = [int(c["id"]) for c in db.get_due_channels(format_iso_utc(now))]
    assert due_ids == [int(due["id"])]


async def test_scheduler_tick_syncs_due_channels_and_reschedules(db):
    web = FakeWebCollector()
    web.set_posts([make_post(1 + i, hours_ago=5 - i) for i in range(3)])
    manager = SyncManager(db=db, web_collector=web, telethon_collector=FakeTelethonCollector())
    scheduler = ChannelSchedulerService(db=db, sync_manager=manager, tick_seconds=10)

    channel = _make_channel(db, "@tick_chan")
    with db.transaction() as conn:
        conn.execute(
            "UPDATE channels SET next_fetch_at = ? WHERE id = ?",
            (format_iso_utc(utc_now() - timedelta(minutes=1)), int(channel["id"])),
        )

    processed = await scheduler.run_due_checks()
    assert processed == 1

    refreshed = db.get_channel(int(channel["id"]))
    assert refreshed["last_message_id"] == 3
    assert refreshed["next_fetch_at"] > format_iso_utc(utc_now())
    assert db.list_posts(page_size=10)["total"] == 3
    assert scheduler.last_tick_at is not None

    # Nothing is due a second time right away
    assert await scheduler.run_due_checks() == 0


async def test_scheduler_status_reports_stopped_before_start(db):
    web = FakeWebCollector()
    manager = SyncManager(db=db, web_collector=web, telethon_collector=FakeTelethonCollector())
    scheduler = ChannelSchedulerService(db=db, sync_manager=manager, tick_seconds=10)

    status = scheduler.get_status()
    assert status["running"] is False
    assert status["tick_seconds"] == 10


async def test_inactive_channel_gets_no_next_fetch_after_sync(db):
    web = FakeWebCollector()
    web.set_posts([make_post(1, hours_ago=1)])
    manager = SyncManager(db=db, web_collector=web, telethon_collector=FakeTelethonCollector())

    channel = _make_channel(db, "@manual_only", active=False)
    await manager.sync_channel(int(channel["id"]), trigger_type="manual")

    refreshed = db.get_channel(int(channel["id"]))
    assert refreshed["last_message_id"] == 1
    assert refreshed["next_fetch_at"] is None
