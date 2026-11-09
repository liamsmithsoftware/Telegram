from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ChannelCreateRequest(BaseModel):
    channel_input: str = Field(..., min_length=1, description="آدرس یا یوزرنیم کانال تلگرام")
    title: Optional[str] = Field(default=None, description="عنوان دلخواه کانال (اختیاری)")
    interval_value: float = Field(default=6.0, gt=0, description="مقدار بازه زمانی بررسی خودکار")
    interval_unit: Literal["minutes", "hours", "days"] = Field(default="hours")
    initial_limit: int = Field(default=10, ge=1, le=100, description="تعداد مطالب در اولین دریافت")
    is_active: bool = Field(default=True)
    fetch_now: bool = Field(default=True, description="آیا بلافاصله پس از افزودن، دریافت اولیه انجام شود؟")


class ChannelUpdateRequest(BaseModel):
    title: Optional[str] = None
    interval_value: Optional[float] = Field(default=None, gt=0)
    interval_unit: Optional[Literal["minutes", "hours", "days"]] = None
    initial_limit: Optional[int] = Field(default=None, ge=1, le=100)
    is_active: Optional[bool] = None


class ChannelResetRequest(BaseModel):
    delete_posts: bool = Field(default=False)


class SettingsUpdateRequest(BaseModel):
    collector_mode: Optional[Literal["auto", "web", "telethon"]] = None
    timezone: Optional[str] = None
    default_initial_limit: Optional[int] = Field(default=None, ge=1, le=100)
    telethon_api_id: Optional[str] = None
    telethon_api_hash: Optional[str] = None
    telethon_phone: Optional[str] = None
    proxy_enabled: Optional[bool] = None
    proxy_type: Optional[Literal["socks5", "http"]] = None
    proxy_host: Optional[str] = None
    proxy_port: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None


class TelethonSendCodeRequest(BaseModel):
    api_id: Optional[str] = None
    api_hash: Optional[str] = None
    phone: str = Field(..., min_length=5)


class TelethonVerifyCodeRequest(BaseModel):
    phone: str = Field(..., min_length=5)
    code: str = Field(default="")
    password: Optional[str] = None


class BulkDeleteRequest(BaseModel):
    """حذف گروهی مطالب: با فیلتر (کانال/تاریخ/نوع محتوا/جستجو) یا با انتخاب شناسه‌ها."""

    channel_id: Optional[int] = Field(default=None, description="شناسه کانال (خالی = همه کانال‌ها)")
    date_from: Optional[str] = Field(default=None, description="از تاریخ (شمسی یا میلادی)")
    date_to: Optional[str] = Field(default=None, description="تا تاریخ (شمسی یا میلادی)")
    media_type: Optional[str] = Field(default=None, description="نوع محتوا (all یا خالی = همه)")
    search: Optional[str] = Field(default=None, description="جستجو در متن یا آدرس مطلب")
    post_ids: Optional[List[int]] = Field(
        default=None,
        description="حذف فقط این شناسه‌های مطلب (انتخاب دستی از جدول آرشیو)",
    )
    reset_channel_cursors: bool = Field(
        default=True,
        description="شناسه آخرین پیام کانال‌های متأثر ریست شود تا دریافت بعدی از ابتدا انجام شود",
    )


class PurgeRequest(BaseModel):
    """پاک‌سازی کلی آرشیو."""

    keep_channels: bool = Field(
        default=True,
        description="کانال‌ها حفظ شوند (فقط مطالب پاک شود) یا همه چیز حذف شود",
    )


class BackupRestoreRequest(BaseModel):
    """بازیابی فایل پشتیبان (محتوای JSON که از همان فایل خوانده شده)."""

    mode: Literal["merge", "replace"] = Field(
        default="merge",
        description="merge: فقط افزودن/به‌روزرسانی — replace: پاک کردن فهرست و بازگردانی کامل",
    )
    restore_settings: bool = Field(default=True, description="تنظیمات موجود در فایل هم اعمال شود")
    overwrite_settings: bool = Field(
        default=False,
        description="اگر true باشد، تنظیمات فعلی با مقادیر فایل جایگزین می‌شوند",
    )
    payload: Dict[str, Any] = Field(..., description="محتوای کامل فایل پشتیبان")
