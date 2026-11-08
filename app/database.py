from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple

from app.config import DB_PATH, DEFAULT_INITIAL_LIMIT, DEFAULT_TIMEZONE
from app.utils.channel_parser import ParsedChannel
from app.utils.jalali import format_iso_utc, split_datetime, utc_now, utc_now_iso

DEFAULT_SETTINGS: Dict[str, str] = {
    "collector_mode": "auto",  # 'auto' | 'web' | 'telethon'
    "timezone": DEFAULT_TIMEZONE,
    "default_initial_limit": str(DEFAULT_INITIAL_LIMIT),
    "telethon_api_id": "",
    "telethon_api_hash": "",
    "telethon_phone": "",
    "proxy_enabled": "0",
    "proxy_type": "socks5",  # 'socks5' | 'http'
    "proxy_host": "",
    "proxy_port": "",
    "proxy_username": "",
    "proxy_password": "",
}


def compute_interval_minutes(interval_value: float, interval_unit: str) -> int:
    unit = (interval_unit or "hours").lower().strip()
    if interval_value <= 0:
        raise ValueError("مقدار بازه زمانی باید بزرگ‌تر از صفر باشد.")

    if unit == "minutes":
        minutes = round(interval_value)
    elif unit == "hours":
        minutes = round(interval_value * 60)
    elif unit == "days":
        minutes = round(interval_value * 1440)
    else:
        raise ValueError("واحد زمانی معتبر نیست (فقط minutes، hours یا days مجاز است).")

    if minutes < 1:
        minutes = 1
    if minutes > 60 * 24 * 365:
        raise ValueError("بازه زمانی نمی‌تواند بیشتر از ۳۶۵ روز باشد.")
    return int(minutes)


class DatabaseManager:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        with self._write_lock:
            conn = self._connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def init_db(self) -> None:
        with self.transaction() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_key TEXT NOT NULL UNIQUE,
                    channel_input TEXT NOT NULL,
                    username TEXT,
                    canonical_url TEXT NOT NULL,
                    web_preview_url TEXT,
                    title TEXT NOT NULL,
                    is_private INTEGER NOT NULL DEFAULT 0,
                    interval_value REAL NOT NULL DEFAULT 6,
                    interval_unit TEXT NOT NULL DEFAULT 'hours',
                    interval_minutes INTEGER NOT NULL DEFAULT 360,
                    initial_limit INTEGER NOT NULL DEFAULT 10,
                    last_message_id INTEGER,
                    last_post_url TEXT,
                    last_post_at TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    is_demo INTEGER NOT NULL DEFAULT 0,
                    last_fetched_at TEXT,
                    next_fetch_at TEXT,
                    last_status TEXT NOT NULL DEFAULT 'pending',
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
                    channel_username TEXT NOT NULL,
                    channel_title TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    post_url TEXT NOT NULL,
                    published_date TEXT NOT NULL,
                    published_jalali_date TEXT NOT NULL,
                    published_time TEXT NOT NULL,
                    published_at_utc TEXT NOT NULL,
                    content TEXT NOT NULL,
                    media_type TEXT NOT NULL DEFAULT 'text',
                    media_url TEXT,
                    views INTEGER,
                    fetched_at TEXT NOT NULL,
                    UNIQUE(channel_id, message_id)
                );

                CREATE INDEX IF NOT EXISTS idx_posts_channel_msg
                    ON posts(channel_id, message_id DESC);
                CREATE INDEX IF NOT EXISTS idx_posts_published_utc
                    ON posts(published_at_utc DESC);
                CREATE INDEX IF NOT EXISTS idx_posts_published_date
                    ON posts(published_date);

                CREATE TABLE IF NOT EXISTS fetch_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER REFERENCES channels(id) ON DELETE CASCADE,
                    channel_title TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    source_mode TEXT NOT NULL,
                    fetched_count INTEGER NOT NULL DEFAULT 0,
                    new_saved_count INTEGER NOT NULL DEFAULT 0,
                    previous_last_message_id INTEGER,
                    new_last_message_id INTEGER,
                    status TEXT NOT NULL,
                    message TEXT,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_fetch_logs_created
                    ON fetch_logs(created_at DESC);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE VIEW IF NOT EXISTS vw_posts_export AS
                SELECT
                    p.id AS post_row_id,
                    c.title AS channel_title,
                    c.canonical_url AS channel_url,
                    p.message_id AS telegram_message_id,
                    p.post_url AS post_url,
                    p.published_jalali_date AS published_jalali_date,
                    p.published_date AS published_gregorian_date,
                    p.published_time AS published_time,
                    p.published_at_utc AS published_at_utc,
                    p.media_type AS media_type,
                    p.views AS views,
                    p.content AS content,
                    p.fetched_at AS fetched_at
                FROM posts p
                JOIN channels c ON c.id = p.channel_id
                ORDER BY p.published_at_utc DESC, p.message_id DESC;
                """
            )
            for k, v in DEFAULT_SETTINGS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (k, v),
                )

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def get_settings(self) -> Dict[str, str]:
        with self.connection() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        merged = dict(DEFAULT_SETTINGS)
        for row in rows:
            merged[row["key"]] = row["value"]
        return merged

    def update_settings(self, updates: Dict[str, Any]) -> Dict[str, str]:
        with self.transaction() as conn:
            for key, val in updates.items():
                if key in DEFAULT_SETTINGS and val is not None:
                    conn.execute(
                        """
                        INSERT INTO settings (key, value) VALUES (?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value
                        """,
                        (key, str(val)),
                    )
        return self.get_settings()

    # ------------------------------------------------------------------
    # Channels CRUD
    # ------------------------------------------------------------------
    def create_channel(
        self,
        parsed: ParsedChannel,
        interval_value: float = 6.0,
        interval_unit: str = "hours",
        initial_limit: int = DEFAULT_INITIAL_LIMIT,
        title: Optional[str] = None,
        is_active: bool = True,
        is_demo: bool = False,
    ) -> Dict[str, Any]:
        interval_minutes = compute_interval_minutes(interval_value, interval_unit)
        if initial_limit < 1 or initial_limit > 100:
            raise ValueError("تعداد پست‌های دریافت اولیه باید بین ۱ تا ۱۰۰ باشد.")

        now_dt = utc_now()
        now_iso = format_iso_utc(now_dt)
        next_iso = format_iso_utc(now_dt + timedelta(minutes=interval_minutes)) if is_active else None

        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT id FROM channels WHERE channel_key = ?",
                (parsed.channel_key,),
            ).fetchone()
            if existing:
                raise ValueError("این کانال قبلاً در لیست برنامه ثبت شده است.")

            cur = conn.execute(
                """
                INSERT INTO channels (
                    channel_key, channel_input, username, canonical_url, web_preview_url,
                    title, is_private, interval_value, interval_unit, interval_minutes,
                    initial_limit, is_active, is_demo, next_fetch_at, last_status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    parsed.channel_key,
                    parsed.channel_input,
                    parsed.username,
                    parsed.canonical_url,
                    parsed.web_preview_url,
                    (title or parsed.default_title).strip(),
                    1 if parsed.is_private else 0,
                    float(interval_value),
                    interval_unit.lower().strip(),
                    interval_minutes,
                    int(initial_limit),
                    1 if is_active else 0,
                    1 if is_demo else 0,
                    next_iso,
                    now_iso,
                    now_iso,
                ),
            )
            channel_id = int(cur.lastrowid)

        channel = self.get_channel(channel_id)
        assert channel is not None
        return channel

    def get_channel(self, channel_id: int) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT
                    c.*,
                    COUNT(p.id) AS posts_count
                FROM channels c
                LEFT JOIN posts p ON p.channel_id = c.id
                WHERE c.id = ?
                GROUP BY c.id
                """,
                (channel_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_channels(self) -> List[Dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.*,
                    COUNT(p.id) AS posts_count
                FROM channels c
                LEFT JOIN posts p ON p.channel_id = c.id
                GROUP BY c.id
                ORDER BY c.id DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def update_channel(
        self,
        channel_id: int,
        *,
        title: Optional[str] = None,
        interval_value: Optional[float] = None,
        interval_unit: Optional[str] = None,
        initial_limit: Optional[int] = None,
        is_active: Optional[bool] = None,
    ) -> Dict[str, Any]:
        current = self.get_channel(channel_id)
        if not current:
            raise LookupError("کانال مورد نظر یافت نشد.")

        new_title = title.strip() if title is not None and title.strip() else current["title"]
        new_val = float(interval_value) if interval_value is not None else float(current["interval_value"])
        new_unit = interval_unit.lower().strip() if interval_unit is not None else current["interval_unit"]
        new_minutes = compute_interval_minutes(new_val, new_unit)

        new_limit = int(initial_limit) if initial_limit is not None else int(current["initial_limit"])
        if new_limit < 1 or new_limit > 100:
            raise ValueError("تعداد پست‌های دریافت اولیه باید بین ۱ تا ۱۰۰ باشد.")

        new_active = bool(is_active) if is_active is not None else bool(current["is_active"])
        now_dt = utc_now()
        now_iso = format_iso_utc(now_dt)

        if not new_active:
            next_fetch = None
        else:
            # Recalculate next_fetch_at relative to last_fetched_at (if available) or now
            if current["last_fetched_at"]:
                try:
                    base_dt = datetime.fromisoformat(current["last_fetched_at"].replace("Z", "+00:00"))
                    candidate_dt = base_dt + timedelta(minutes=new_minutes)
                    if candidate_dt < now_dt:
                        candidate_dt = now_dt + timedelta(seconds=5)
                    next_fetch = format_iso_utc(candidate_dt)
                except ValueError:
                    next_fetch = format_iso_utc(now_dt + timedelta(minutes=new_minutes))
            else:
                next_fetch = format_iso_utc(now_dt + timedelta(minutes=new_minutes))

        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE channels
                SET title = ?,
                    interval_value = ?,
                    interval_unit = ?,
                    interval_minutes = ?,
                    initial_limit = ?,
                    is_active = ?,
                    next_fetch_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    new_title,
                    new_val,
                    new_unit,
                    new_minutes,
                    new_limit,
                    1 if new_active else 0,
                    next_fetch,
                    now_iso,
                    channel_id,
                ),
            )
        updated = self.get_channel(channel_id)
        assert updated is not None
        return updated

    def delete_channel(self, channel_id: int) -> bool:
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
            return cur.rowcount > 0

    def reset_channel_cursor(self, channel_id: int, delete_posts: bool = False) -> Dict[str, Any]:
        current = self.get_channel(channel_id)
        if not current:
            raise LookupError("کانال مورد نظر یافت نشد.")
        now_iso = utc_now_iso()
        with self.transaction() as conn:
            if delete_posts:
                conn.execute("DELETE FROM posts WHERE channel_id = ?", (channel_id,))
            conn.execute(
                """
                UPDATE channels
                SET last_message_id = NULL,
                    last_post_url = NULL,
                    last_post_at = NULL,
                    last_status = 'pending',
                    last_error = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now_iso, channel_id),
            )
        updated = self.get_channel(channel_id)
        assert updated is not None
        return updated

    def mark_channel_syncing(self, channel_id: int) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE channels SET last_status = 'syncing', updated_at = ? WHERE id = ?",
                (utc_now_iso(), channel_id),
            )

    def get_due_channels(self, now_iso: Optional[str] = None) -> List[Dict[str, Any]]:
        ref_iso = now_iso or utc_now_iso()
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM channels
                WHERE is_active = 1
                  AND is_demo = 0
                  AND (next_fetch_at IS NULL OR next_fetch_at <= ?)
                ORDER BY COALESCE(next_fetch_at, '') ASC, id ASC
                """,
                (ref_iso,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Posts Storage & Deduplication
    # ------------------------------------------------------------------
    def save_sync_result(
        self,
        *,
        channel_id: int,
        resolved_title: Optional[str],
        prepared_posts: List[Dict[str, Any]],
        trigger_type: str,
        source_mode: str,
        duration_ms: int,
    ) -> Dict[str, Any]:
        """
        Atomically inserts new posts (skipping duplicates via UNIQUE(channel_id, message_id)),
        advances last_message_id, schedules next_fetch_at, and records a fetch_log entry.
        """
        now_dt = utc_now()
        now_iso = format_iso_utc(now_dt)

        with self.transaction() as conn:
            ch_row = conn.execute(
                "SELECT * FROM channels WHERE id = ?", (channel_id,)
            ).fetchone()
            if not ch_row:
                raise LookupError("کانال یافت نشد.")

            prev_last_id: Optional[int] = ch_row["last_message_id"]
            channel_title = (resolved_title or ch_row["title"] or "").strip() or ch_row["title"]
            channel_username = ch_row["username"] or ch_row["channel_key"]

            # Sort chronologically (oldest -> newest) before insertion
            sorted_posts = sorted(prepared_posts, key=lambda item: int(item["message_id"]))

            inserted_count = 0
            max_msg_id = prev_last_id
            latest_post_url = ch_row["last_post_url"]
            latest_post_at = ch_row["last_post_at"]

            for post in sorted_posts:
                msg_id = int(post["message_id"])
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO posts (
                        channel_id, channel_username, channel_title, message_id,
                        post_url, published_date, published_jalali_date, published_time,
                        published_at_utc, content, media_type, media_url, views, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        channel_id,
                        channel_username,
                        channel_title,
                        msg_id,
                        post["post_url"],
                        post["published_date"],
                        post["published_jalali_date"],
                        post["published_time"],
                        post["published_at_utc"],
                        post["content"],
                        post.get("media_type") or "text",
                        post.get("media_url"),
                        post.get("views"),
                        now_iso,
                    ),
                )
                if cur.rowcount > 0:
                    inserted_count += 1

                if max_msg_id is None or msg_id > max_msg_id:
                    max_msg_id = msg_id
                    latest_post_url = post["post_url"]
                    latest_post_at = post["published_at_utc"]

            # Keep channel_title synchronized across existing posts if updated
            if channel_title != ch_row["title"]:
                conn.execute(
                    "UPDATE posts SET channel_title = ? WHERE channel_id = ?",
                    (channel_title, channel_id),
                )

            interval_minutes = int(ch_row["interval_minutes"])
            next_fetch_at = (
                format_iso_utc(now_dt + timedelta(minutes=interval_minutes))
                if ch_row["is_active"]
                else None
            )

            conn.execute(
                """
                UPDATE channels
                SET title = ?,
                    last_message_id = ?,
                    last_post_url = ?,
                    last_post_at = ?,
                    last_fetched_at = ?,
                    next_fetch_at = ?,
                    last_status = 'ok',
                    last_error = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    channel_title,
                    max_msg_id,
                    latest_post_url,
                    latest_post_at,
                    now_iso,
                    next_fetch_at,
                    now_iso,
                    channel_id,
                ),
            )

            if inserted_count > 0:
                log_msg = f"{inserted_count} مطلب جدید دریافت و ذخیره شد."
            else:
                log_msg = "بررسی انجام شد؛ مطلب جدیدی نسبت به آخرین شناسه منتشر نشده بود."

            conn.execute(
                """
                INSERT INTO fetch_logs (
                    channel_id, channel_title, trigger_type, source_mode,
                    fetched_count, new_saved_count, previous_last_message_id,
                    new_last_message_id, status, message, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'success', ?, ?, ?)
                """,
                (
                    channel_id,
                    channel_title,
                    trigger_type,
                    source_mode,
                    len(sorted_posts),
                    inserted_count,
                    prev_last_id,
                    max_msg_id,
                    log_msg,
                    int(duration_ms),
                    now_iso,
                ),
            )

        return {
            "channel_id": channel_id,
            "channel_title": channel_title,
            "fetched_count": len(sorted_posts),
            "new_saved_count": inserted_count,
            "previous_last_message_id": prev_last_id,
            "new_last_message_id": max_msg_id,
            "status": "success",
            "message": log_msg,
        }

    def save_sync_error(
        self,
        *,
        channel_id: int,
        error_message: str,
        trigger_type: str,
        source_mode: str,
        duration_ms: int,
    ) -> Dict[str, Any]:
        now_dt = utc_now()
        now_iso = format_iso_utc(now_dt)

        with self.transaction() as conn:
            ch_row = conn.execute(
                "SELECT * FROM channels WHERE id = ?", (channel_id,)
            ).fetchone()
            if not ch_row:
                raise LookupError("کانال یافت نشد.")

            retry_minutes = min(int(ch_row["interval_minutes"]), 15)
            next_fetch_at = (
                format_iso_utc(now_dt + timedelta(minutes=max(1, retry_minutes)))
                if ch_row["is_active"]
                else None
            )

            conn.execute(
                """
                UPDATE channels
                SET last_fetched_at = ?,
                    next_fetch_at = ?,
                    last_status = 'error',
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now_iso, next_fetch_at, error_message, now_iso, channel_id),
            )

            conn.execute(
                """
                INSERT INTO fetch_logs (
                    channel_id, channel_title, trigger_type, source_mode,
                    fetched_count, new_saved_count, previous_last_message_id,
                    new_last_message_id, status, message, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, 0, 0, ?, ?, 'error', ?, ?, ?)
                """,
                (
                    channel_id,
                    ch_row["title"],
                    trigger_type,
                    source_mode,
                    ch_row["last_message_id"],
                    ch_row["last_message_id"],
                    error_message,
                    int(duration_ms),
                    now_iso,
                ),
            )

        return {
            "channel_id": channel_id,
            "channel_title": ch_row["title"],
            "fetched_count": 0,
            "new_saved_count": 0,
            "previous_last_message_id": ch_row["last_message_id"],
            "new_last_message_id": ch_row["last_message_id"],
            "status": "error",
            "message": error_message,
        }

    # ------------------------------------------------------------------
    # Querying Posts & Logs
    # ------------------------------------------------------------------
    def _build_post_filters(
        self,
        *,
        channel_id: Optional[int] = None,
        search: Optional[str] = None,
        date_from_greg: Optional[str] = None,
        date_to_greg: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> Tuple[str, List[Any]]:
        clauses: List[str] = []
        params: List[Any] = []

        if channel_id is not None:
            clauses.append("p.channel_id = ?")
            params.append(int(channel_id))

        if search and search.strip():
            q = f"%{search.strip()}%"
            clauses.append("(p.content LIKE ? OR p.channel_title LIKE ? OR p.post_url LIKE ?)")
            params.extend([q, q, q])

        if date_from_greg:
            clauses.append("p.published_date >= ?")
            params.append(date_from_greg)

        if date_to_greg:
            clauses.append("p.published_date <= ?")
            params.append(date_to_greg)

        if media_type and media_type.strip() and media_type != "all":
            clauses.append("p.media_type = ?")
            params.append(media_type.strip())

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where_sql, params

    def list_posts(
        self,
        *,
        channel_id: Optional[int] = None,
        search: Optional[str] = None,
        date_from_greg: Optional[str] = None,
        date_to_greg: Optional[str] = None,
        media_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 25,
    ) -> Dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(200, int(page_size)))
        offset = (page - 1) * page_size

        where_sql, params = self._build_post_filters(
            channel_id=channel_id,
            search=search,
            date_from_greg=date_from_greg,
            date_to_greg=date_to_greg,
            media_type=media_type,
        )

        with self.connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM posts p {where_sql}",
                params,
            ).fetchone()["cnt"]

            rows = conn.execute(
                f"""
                SELECT
                    p.*,
                    c.canonical_url AS channel_url
                FROM posts p
                JOIN channels c ON c.id = p.channel_id
                {where_sql}
                ORDER BY p.published_at_utc DESC, p.message_id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()

        total_pages = max(1, (total + page_size - 1) // page_size)
        return {
            "items": [dict(r) for r in rows],
            "total": int(total),
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def get_posts_for_export(
        self,
        *,
        channel_id: Optional[int] = None,
        search: Optional[str] = None,
        date_from_greg: Optional[str] = None,
        date_to_greg: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        where_sql, params = self._build_post_filters(
            channel_id=channel_id,
            search=search,
            date_from_greg=date_from_greg,
            date_to_greg=date_to_greg,
            media_type=media_type,
        )
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    p.*,
                    c.canonical_url AS channel_url
                FROM posts p
                JOIN channels c ON c.id = p.channel_id
                {where_sql}
                ORDER BY p.published_at_utc DESC, p.message_id DESC
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_post(self, post_id: int) -> bool:
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
            return cur.rowcount > 0

    def list_fetch_logs(self, limit: int = 100, channel_id: Optional[int] = None) -> List[Dict[str, Any]]:
        limit = max(1, min(500, int(limit)))
        with self.connection() as conn:
            if channel_id is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM fetch_logs
                    WHERE channel_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (int(channel_id), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM fetch_logs ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def clear_fetch_logs(self) -> int:
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM fetch_logs")
            return cur.rowcount

    # ------------------------------------------------------------------
    # Dashboard Stats & SQLite Backup Export
    # ------------------------------------------------------------------
    def get_dashboard_stats(self) -> Dict[str, Any]:
        with self.connection() as conn:
            ch_stats = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_channels,
                    SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active_channels,
                    SUM(CASE WHEN is_demo = 1 THEN 1 ELSE 0 END) AS demo_channels,
                    MIN(CASE WHEN is_active = 1 THEN next_fetch_at ELSE NULL END) AS nearest_next_fetch
                FROM channels
                """
            ).fetchone()

            post_stats = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_posts,
                    MAX(published_at_utc) AS latest_post_utc,
                    MAX(fetched_at) AS latest_fetched_utc
                FROM posts
                """
            ).fetchone()

        db_size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "total_channels": int(ch_stats["total_channels"] or 0),
            "active_channels": int(ch_stats["active_channels"] or 0),
            "demo_channels": int(ch_stats["demo_channels"] or 0),
            "nearest_next_fetch": ch_stats["nearest_next_fetch"],
            "total_posts": int(post_stats["total_posts"] or 0),
            "latest_post_utc": post_stats["latest_post_utc"],
            "latest_fetched_utc": post_stats["latest_fetched_utc"],
            "db_size_bytes": db_size_bytes,
        }

    def backup_sqlite_to_file(self, target_path: Path) -> Path:
        """
        Creates a clean, self-contained, unlocked SQLite snapshot using sqlite3's
        online backup API so it can be downloaded safely even during active writes.
        """
        target_path = Path(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            target_path.unlink()

        with self._write_lock:
            src_conn = self._connect()
            dst_conn = sqlite3.connect(str(target_path))
            try:
                src_conn.backup(dst_conn)
                # Ensure single-file portability (no WAL sidecars needed by external SQLite viewers)
                dst_conn.execute("PRAGMA journal_mode = DELETE;")
                dst_conn.commit()
            finally:
                dst_conn.close()
                src_conn.close()
        return target_path

    # ------------------------------------------------------------------
    # Demo Data Helper (for offline testing of UI, filters, Excel & SQLite exports)
    # ------------------------------------------------------------------
    def seed_demo_data(self, tz_name: str = DEFAULT_TIMEZONE) -> Dict[str, int]:
        from app.utils.channel_parser import parse_channel_input

        demo_specs = [
            {
                "input": "https://t.me/tech_farsi_demo",
                "title": "فناوری و هوش مصنوعی (نمونه آزمایشی)",
                "interval_value": 4,
                "interval_unit": "hours",
                "base_msg_id": 2401,
                "posts": [
                    ("معرفی نسل جدید مدل‌های زبانی سبک برای اجرا روی سیستم‌های محلی با مصرف رم کمتر از ۸ گیگابایت.", "photo", 14200),
                    ("راهنمای بهینه‌سازی پایگاه داده SQLite در حالت WAL برای پردازش همزمان هزاران رکورد در ثانیه.", "text", 9850),
                    ("انتشار نسخه جدید پایتون با بهبود چشمگیر سرعت در پردازش‌های ناهمگام (AsyncIO).", "document", 18400),
                    ("مقایسه جامع ابزارهای زمان‌بندی خودکار وظایف در بک‌اندهای مدرن وب.", "text", 7600),
                    ("پنج نکته کلیدی امنیت اطلاعات هنگام استفاده از APIهای پیام‌رسان‌ها.", "photo", 11300),
                    ("ویدیوی آموزشی ساخت داشبوردهای تحلیلی و گزارش‌گیری خودکار با فرمت اکسل.", "video", 21500),
                    ("گزارش هفتگی تحولات بازار ابری و زیرساخت‌های متن‌باز در سال جاری.", "text", 8900),
                    ("بررسی معماری میکروسرویس در برابر یکپارچه ماژولار برای تیم‌های توسعه کوچک.", "text", 6400),
                    ("ابزارهای پیشنهادی برای مانیتورینگ سرویس‌های لینوکسی و مدیریت لاگ‌ها.", "photo", 10200),
                    ("جمع‌بندی رویداد توسعه‌دهندگان نرم‌افزارهای آزاد و مهم‌ترین پروژه‌های معرفی‌شده.", "text", 15900),
                ],
            },
            {
                "input": "https://t.me/eghtesad_rooz_demo",
                "title": "نبض اقتصاد و بازار (نمونه آزمایشی)",
                "interval_value": 1,
                "interval_unit": "days",
                "base_msg_id": 8910,
                "posts": [
                    ("خلاصه وضعیت بازارهای جهانی در آغاز معاملات هفتگی و تغییر شاخص‌های کلیدی.", "text", 31200),
                    ("تحلیل نموداری روند تقاضای انرژی و تاثیر آن بر صنایع پتروشیمی و فلزات.", "photo", 27400),
                    ("فایل PDF گزارش آماری شاخص مدیران خرید (PMI) در بخش تولید و خدمات.", "document", 19800),
                    ("بررسی راهکارهای نوین فین‌تک در تسویه سریع مبادلات تجاری خرد و کلان.", "text", 22100),
                    ("جمع‌بندی نرخ‌های مرجع بانکی و اطلاعیه‌های جدید سامانه مبادله.", "text", 41500),
                ],
            },
        ]

        created_channels = 0
        inserted_posts = 0
        now_dt = utc_now()

        for ch_idx, spec in enumerate(demo_specs):
            parsed = parse_channel_input(spec["input"])
            with self.connection() as conn:
                existing = conn.execute(
                    "SELECT id FROM channels WHERE channel_key = ?",
                    (parsed.channel_key,),
                ).fetchone()

            if existing:
                ch_id = int(existing["id"])
            else:
                ch = self.create_channel(
                    parsed=parsed,
                    interval_value=spec["interval_value"],
                    interval_unit=spec["interval_unit"],
                    initial_limit=10,
                    title=spec["title"],
                    is_active=False,  # Demo channels stay paused so scheduler won't hit fake URLs
                    is_demo=True,
                )
                ch_id = int(ch["id"])
                created_channels += 1

            prepared: List[Dict[str, Any]] = []
            total_items = len(spec["posts"])
            for idx, (text_body, mtype, views) in enumerate(spec["posts"]):
                msg_id = spec["base_msg_id"] + idx
                post_dt = now_dt - timedelta(hours=(total_items - idx) * 3 + ch_idx * 2, minutes=idx * 7)
                dt_parts = split_datetime(post_dt, tz_name=tz_name)
                prepared.append(
                    {
                        "message_id": msg_id,
                        "post_url": f"https://t.me/{parsed.username}/{msg_id}",
                        "published_date": dt_parts.published_date,
                        "published_jalali_date": dt_parts.published_jalali_date,
                        "published_time": dt_parts.published_time,
                        "published_at_utc": dt_parts.published_at_utc,
                        "content": text_body,
                        "media_type": mtype,
                        "media_url": None,
                        "views": views,
                    }
                )

            res = self.save_sync_result(
                channel_id=ch_id,
                resolved_title=spec["title"],
                prepared_posts=prepared,
                trigger_type="demo",
                source_mode="demo",
                duration_ms=42,
            )
            inserted_posts += int(res["new_saved_count"])

        return {"created_channels": created_channels, "inserted_posts": inserted_posts}

    def clear_demo_data(self) -> int:
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM channels WHERE is_demo = 1")
            return cur.rowcount
