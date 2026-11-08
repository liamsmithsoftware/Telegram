from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

PERSIAN_DIGITS_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
INVISIBLE_CHARS_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]")
PUBLIC_USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{3,31}$")
INVITE_HASH_RE = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")

RESERVED_PATHS = {
    "share",
    "addstickers",
    "addemoji",
    "addtheme",
    "addlist",
    "proxy",
    "socks",
    "iv",
    "login",
    "contact",
    "setlanguage",
    "dl",
}

TELEGRAM_HOSTS = {
    "t.me",
    "www.t.me",
    "telegram.me",
    "www.telegram.me",
    "telegram.dog",
    "www.telegram.dog",
}


@dataclass(frozen=True)
class ParsedChannel:
    channel_key: str
    channel_input: str
    username: Optional[str]
    canonical_url: str
    web_preview_url: Optional[str]
    default_title: str
    is_private: bool


def normalize_digits(text: str) -> str:
    return text.translate(PERSIAN_DIGITS_MAP)


def clean_raw_input(raw: str) -> str:
    cleaned = INVISIBLE_CHARS_RE.sub("", raw or "")
    return normalize_digits(cleaned).strip()


def parse_channel_input(raw_input: str) -> ParsedChannel:
    """
    Parse any valid Telegram channel reference:
    - @channel_name or channel_name
    - https://t.me/channel_name or https://t.me/s/channel_name
    - https://t.me/channel_name/1234 (extracts channel_name)
    - https://t.me/+InviteHash or https://t.me/joinchat/InviteHash (private via Telethon)
    - https://t.me/c/1234567890/42 or -1001234567890 (private peer ID via Telethon)
    """
    cleaned = clean_raw_input(raw_input)
    if not cleaned:
        raise ValueError("لطفاً آدرس یا نام کاربری کانال تلگرام را وارد کنید.")

    # Direct numeric channel ID (e.g. -1001234567890)
    if re.fullmatch(r"-?\d{7,20}", cleaned):
        numeric_id = cleaned if cleaned.startswith("-") else f"-100{cleaned}"
        bare_digits = numeric_id[4:] if numeric_id.startswith("-100") else numeric_id.lstrip("-")
        return ParsedChannel(
            channel_key=f"id:{numeric_id}",
            channel_input=cleaned,
            username=None,
            canonical_url=f"https://t.me/c/{bare_digits}",
            web_preview_url=None,
            default_title=f"کانال خصوصی ({numeric_id})",
            is_private=True,
        )

    # @username or bare username
    if not ("/" in cleaned or "." in cleaned or cleaned.startswith("+")):
        candidate = cleaned.lstrip("@")
        if not PUBLIC_USERNAME_RE.fullmatch(candidate):
            raise ValueError(
                "نام کاربری کانال معتبر نیست. باید با حرف انگلیسی شروع شود و حداقل ۴ کاراکتر (حروف انگلیسی، عدد یا _) داشته باشد."
            )
        if candidate.lower() in RESERVED_PATHS:
            raise ValueError("این آدرس رزرو شده تلگرام است و نام کانال معتبر نیست.")
        return ParsedChannel(
            channel_key=candidate.lower(),
            channel_input=cleaned,
            username=candidate,
            canonical_url=f"https://t.me/{candidate}",
            web_preview_url=f"https://t.me/s/{candidate}",
            default_title=f"@{candidate}",
            is_private=False,
        )

    # Bare invite hash starting with +
    if cleaned.startswith("+") and INVITE_HASH_RE.fullmatch(cleaned[1:]):
        invite_hash = cleaned[1:]
        return ParsedChannel(
            channel_key=f"invite:{invite_hash}",
            channel_input=cleaned,
            username=None,
            canonical_url=f"https://t.me/+{invite_hash}",
            web_preview_url=None,
            default_title=f"کانال خصوصی (+{invite_hash[:8]}...)",
            is_private=True,
        )

    # URL-like input (with or without scheme)
    url_candidate = cleaned
    if not re.match(r"^https?://", url_candidate, flags=re.IGNORECASE):
        url_candidate = f"https://{url_candidate}"

    parsed = urlparse(url_candidate)
    host = (parsed.netloc or "").lower()
    if host not in TELEGRAM_HOSTS:
        raise ValueError(
            "دامنه لینک معتبر نیست. لطفاً لینکی از دامنه t.me یا telegram.me یا نام کاربری با @ وارد کنید."
        )

    segments = [seg for seg in (parsed.path or "").split("/") if seg]
    if not segments:
        raise ValueError("در لینک واردشده نام کانال مشخص نشده است.")

    first = segments[0]

    # Case 1: https://t.me/s/channel_name[/123]
    if first.lower() == "s":
        if len(segments) < 2:
            raise ValueError("در لینک پیش‌نمایش (t.me/s/...) نام کانال مشخص نشده است.")
        username = segments[1]
        return _build_public_channel(username, cleaned)

    # Case 2: https://t.me/+InviteHash
    if first.startswith("+"):
        invite_hash = first[1:]
        if not INVITE_HASH_RE.fullmatch(invite_hash):
            raise ValueError("لینک دعوت کانال خصوصی معتبر نیست.")
        return ParsedChannel(
            channel_key=f"invite:{invite_hash}",
            channel_input=cleaned,
            username=None,
            canonical_url=f"https://t.me/+{invite_hash}",
            web_preview_url=None,
            default_title=f"کانال خصوصی (+{invite_hash[:8]}...)",
            is_private=True,
        )

    # Case 3: https://t.me/joinchat/InviteHash
    if first.lower() == "joinchat":
        if len(segments) < 2 or not INVITE_HASH_RE.fullmatch(segments[1]):
            raise ValueError("لینک joinchat کانال خصوصی معتبر نیست.")
        invite_hash = segments[1]
        return ParsedChannel(
            channel_key=f"invite:{invite_hash}",
            channel_input=cleaned,
            username=None,
            canonical_url=f"https://t.me/+{invite_hash}",
            web_preview_url=None,
            default_title=f"کانال خصوصی (+{invite_hash[:8]}...)",
            is_private=True,
        )

    # Case 4: https://t.me/c/1234567890[/42]
    if first.lower() == "c":
        if len(segments) < 2 or not segments[1].isdigit():
            raise ValueError("لینک کانال خصوصی (t.me/c/...) معتبر نیست.")
        bare_id = segments[1]
        numeric_id = f"-100{bare_id}"
        return ParsedChannel(
            channel_key=f"id:{numeric_id}",
            channel_input=cleaned,
            username=None,
            canonical_url=f"https://t.me/c/{bare_id}",
            web_preview_url=None,
            default_title=f"کانال خصوصی ({bare_id})",
            is_private=True,
        )

    if first.lower() in RESERVED_PATHS:
        raise ValueError("این لینک مربوط به قابلیت‌های جانبی تلگرام است، نه آدرس یک کانال.")

    # Case 5: https://t.me/channel_name[/123]
    return _build_public_channel(first, cleaned)


def _build_public_channel(username: str, original_input: str) -> ParsedChannel:
    candidate = username.lstrip("@")
    if not PUBLIC_USERNAME_RE.fullmatch(candidate):
        raise ValueError(
            f"شناسه کانال «{candidate}» معتبر نیست. نام کاربری کانال عمومی باید بین ۴ تا ۳۲ کاراکتر انگلیسی/عدد/_ باشد."
        )
    if candidate.lower() in RESERVED_PATHS:
        raise ValueError("این آدرس رزرو شده تلگرام است و نام کانال معتبر نیست.")
    return ParsedChannel(
        channel_key=candidate.lower(),
        channel_input=original_input,
        username=candidate,
        canonical_url=f"https://t.me/{candidate}",
        web_preview_url=f"https://t.me/s/{candidate}",
        default_title=f"@{candidate}",
        is_private=False,
    )
