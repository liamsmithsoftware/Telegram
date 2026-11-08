from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from app.collectors.base import CollectorError, FetchBatchResult, FetchedPost
from app.collectors.telethon_client import TelethonCollector
from app.collectors.web_scraper import WebScraperCollector
from app.config import DEFAULT_INITIAL_LIMIT, DEFAULT_TIMEZONE
from app.database import DatabaseManager
from app.utils.jalali import split_datetime


class SyncManager:
    def __init__(
        self,
        db: DatabaseManager,
        web_collector: Optional[WebScraperCollector] = None,
        telethon_collector: Optional[TelethonCollector] = None,
    ) -> None:
        self.db = db
        self.web_collector = web_collector or WebScraperCollector()
        self.telethon_collector = telethon_collector or TelethonCollector()
        self._channel_locks: Dict[int, asyncio.Lock] = {}

    def _get_lock(self, channel_id: int) -> asyncio.Lock:
        if channel_id not in self._channel_locks:
            self._channel_locks[channel_id] = asyncio.Lock()
        return self._channel_locks[channel_id]

    async def _fetch_batch(
        self,
        channel: Dict[str, Any],
        settings: Dict[str, str],
    ) -> FetchBatchResult:
        mode = (settings.get("collector_mode") or "auto").strip().lower()
        is_private = bool(channel.get("is_private"))
        last_message_id: Optional[int] = channel.get("last_message_id")
        initial_limit = int(channel.get("initial_limit") or DEFAULT_INITIAL_LIMIT)

        if is_private and mode == "web":
            raise CollectorError(
                "این کانال خصوصی است و از طریق نسخه وب قابل دریافت نیست؛ لطفاً در تنظیمات حالت دریافت را روی «هوشمند» یا «Telethon» قرار دهید و وارد اکانت شوید."
            )

        if mode == "telethon" or is_private:
            return await self.telethon_collector.fetch_channel_posts(
                channel=channel,
                settings=settings,
            )

        if mode == "auto" and self.telethon_collector.has_credentials(settings) and self.telethon_collector.has_session_file():
            try:
                return await self.telethon_collector.fetch_channel_posts(
                    channel=channel,
                    settings=settings,
                )
            except CollectorError:
                # Fallback to public web scraper if channel has a public username
                if not channel.get("username"):
                    raise

        return await self.web_collector.fetch_channel_posts(
            username=channel.get("username") or "",
            last_message_id=last_message_id,
            initial_limit=initial_limit,
            settings=settings,
        )

    @staticmethod
    def filter_and_prepare_posts(
        raw_posts: List[FetchedPost],
        *,
        last_message_id: Optional[int],
        initial_limit: int,
        tz_name: str,
    ) -> List[Dict[str, Any]]:
        # Deduplicate within batch by message_id and sort ascending (oldest -> newest)
        unique_map: Dict[int, FetchedPost] = {}
        for p in raw_posts:
            unique_map[int(p.message_id)] = p
        ordered = sorted(unique_map.values(), key=lambda p: p.message_id)

        if last_message_id is None:
            # First run: strictly take at most `initial_limit` (default 10) latest posts
            filtered = ordered[-max(1, int(initial_limit)) :]
        else:
            # Subsequent runs: strictly take posts newer than `last_message_id`
            filtered = [p for p in ordered if p.message_id > int(last_message_id)]

        prepared: List[Dict[str, Any]] = []
        for post in filtered:
            dt_parts = split_datetime(post.published_at, tz_name=tz_name)
            prepared.append(
                {
                    "message_id": int(post.message_id),
                    "post_url": post.post_url,
                    "published_date": dt_parts.published_date,
                    "published_jalali_date": dt_parts.published_jalali_date,
                    "published_time": dt_parts.published_time,
                    "published_at_utc": dt_parts.published_at_utc,
                    "content": post.content,
                    "media_type": post.media_type or "text",
                    "media_url": post.media_url,
                    "views": post.views,
                }
            )
        return prepared

    async def sync_channel(
        self,
        channel_id: int,
        *,
        trigger_type: str = "manual",
    ) -> Dict[str, Any]:
        lock = self._get_lock(channel_id)
        async with lock:
            channel = self.db.get_channel(channel_id)
            if not channel:
                raise LookupError("کانال مورد نظر یافت نشد.")

            if channel.get("is_demo"):
                return {
                    "channel_id": channel_id,
                    "channel_title": channel["title"],
                    "fetched_count": 0,
                    "new_saved_count": 0,
                    "previous_last_message_id": channel["last_message_id"],
                    "new_last_message_id": channel["last_message_id"],
                    "status": "success",
                    "message": "این یک کانال نمونه آزمایشی است (برای دریافت واقعی، آدرس کانال تلگرام واقعی اضافه کنید).",
                }

            settings = self.db.get_settings()
            tz_name = settings.get("timezone") or DEFAULT_TIMEZONE
            configured_mode = settings.get("collector_mode") or "auto"

            self.db.mark_channel_syncing(channel_id)
            started = time.perf_counter()

            try:
                batch = await self._fetch_batch(channel=channel, settings=settings)
                prepared = self.filter_and_prepare_posts(
                    batch.posts,
                    last_message_id=channel.get("last_message_id"),
                    initial_limit=int(channel.get("initial_limit") or DEFAULT_INITIAL_LIMIT),
                    tz_name=tz_name,
                )
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                return self.db.save_sync_result(
                    channel_id=channel_id,
                    resolved_title=batch.channel_title,
                    prepared_posts=prepared,
                    trigger_type=trigger_type,
                    source_mode=batch.source_mode,
                    duration_ms=elapsed_ms,
                )
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                err_text = str(exc) if isinstance(exc, CollectorError) else f"خطا در دریافت کانال: {exc}"
                return self.db.save_sync_error(
                    channel_id=channel_id,
                    error_message=err_text,
                    trigger_type=trigger_type,
                    source_mode=configured_mode,
                    duration_ms=elapsed_ms,
                )

    async def sync_all_active(self, *, trigger_type: str = "manual") -> Dict[str, Any]:
        channels = [
            c for c in self.db.list_channels()
            if c.get("is_active") and not c.get("is_demo")
        ]
        results: List[Dict[str, Any]] = []
        total_new = 0
        success_count = 0
        error_count = 0

        for idx, ch in enumerate(channels):
            if idx > 0:
                await asyncio.sleep(1.0)
            res = await self.sync_channel(int(ch["id"]), trigger_type=trigger_type)
            results.append(res)
            if res["status"] == "success":
                success_count += 1
                total_new += int(res["new_saved_count"])
            else:
                error_count += 1

        return {
            "checked_channels": len(channels),
            "success_count": success_count,
            "error_count": error_count,
            "total_new_posts": total_new,
            "results": results,
        }
