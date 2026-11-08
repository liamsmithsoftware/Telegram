from __future__ import annotations

import asyncio
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PasswordHashInvalidError,
    SessionPasswordNeededError,
)
from telethon.tl.patched import MessageService

from app.collectors.base import (
    CollectorError,
    FetchBatchResult,
    FetchedPost,
    build_telethon_proxy_dict,
)
from app.config import SESSION_PREFIX


class TelethonCollector:
    """
    Official MTProto collector powered by Telethon.
    Supports both public and private Telegram channels, exact min_id incremental
    fetching, interactive login from the web UI, and SOCKS5/HTTP proxies.
    """

    def __init__(self, session_prefix: Path = SESSION_PREFIX) -> None:
        self.session_prefix = Path(session_prefix)
        self._lock = asyncio.Lock()
        self._pending_phone_code_hash: Dict[str, str] = {}

    @property
    def session_file(self) -> Path:
        return Path(f"{self.session_prefix}.session")

    def has_credentials(self, settings: Dict[str, str]) -> bool:
        api_id = (settings.get("telethon_api_id") or "").strip()
        api_hash = (settings.get("telethon_api_hash") or "").strip()
        return bool(api_id.isdigit() and len(api_hash) >= 10)

    def has_session_file(self) -> bool:
        return self.session_file.exists()

    def _create_client(self, settings: Dict[str, str]) -> TelegramClient:
        api_id_str = (settings.get("telethon_api_id") or "").strip()
        api_hash = (settings.get("telethon_api_hash") or "").strip()
        if not api_id_str.isdigit() or not api_hash:
            raise CollectorError(
                "اطلاعات API تلگرام (api_id و api_hash) در بخش تنظیمات ثبت نشده است."
            )
        self.session_prefix.parent.mkdir(parents=True, exist_ok=True)
        proxy_cfg = build_telethon_proxy_dict(settings)
        return TelegramClient(
            str(self.session_prefix),
            int(api_id_str),
            api_hash,
            proxy=proxy_cfg,
            connection_retries=2,
            timeout=15,
        )

    async def get_auth_status(self, settings: Dict[str, str], check_network: bool = False) -> Dict[str, Any]:
        configured = self.has_credentials(settings)
        if not configured:
            return {
                "configured": False,
                "authorized": False,
                "session_exists": False,
                "account": None,
            }

        if not self.has_session_file():
            return {
                "configured": True,
                "authorized": False,
                "session_exists": False,
                "account": None,
            }

        if not check_network:
            return {
                "configured": True,
                "authorized": True,
                "session_exists": True,
                "account": settings.get("telethon_phone") or "متصل (نشست ذخیره شده)",
            }

        async with self._lock:
            client = self._create_client(settings)
            try:
                await client.connect()
                is_auth = await client.is_user_authorized()
                account_label = None
                if is_auth:
                    me = await client.get_me()
                    if me:
                        full_name = " ".join(filter(None, [me.first_name, me.last_name])).strip()
                        account_label = f"{full_name} (+{me.phone})" if me.phone else full_name
                return {
                    "configured": True,
                    "authorized": bool(is_auth),
                    "session_exists": True,
                    "account": account_label,
                }
            except Exception as exc:
                return {
                    "configured": True,
                    "authorized": False,
                    "session_exists": self.has_session_file(),
                    "account": None,
                    "error": str(exc),
                }
            finally:
                await client.disconnect()

    async def send_login_code(self, settings: Dict[str, str], phone: str) -> Dict[str, Any]:
        clean_phone = phone.strip().replace(" ", "")
        if not clean_phone:
            raise CollectorError("لطفاً شماره موبایل اکانت تلگرام را به همراه پیش‌شماره کشور (مثلاً +98912...) وارد کنید.")

        async with self._lock:
            client = self._create_client(settings)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    me = await client.get_me()
                    return {
                        "already_authorized": True,
                        "message": f"اکانت شما قبلاً متصل شده است ({me.first_name if me else clean_phone}).",
                    }
                sent = await client.send_code_request(clean_phone)
                self._pending_phone_code_hash[clean_phone] = sent.phone_code_hash
                return {
                    "already_authorized": False,
                    "code_sent": True,
                    "message": "کد تایید به تلگرام شما ارسال شد. لطفاً کد دریافتی را وارد کنید.",
                }
            except FloodWaitError as exc:
                raise CollectorError(f"محدودیت موقت تلگرام: لطفاً {exc.seconds} ثانیه دیگر تلاش کنید.") from exc
            except Exception as exc:
                raise CollectorError(f"خطا در ارسال کد تایید تلگرام: {exc}") from exc
            finally:
                await client.disconnect()

    async def verify_login_code(
        self,
        settings: Dict[str, str],
        phone: str,
        code: str,
        password: Optional[str] = None,
    ) -> Dict[str, Any]:
        clean_phone = phone.strip().replace(" ", "")
        clean_code = code.strip()
        phone_code_hash = self._pending_phone_code_hash.get(clean_phone)

        if not phone_code_hash and not password:
            raise CollectorError("ابتدا دکمه «ارسال کد تایید» را بزنید تا کد جدید ارسال شود.")

        async with self._lock:
            client = self._create_client(settings)
            try:
                await client.connect()
                try:
                    if clean_code and phone_code_hash:
                        await client.sign_in(
                            phone=clean_phone,
                            code=clean_code,
                            phone_code_hash=phone_code_hash,
                        )
                    elif password:
                        await client.sign_in(password=password)
                except SessionPasswordNeededError:
                    if not password:
                        return {
                            "authorized": False,
                            "requires_2fa": True,
                            "message": "اکانت شما تایید دو مرحله‌ای (رمز ابری) دارد. لطفاً رمز دو مرحله‌ای را وارد و تایید کنید.",
                        }
                    await client.sign_in(password=password)

                self._pending_phone_code_hash.pop(clean_phone, None)
                me = await client.get_me()
                name = " ".join(filter(None, [me.first_name, me.last_name])).strip() if me else clean_phone
                return {
                    "authorized": True,
                    "requires_2fa": False,
                    "account": name,
                    "message": f"اتصال به اکانت تلگرام ({name}) با موفقیت انجام شد.",
                }
            except PhoneCodeInvalidError as exc:
                raise CollectorError("کد واردشده نادرست است.") from exc
            except PhoneCodeExpiredError as exc:
                raise CollectorError("کد تایید منقضی شده است؛ دوباره درخواست کد دهید.") from exc
            except PasswordHashInvalidError as exc:
                raise CollectorError("رمز تایید دو مرحله‌ای اشتباه است.") from exc
            except Exception as exc:
                raise CollectorError(f"خطا در تایید ورود به تلگرام: {exc}") from exc
            finally:
                await client.disconnect()

    async def logout(self, settings: Dict[str, str]) -> Dict[str, Any]:
        async with self._lock:
            if self.has_credentials(settings) and self.has_session_file():
                client = self._create_client(settings)
                try:
                    await client.connect()
                    if await client.is_user_authorized():
                        await client.log_out()
                except Exception:
                    pass
                finally:
                    await client.disconnect()
            if self.session_file.exists():
                self.session_file.unlink(missing_ok=True)
        return {"logged_out": True, "message": "نشست Telethon با موفقیت خارج و پاک شد."}

    @staticmethod
    def _detect_telethon_media_type(msg: Any) -> str:
        if getattr(msg, "photo", None):
            return "photo"
        if getattr(msg, "video", None) or getattr(msg, "video_note", None):
            return "video"
        if getattr(msg, "voice", None):
            return "voice"
        if getattr(msg, "poll", None):
            return "poll"
        if getattr(msg, "document", None):
            return "document"
        return "text"

    @staticmethod
    def _build_post_url(entity: Any, channel_row: Dict[str, Any], message_id: int) -> str:
        username = getattr(entity, "username", None) or channel_row.get("username")
        if username:
            return f"https://t.me/{username}/{message_id}"
        entity_id = getattr(entity, "id", None)
        if entity_id:
            return f"https://t.me/c/{entity_id}/{message_id}"
        return f"{channel_row['canonical_url'].rstrip('/')}/{message_id}"

    async def fetch_channel_posts(
        self,
        *,
        channel: Dict[str, Any],
        settings: Dict[str, str],
    ) -> FetchBatchResult:
        if not self.has_credentials(settings) or not self.has_session_file():
            raise CollectorError(
                "نشست Telethon فعال نیست. لطفاً ابتدا در بخش تنظیمات با api_id، api_hash و شماره موبایل وارد شوید."
            )

        last_message_id: Optional[int] = channel.get("last_message_id")
        initial_limit = int(channel.get("initial_limit") or 10)

        target_ref: Any
        ch_key: str = channel["channel_key"]
        if ch_key.startswith("id:"):
            target_ref = int(ch_key.split(":", 1)[1])
        elif channel.get("username"):
            target_ref = channel["username"]
        else:
            target_ref = channel["canonical_url"]

        async with self._lock:
            client = self._create_client(settings)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    raise CollectorError(
                        "نشست Telethon منقضی شده یا احراز هویت نشده است. لطفاً مجدداً در تنظیمات وارد شوید."
                    )

                entity = await client.get_entity(target_ref)
                resolved_title = getattr(entity, "title", None) or channel.get("title")

                raw_messages = []
                if last_message_id is None:
                    # First fetch -> strictly fetch latest `initial_limit` (default 10) messages
                    fetched = await client.get_messages(entity, limit=initial_limit)
                    raw_messages = [m for m in reversed(list(fetched)) if not isinstance(m, MessageService)]
                else:
                    # Incremental fetch -> strictly messages with id > last_message_id in chronological order
                    async for msg in client.iter_messages(
                        entity,
                        min_id=int(last_message_id),
                        reverse=True,
                        limit=500,
                    ):
                        if not isinstance(msg, MessageService):
                            raw_messages.append(msg)

                posts: List[FetchedPost] = []
                for msg in raw_messages:
                    if msg.id is None:
                        continue
                    pub_dt = msg.date or None
                    if pub_dt is None:
                        continue
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)

                    mtype = self._detect_telethon_media_type(msg)
                    text = (msg.message or "").strip()
                    if not text:
                        text = f"[{mtype}]"

                    posts.append(
                        FetchedPost(
                            message_id=int(msg.id),
                            post_url=self._build_post_url(entity, channel, int(msg.id)),
                            published_at=pub_dt,
                            content=text,
                            media_type=mtype,
                            media_url=None,
                            views=int(msg.views) if getattr(msg, "views", None) is not None else None,
                        )
                    )

                posts.sort(key=lambda p: p.message_id)
                return FetchBatchResult(
                    channel_title=resolved_title,
                    posts=posts,
                    source_mode="telethon",
                )
            except CollectorError:
                raise
            except FloodWaitError as exc:
                raise CollectorError(
                    f"محدودیت نرخ درخواست تلگرام (FloodWait): لطفاً {exc.seconds} ثانیه صبر کنید."
                ) from exc
            except Exception as exc:
                raise CollectorError(f"خطا در دریافت کانال از طریق Telethon: {exc}") from exc
            finally:
                await client.disconnect()
