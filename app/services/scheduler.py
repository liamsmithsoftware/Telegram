from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.collectors.manager import SyncManager
from app.config import SCHEDULER_TICK_SECONDS
from app.database import DatabaseManager
from app.utils.jalali import utc_now_iso

logger = logging.getLogger("telegram_collector.scheduler")


class ChannelSchedulerService:
    """
    Periodically inspects `channels` for due `next_fetch_at` timestamps and
    dispatches incremental channel syncs according to each channel's own interval.
    """

    def __init__(
        self,
        db: DatabaseManager,
        sync_manager: SyncManager,
        tick_seconds: int = SCHEDULER_TICK_SECONDS,
    ) -> None:
        self.db = db
        self.sync_manager = sync_manager
        self.tick_seconds = max(10, int(tick_seconds))
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._tick_lock = asyncio.Lock()
        self.last_tick_at: Optional[str] = None
        self.currently_syncing_channel_id: Optional[int] = None

    @property
    def is_running(self) -> bool:
        return bool(self._scheduler and self._scheduler.running)

    def start(self) -> None:
        if self._scheduler and self._scheduler.running:
            return
        self._scheduler = AsyncIOScheduler(timezone=timezone.utc)
        self._scheduler.add_job(
            self.run_due_checks,
            trigger="interval",
            seconds=self.tick_seconds,
            id="due_channels_poller",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5),
        )
        self._scheduler.start()
        logger.info("ChannelSchedulerService started (tick=%ss)", self.tick_seconds)

    def stop(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("ChannelSchedulerService stopped")

    async def run_due_checks(self) -> int:
        if self._tick_lock.locked():
            return 0

        async with self._tick_lock:
            self.last_tick_at = utc_now_iso()
            due_channels = self.db.get_due_channels(self.last_tick_at)
            processed = 0
            for idx, ch in enumerate(due_channels):
                if idx > 0:
                    await asyncio.sleep(1.5)
                ch_id = int(ch["id"])
                self.currently_syncing_channel_id = ch_id
                try:
                    await self.sync_manager.sync_channel(ch_id, trigger_type="scheduled")
                    processed += 1
                except Exception as exc:
                    logger.exception("Scheduled sync failed for channel %s: %s", ch_id, exc)
                finally:
                    self.currently_syncing_channel_id = None
            return processed

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self.is_running,
            "tick_seconds": self.tick_seconds,
            "last_tick_at": self.last_tick_at,
            "currently_syncing_channel_id": self.currently_syncing_channel_id,
        }
