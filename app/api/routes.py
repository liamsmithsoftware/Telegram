from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from app.collectors.base import CollectorError
from app.collectors.manager import SyncManager
from app import config as app_config
from app.config import DEFAULT_TIMEZONE
from app.database import DatabaseManager
from app.schemas import (
    BulkDeleteRequest,
    ChannelCreateRequest,
    ChannelResetRequest,
    ChannelUpdateRequest,
    PurgeRequest,
    SettingsUpdateRequest,
    TelethonSendCodeRequest,
    TelethonVerifyCodeRequest,
)
from app.services.exporter import create_sqlite_export_snapshot, generate_excel_bytes
from app.services.scheduler import ChannelSchedulerService
from app.utils.channel_parser import normalize_digits, parse_channel_input
from app.utils.jalali import format_local_display, parse_filter_date_to_gregorian, utc_now

router = APIRouter(prefix="/api")

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def to_persian_number(value: Any) -> str:
    """اعداد را برای نمایش در پیام‌های فارسی تبدیل می‌کند."""
    return str(value).translate(_FA_DIGITS)


def _get_db(request: Request) -> DatabaseManager:
    return request.app.state.db


def _get_sync_manager(request: Request) -> SyncManager:
    return request.app.state.sync_manager


def _get_scheduler(request: Request) -> ChannelSchedulerService:
    return request.app.state.scheduler


def _enrich_channel(ch: Dict[str, Any], tz_name: str) -> Dict[str, Any]:
    out = dict(ch)
    out["is_active"] = bool(ch.get("is_active"))
    out["is_private"] = bool(ch.get("is_private"))
    out["is_demo"] = bool(ch.get("is_demo"))
    out["last_fetched_display"] = format_local_display(ch.get("last_fetched_at"), tz_name=tz_name)
    out["next_fetch_display"] = format_local_display(ch.get("next_fetch_at"), tz_name=tz_name)
    out["last_post_display"] = format_local_display(ch.get("last_post_at"), tz_name=tz_name)
    return out


# ------------------------------------------------------------------
# Overview & Stats
# ------------------------------------------------------------------
@router.get("/overview")
async def get_overview(request: Request) -> Dict[str, Any]:
    db = _get_db(request)
    sync_manager = _get_sync_manager(request)
    scheduler = _get_scheduler(request)

    settings = db.get_settings()
    tz_name = settings.get("timezone") or DEFAULT_TIMEZONE
    stats = db.get_dashboard_stats()
    stats["nearest_next_fetch_display"] = format_local_display(
        stats.get("nearest_next_fetch"), tz_name=tz_name
    )
    stats["latest_post_display"] = format_local_display(
        stats.get("latest_post_utc"), tz_name=tz_name
    )

    telethon_status = await sync_manager.telethon_collector.get_auth_status(
        settings, check_network=False
    )

    return {
        "stats": stats,
        "scheduler": scheduler.get_status(),
        "collector_mode": settings.get("collector_mode", "auto"),
        "timezone": tz_name,
        "proxy_enabled": settings.get("proxy_enabled") == "1",
        "telethon": telethon_status,
    }


# ------------------------------------------------------------------
# Channels Management
# ------------------------------------------------------------------
@router.get("/channels")
async def list_channels(request: Request) -> Dict[str, Any]:
    db = _get_db(request)
    tz_name = db.get_settings().get("timezone") or DEFAULT_TIMEZONE
    items = [_enrich_channel(ch, tz_name) for ch in db.list_channels()]
    return {"items": items}


@router.post("/channels")
async def create_channel(payload: ChannelCreateRequest, request: Request) -> Dict[str, Any]:
    db = _get_db(request)
    sync_manager = _get_sync_manager(request)
    tz_name = db.get_settings().get("timezone") or DEFAULT_TIMEZONE

    try:
        parsed = parse_channel_input(payload.channel_input)
        created = db.create_channel(
            parsed=parsed,
            interval_value=payload.interval_value,
            interval_unit=payload.interval_unit,
            initial_limit=payload.initial_limit,
            title=payload.title,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sync_result = None
    if payload.fetch_now:
        sync_result = await sync_manager.sync_channel(int(created["id"]), trigger_type="manual")
        refreshed = db.get_channel(int(created["id"]))
        if refreshed:
            created = refreshed

    return {
        "channel": _enrich_channel(created, tz_name),
        "sync_result": sync_result,
    }


@router.put("/channels/{channel_id}")
async def update_channel(
    channel_id: int,
    payload: ChannelUpdateRequest,
    request: Request,
) -> Dict[str, Any]:
    db = _get_db(request)
    tz_name = db.get_settings().get("timezone") or DEFAULT_TIMEZONE
    try:
        updated = db.update_channel(
            channel_id,
            title=payload.title,
            interval_value=payload.interval_value,
            interval_unit=payload.interval_unit,
            initial_limit=payload.initial_limit,
            is_active=payload.is_active,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"channel": _enrich_channel(updated, tz_name)}


@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: int, request: Request) -> Dict[str, Any]:
    db = _get_db(request)
    ok = db.delete_channel(channel_id)
    if not ok:
        raise HTTPException(status_code=404, detail="کانال مورد نظر یافت نشد.")
    return {"deleted": True, "channel_id": channel_id}


@router.post("/channels/sync-all")
async def sync_all_channels(request: Request) -> Dict[str, Any]:
    sync_manager = _get_sync_manager(request)
    return await sync_manager.sync_all_active(trigger_type="manual")


@router.post("/channels/{channel_id}/sync")
async def sync_single_channel(channel_id: int, request: Request) -> Dict[str, Any]:
    db = _get_db(request)
    sync_manager = _get_sync_manager(request)
    tz_name = db.get_settings().get("timezone") or DEFAULT_TIMEZONE

    try:
        result = await sync_manager.sync_channel(channel_id, trigger_type="manual")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    updated_ch = db.get_channel(channel_id)
    return {
        "sync_result": result,
        "channel": _enrich_channel(updated_ch, tz_name) if updated_ch else None,
    }


@router.post("/channels/{channel_id}/reset")
async def reset_channel_cursor(
    channel_id: int,
    payload: ChannelResetRequest,
    request: Request,
) -> Dict[str, Any]:
    db = _get_db(request)
    tz_name = db.get_settings().get("timezone") or DEFAULT_TIMEZONE
    try:
        updated = db.reset_channel_cursor(channel_id, delete_posts=payload.delete_posts)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"channel": _enrich_channel(updated, tz_name)}


# ------------------------------------------------------------------
# Posts Archive
# ------------------------------------------------------------------
@router.get("/posts")
async def list_posts(
    request: Request,
    channel_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    media_type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
) -> Dict[str, Any]:
    db = _get_db(request)
    tz_name = db.get_settings().get("timezone") or DEFAULT_TIMEZONE

    try:
        greg_from = parse_filter_date_to_gregorian(date_from)
        greg_to = parse_filter_date_to_gregorian(date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    res = db.list_posts(
        channel_id=channel_id,
        search=search,
        date_from_greg=greg_from,
        date_to_greg=greg_to,
        media_type=media_type,
        page=page,
        page_size=page_size,
    )
    for item in res["items"]:
        item["fetched_display"] = format_local_display(item.get("fetched_at"), tz_name=tz_name)
    return res


@router.delete("/posts/{post_id}")
async def delete_post(post_id: int, request: Request) -> Dict[str, Any]:
    db = _get_db(request)
    if not db.delete_post(post_id):
        raise HTTPException(status_code=404, detail="مطلب مورد نظر یافت نشد.")
    return {"deleted": True, "post_id": post_id}


@router.post("/posts/bulk-delete")
async def bulk_delete_posts(payload: BulkDeleteRequest, request: Request) -> Dict[str, Any]:
    """
    حذف گروهی مطالب:
    - بر اساس فیلتر (کانال، بازه تاریخ شمسی/میلادی، نوع محتوا، جستجو)
    - یا بر اساس انتخاب دستی `post_ids` از جدول آرشیو
    بدون هیچ فیلتری، تمام مطالب آرشیو حذف می‌شود.
    """
    db = _get_db(request)

    try:
        greg_from = parse_filter_date_to_gregorian(payload.date_from)
        greg_to = parse_filter_date_to_gregorian(payload.date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if greg_from and greg_to and greg_from > greg_to:
        raise HTTPException(status_code=400, detail="تاریخ شروع نمی‌تواند بعد از تاریخ پایان باشد.")

    if payload.channel_id is not None and not db.get_channel(int(payload.channel_id)):
        raise HTTPException(status_code=404, detail="کانال انتخاب‌شده یافت نشد.")

    if payload.post_ids is not None and len(payload.post_ids) == 0:
        raise HTTPException(
            status_code=400,
            detail="هیچ مطلبی برای حذف انتخاب نشده است. ابتدا در جدول آرشیو، ردیف‌ها را تیک بزنید.",
        )

    media_type = payload.media_type if payload.media_type and payload.media_type != "all" else None

    matched = db.count_posts_for_scope(
        channel_id=payload.channel_id,
        date_from_greg=greg_from,
        date_to_greg=greg_to,
        media_type=media_type,
        search=payload.search,
        post_ids=payload.post_ids,
    )
    result = db.delete_posts_by_scope(
        channel_id=payload.channel_id,
        date_from_greg=greg_from,
        date_to_greg=greg_to,
        media_type=media_type,
        search=payload.search,
        post_ids=payload.post_ids,
        reset_channel_cursors=payload.reset_channel_cursors,
    )

    if not result["deleted_posts"]:
        message = "هیچ مطلبی مطابق با شرایط انتخاب‌شده یافت نشد."
    elif payload.post_ids is not None:
        message = f"{to_persian_number(result['deleted_posts'])} مطلب انتخاب‌شده حذف شد."
    else:
        message = f"{to_persian_number(result['deleted_posts'])} مطلب حذف شد."

    return {
        **result,
        "matched_before_delete": matched,
        "message": message,
    }


@router.get("/posts/ids")
async def list_post_ids(
    request: Request,
    channel_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    media_type: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """شناسه همه مطالبی که با فیلتر فعلی مطابقت دارند (برای «انتخاب همه نتایج»)."""
    db = _get_db(request)
    try:
        greg_from = parse_filter_date_to_gregorian(date_from)
        greg_to = parse_filter_date_to_gregorian(date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    media = media_type if media_type and media_type != "all" else None
    posts = db.get_posts_for_export(
        channel_id=channel_id,
        search=search,
        date_from_greg=greg_from,
        date_to_greg=greg_to,
        media_type=media,
    )
    return {"ids": [int(p["id"]) for p in posts], "total": len(posts)}


@router.post("/posts/purge")
async def purge_archive(payload: PurgeRequest, request: Request) -> Dict[str, Any]:
    """پاک‌سازی کلی: همه مطالب و گزارش‌ها، با یا بدون کانال‌ها."""
    db = _get_db(request)
    result = db.purge_everything(keep_channels=payload.keep_channels)

    if payload.keep_channels:
        message = (
            f"تمام مطالب ({to_persian_number(result['deleted_posts'])} مورد) و گزارش‌ها پاک شد. "
            "کانال‌ها حفظ شدند و شناسه آخرین پیام آن‌ها ریست شد."
        )
    else:
        message = (
            f"همه چیز پاک شد: {to_persian_number(result['deleted_channels'])} کانال، "
            f"{to_persian_number(result['deleted_posts'])} مطلب و "
            f"{to_persian_number(result['deleted_logs'])} گزارش."
        )
    return {**result, "message": message}


# ------------------------------------------------------------------
# Fetch Logs
# ------------------------------------------------------------------
@router.get("/logs")
async def get_logs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    channel_id: Optional[int] = Query(default=None),
) -> Dict[str, Any]:
    db = _get_db(request)
    tz_name = db.get_settings().get("timezone") or DEFAULT_TIMEZONE
    logs = db.list_fetch_logs(limit=limit, channel_id=channel_id)
    for lg in logs:
        lg["created_display"] = format_local_display(lg.get("created_at"), tz_name=tz_name)
    return {"items": logs}


@router.delete("/logs")
async def clear_logs(request: Request) -> Dict[str, Any]:
    db = _get_db(request)
    removed = db.clear_fetch_logs()
    return {"cleared": removed}


# ------------------------------------------------------------------
# Exports: Excel (.xlsx) & SQLite (.sqlite)
# ------------------------------------------------------------------
@router.get("/exports/excel")
async def export_excel(
    request: Request,
    channel_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    media_type: Optional[str] = Query(default=None),
) -> Response:
    db = _get_db(request)
    tz_name = db.get_settings().get("timezone") or DEFAULT_TIMEZONE

    try:
        greg_from = parse_filter_date_to_gregorian(date_from)
        greg_to = parse_filter_date_to_gregorian(date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    posts = db.get_posts_for_export(
        channel_id=channel_id,
        search=search,
        date_from_greg=greg_from,
        date_to_greg=greg_to,
        media_type=media_type,
    )
    channels = db.list_channels()

    excel_bytes = generate_excel_bytes(posts=posts, channels=channels, tz_name=tz_name)
    stamp = utc_now().strftime("%Y%m%d_%H%M%S")
    filename = f"telegram_posts_{stamp}.xlsx"

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


@router.get("/exports/sqlite")
async def export_sqlite(
    request: Request,
    background_tasks: BackgroundTasks,
    filtered_only: bool = Query(default=False),
    channel_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    media_type: Optional[str] = Query(default=None),
) -> FileResponse:
    db = _get_db(request)

    filtered_ids = None
    if filtered_only:
        try:
            greg_from = parse_filter_date_to_gregorian(date_from)
            greg_to = parse_filter_date_to_gregorian(date_to)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        matching = db.get_posts_for_export(
            channel_id=channel_id,
            search=search,
            date_from_greg=greg_from,
            date_to_greg=greg_to,
            media_type=media_type,
        )
        filtered_ids = [int(p["id"]) for p in matching]

    snapshot_path = create_sqlite_export_snapshot(
        db,
        filtered_post_ids=filtered_ids,
        strip_sensitive_settings=True,
    )
    background_tasks.add_task(_unlink_quietly, snapshot_path)

    stamp = utc_now().strftime("%Y%m%d_%H%M%S")
    filename = f"telegram_collector_{stamp}.sqlite"

    return FileResponse(
        path=str(snapshot_path),
        media_type="application/vnd.sqlite3",
        filename=filename,
        headers={"Cache-Control": "no-store"},
    )


# ------------------------------------------------------------------
# Settings & Telethon Interactive Login
# ------------------------------------------------------------------
@router.get("/settings")
async def get_settings_endpoint(
    request: Request,
    check_telethon_network: bool = Query(default=False),
) -> Dict[str, Any]:
    db = _get_db(request)
    sync_manager = _get_sync_manager(request)
    raw = db.get_settings()

    telethon_status = await sync_manager.telethon_collector.get_auth_status(
        raw, check_network=check_telethon_network
    )

    return {
        "telethon_installed": app_config.TELETHON_INSTALLED,
        "settings": {
            "collector_mode": raw.get("collector_mode", "auto"),
            "timezone": raw.get("timezone", DEFAULT_TIMEZONE),
            "default_initial_limit": int(raw.get("default_initial_limit") or 10),
            "telethon_api_id": raw.get("telethon_api_id", ""),
            "telethon_api_hash_set": bool(raw.get("telethon_api_hash")),
            "telethon_phone": raw.get("telethon_phone", ""),
            "proxy_enabled": raw.get("proxy_enabled") == "1",
            "proxy_type": raw.get("proxy_type", "socks5"),
            "proxy_host": raw.get("proxy_host", ""),
            "proxy_port": raw.get("proxy_port", ""),
            "proxy_username": raw.get("proxy_username", ""),
            "proxy_password_set": bool(raw.get("proxy_password")),
        },
        "telethon": telethon_status,
    }


@router.put("/settings")
async def update_settings_endpoint(
    payload: SettingsUpdateRequest,
    request: Request,
) -> Dict[str, Any]:
    db = _get_db(request)
    updates: Dict[str, Any] = {}

    if payload.collector_mode is not None:
        updates["collector_mode"] = payload.collector_mode
    if payload.timezone is not None and payload.timezone.strip():
        updates["timezone"] = payload.timezone.strip()
    if payload.default_initial_limit is not None:
        updates["default_initial_limit"] = str(payload.default_initial_limit)
    if payload.telethon_api_id is not None:
        clean_id = normalize_digits(payload.telethon_api_id).strip()
        if clean_id and not clean_id.isdigit():
            raise HTTPException(status_code=400, detail="مقدار api_id باید فقط شامل عدد باشد.")
        updates["telethon_api_id"] = clean_id
    if payload.telethon_api_hash is not None and payload.telethon_api_hash != "********":
        updates["telethon_api_hash"] = payload.telethon_api_hash.strip()
    if payload.telethon_phone is not None:
        updates["telethon_phone"] = normalize_digits(payload.telethon_phone).strip()

    if payload.proxy_enabled is not None:
        updates["proxy_enabled"] = "1" if payload.proxy_enabled else "0"
    if payload.proxy_type is not None:
        updates["proxy_type"] = payload.proxy_type
    if payload.proxy_host is not None:
        updates["proxy_host"] = payload.proxy_host.strip()
    if payload.proxy_port is not None:
        clean_port = normalize_digits(payload.proxy_port).strip()
        if clean_port and (not clean_port.isdigit() or not (1 <= int(clean_port) <= 65535)):
            raise HTTPException(status_code=400, detail="پورت پروکسی باید عددی بین ۱ تا ۶۵۵۳۵ باشد.")
        updates["proxy_port"] = clean_port
    if payload.proxy_username is not None:
        updates["proxy_username"] = payload.proxy_username.strip()
    if payload.proxy_password is not None and payload.proxy_password != "********":
        updates["proxy_password"] = payload.proxy_password

    db.update_settings(updates)
    return await get_settings_endpoint(request, check_telethon_network=False)


@router.post("/telethon/send-code")
async def telethon_send_code(
    payload: TelethonSendCodeRequest,
    request: Request,
) -> Dict[str, Any]:
    db = _get_db(request)
    sync_manager = _get_sync_manager(request)

    updates: Dict[str, str] = {"telethon_phone": normalize_digits(payload.phone).strip()}
    if payload.api_id is not None and payload.api_id.strip():
        clean_id = normalize_digits(payload.api_id).strip()
        if not clean_id.isdigit():
            raise HTTPException(status_code=400, detail="مقدار api_id باید عددی باشد.")
        updates["telethon_api_id"] = clean_id
    if payload.api_hash is not None and payload.api_hash.strip() and payload.api_hash != "********":
        updates["telethon_api_hash"] = payload.api_hash.strip()

    settings = db.update_settings(updates)
    try:
        return await sync_manager.telethon_collector.send_login_code(
            settings=settings,
            phone=updates["telethon_phone"],
        )
    except CollectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/telethon/verify-code")
async def telethon_verify_code(
    payload: TelethonVerifyCodeRequest,
    request: Request,
) -> Dict[str, Any]:
    db = _get_db(request)
    sync_manager = _get_sync_manager(request)
    settings = db.get_settings()

    try:
        return await sync_manager.telethon_collector.verify_login_code(
            settings=settings,
            phone=normalize_digits(payload.phone).strip(),
            code=normalize_digits(payload.code).strip(),
            password=payload.password,
        )
    except CollectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/telethon/logout")
async def telethon_logout(request: Request) -> Dict[str, Any]:
    db = _get_db(request)
    sync_manager = _get_sync_manager(request)
    settings = db.get_settings()
    return await sync_manager.telethon_collector.logout(settings)


# ------------------------------------------------------------------
# Demo Seed / Clear (for instant UI & export testing)
# ------------------------------------------------------------------
@router.post("/demo/seed")
async def seed_demo(request: Request) -> Dict[str, Any]:
    db = _get_db(request)
    tz_name = db.get_settings().get("timezone") or DEFAULT_TIMEZONE
    res = db.seed_demo_data(tz_name=tz_name)
    return {
        "seeded": True,
        **res,
        "message": "داده‌های نمونه آزمایشی با موفقیت بارگذاری شد. اکنون می‌توانید فیلترها و خروجی Excel و SQLite را تست کنید.",
    }


@router.delete("/demo")
async def clear_demo(request: Request) -> Dict[str, Any]:
    db = _get_db(request)
    removed = db.clear_demo_data()
    return {
        "cleared_channels": removed,
        "message": "تمامی کانال‌ها و مطالب آزمایشی پاک‌سازی شدند.",
    }
