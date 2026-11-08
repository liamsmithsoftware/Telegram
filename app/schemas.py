from __future__ import annotations

from typing import Literal, Optional

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
