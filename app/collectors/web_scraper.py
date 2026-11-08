from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup, Tag

from app.collectors.base import (
    CollectorError,
    FetchBatchResult,
    FetchedPost,
    build_httpx_proxy_url,
)

BG_IMAGE_URL_RE = re.compile(r"url\(['\"]?(https?://[^'\")]+)['\"]?\)")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
}

MEDIA_FALLBACK_LABELS = {
    "photo": "[تصویر بدون متن]",
    "video": "[ویدیو بدون متن]",
    "voice": "[پیام صوتی]",
    "document": "[فایل پیوست]",
    "poll": "[نظرسنجی]",
    "text": "[مطلب بدون متن]",
}


def parse_views_count(raw_views: Optional[str]) -> Optional[int]:
    if not raw_views:
        return None
    text = raw_views.strip().upper().replace(",", "").replace(" ", "")
    if not text:
        return None
    try:
        if text.endswith("K"):
            return int(float(text[:-1]) * 1_000)
        if text.endswith("M"):
            return int(float(text[:-1]) * 1_000_000)
        if text.isdigit():
            return int(text)
    except ValueError:
        return None
    return None


def _extract_clean_text(element: Tag) -> str:
    node = copy.copy(element)
    for br in node.find_all("br"):
        br.replace_with("\n")
    raw_text = node.get_text()
    # Normalize line endings and collapse 3+ consecutive newlines
    lines = [line.rstrip() for line in raw_text.replace("\r\n", "\n").split("\n")]
    joined = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", joined)


def _detect_media(msg_el: Tag) -> Tuple[str, Optional[str], Optional[str]]:
    """Returns (media_type, media_url, attachment_title)."""
    photo_wrap = msg_el.select_one(".tgme_widget_message_photo_wrap")
    if photo_wrap:
        style = photo_wrap.get("style") or ""
        m = BG_IMAGE_URL_RE.search(str(style))
        return "photo", (m.group(1) if m else None), None

    video_el = msg_el.select_one("video, .tgme_widget_message_video_wrap, .tgme_widget_message_roundvideo_wrap")
    if video_el:
        src = video_el.get("src") if video_el.name == "video" else None
        if not src:
            inner_video = msg_el.select_one("video")
            src = str(inner_video.get("src")) if inner_video and inner_video.get("src") else None
        return "video", (str(src) if src else None), None

    if msg_el.select_one(".tgme_widget_message_voice"):
        return "voice", None, None

    doc_wrap = msg_el.select_one(".tgme_widget_message_document_wrap")
    if doc_wrap:
        doc_title_el = doc_wrap.select_one(".tgme_widget_message_document_title")
        doc_title = doc_title_el.get_text(strip=True) if doc_title_el else None
        return "document", None, doc_title

    if msg_el.select_one(".tgme_widget_message_poll"):
        return "poll", None, None

    return "text", None, None


def parse_telegram_web_html(html: str, fallback_username: str) -> Tuple[Optional[str], List[FetchedPost]]:
    """
    Parses Telegram's public web preview HTML (https://t.me/s/<channel>).
    Returns (channel_title, sorted_posts_ascending).
    """
    soup = BeautifulSoup(html, "html.parser")

    history_section = soup.select_one(".tgme_channel_history")
    msg_nodes = soup.select(".tgme_widget_message[data-post]")

    if not history_section and not msg_nodes:
        raise CollectorError(
            "پیش‌نمایش وب عمومی برای این کانال فعال نیست یا کانال وجود ندارد. "
            "اگر کانال خصوصی است یا نمایش وب آن بسته است، از بخش تنظیمات اتصال Telethon را فعال کنید."
        )

    title: Optional[str] = None
    header_title = soup.select_one(".tgme_channel_info_header_title")
    if header_title:
        title = header_title.get_text(strip=True)
    if not title:
        og_title = soup.select_one('meta[property="og:title"]')
        if og_title and og_title.get("content"):
            title = str(og_title["content"]).strip()

    posts_by_id: Dict[int, FetchedPost] = {}

    for msg_el in msg_nodes:
        # Skip service messages (pinned notifications, channel photo changed, etc.)
        if "service_message" in (msg_el.get("class") or []):
            continue

        data_post = str(msg_el.get("data-post") or "").strip()
        if "/" not in data_post:
            continue

        ch_part, id_part = data_post.split("/", 1)
        if not id_part.isdigit():
            continue

        message_id = int(id_part)
        post_channel = ch_part.strip() or fallback_username
        post_url = f"https://t.me/{post_channel}/{message_id}"

        # Parse timestamp
        time_el = msg_el.select_one(".tgme_widget_message_date time[datetime]")
        published_at: Optional[datetime] = None
        if time_el and time_el.get("datetime"):
            raw_dt = str(time_el["datetime"]).strip()
            try:
                published_at = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
            except ValueError:
                published_at = None
        if published_at is None:
            published_at = datetime.now(timezone.utc)
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)

        # Clone bubble and strip reply preview so reply text isn't mixed into main content
        bubble = msg_el.select_one(".tgme_widget_message_bubble") or msg_el
        bubble_copy = copy.copy(bubble)
        for reply_block in bubble_copy.select(".tgme_widget_message_reply"):
            reply_block.decompose()

        text_parts: List[str] = []
        # Prefer explicit js-message_text, otherwise non-reply message text blocks
        text_blocks = bubble_copy.select(".js-message_text") or bubble_copy.select(".tgme_widget_message_text")
        for tb in text_blocks:
            extracted = _extract_clean_text(tb)
            if extracted:
                text_parts.append(extracted)

        # Poll support
        poll_el = bubble_copy.select_one(".tgme_widget_message_poll")
        if poll_el:
            q_el = poll_el.select_one(".tgme_widget_message_poll_question")
            opts = [o.get_text(strip=True) for o in poll_el.select(".tgme_widget_message_poll_option_text")]
            poll_lines = []
            if q_el:
                poll_lines.append(f"📊 نظرسنجی: {q_el.get_text(strip=True)}")
            for opt in opts:
                if opt:
                    poll_lines.append(f"• {opt}")
            if poll_lines:
                text_parts.append("\n".join(poll_lines))

        media_type, media_url, doc_title = _detect_media(msg_el)
        content = "\n\n".join(text_parts).strip()
        if not content:
            if media_type == "document" and doc_title:
                content = f"[فایل پیوست: {doc_title}]"
            else:
                content = MEDIA_FALLBACK_LABELS.get(media_type, "[مطلب بدون متن]")
        elif media_type == "document" and doc_title and doc_title not in content:
            content = f"[فایل: {doc_title}]\n{content}"

        views_el = msg_el.select_one(".tgme_widget_message_views")
        views = parse_views_count(views_el.get_text(strip=True) if views_el else None)

        posts_by_id[message_id] = FetchedPost(
            message_id=message_id,
            post_url=post_url,
            published_at=published_at,
            content=content,
            media_type=media_type,
            media_url=media_url,
            views=views,
        )

    sorted_posts = sorted(posts_by_id.values(), key=lambda p: p.message_id)
    return title, sorted_posts


class WebScraperCollector:
    """
    Fetches public Telegram channels via https://t.me/s/<username> without requiring
    a Telegram account or API credentials. Supports pagination via ?before=<id>.
    """

    MAX_BACKFILL_PAGES = 15

    async def fetch_channel_posts(
        self,
        *,
        username: str,
        last_message_id: Optional[int],
        initial_limit: int,
        settings: Dict[str, str],
    ) -> FetchBatchResult:
        if not username:
            raise CollectorError(
                "این کانال خصوصی است و یوزرنیم عمومی ندارد؛ برای دریافت از آن لطفاً موتور Telethon را در تنظیمات فعال کنید."
            )

        base_url = f"https://t.me/s/{username}"
        proxy_url = build_httpx_proxy_url(settings)

        collected: Dict[int, FetchedPost] = {}
        resolved_title: Optional[str] = None

        try:
            async with httpx.AsyncClient(
                headers=BROWSER_HEADERS,
                follow_redirects=True,
                timeout=httpx.Timeout(25.0, connect=15.0),
                proxy=proxy_url,
            ) as client:
                resp = await client.get(base_url)
                resp.raise_for_status()

                # Check if Telegram redirected away from /s/ (happens when web preview is disabled or channel doesn't exist)
                final_path = resp.url.path or ""
                if "/s/" not in final_path:
                    raise CollectorError(
                        f"پیش‌نمایش وب برای کانال @{username} در دسترس نیست (احتمالاً کانال خصوصی است، نمایش وب آن بسته است یا وجود ندارد)."
                    )

                title, page_posts = parse_telegram_web_html(resp.text, username)
                resolved_title = title

                # Case 1: First run for this channel -> take ONLY the latest `initial_limit` (default 10) posts
                if last_message_id is None:
                    for p in page_posts:
                        collected[p.message_id] = p

                    # If the latest page had fewer than initial_limit posts, walk 1 page back if possible
                    if 0 < len(collected) < initial_limit:
                        oldest_id = min(collected.keys())
                        older_resp = await client.get(base_url, params={"before": oldest_id})
                        if older_resp.status_code == 200 and "/s/" in (older_resp.url.path or ""):
                            _, older_posts = parse_telegram_web_html(older_resp.text, username)
                            for p in older_posts:
                                collected[p.message_id] = p

                    ordered = sorted(collected.values(), key=lambda p: p.message_id)
                    return FetchBatchResult(
                        channel_title=resolved_title,
                        posts=ordered[-initial_limit:],
                        source_mode="web",
                    )

                # Case 2: Subsequent runs -> collect strictly message_id > last_message_id, paginating backwards if needed
                for p in page_posts:
                    if p.message_id > last_message_id:
                        collected[p.message_id] = p

                if page_posts:
                    oldest_on_page = min(p.message_id for p in page_posts)
                    pages_walked = 1

                    while oldest_on_page > last_message_id and pages_walked < self.MAX_BACKFILL_PAGES:
                        older_resp = await client.get(base_url, params={"before": oldest_on_page})
                        if older_resp.status_code != 200 or "/s/" not in (older_resp.url.path or ""):
                            break
                        _, older_posts = parse_telegram_web_html(older_resp.text, username)
                        if not older_posts:
                            break
                        new_oldest = min(p.message_id for p in older_posts)
                        if new_oldest >= oldest_on_page:
                            break
                        for p in older_posts:
                            if p.message_id > last_message_id:
                                collected[p.message_id] = p
                        oldest_on_page = new_oldest
                        pages_walked += 1

                ordered = sorted(collected.values(), key=lambda p: p.message_id)
                return FetchBatchResult(
                    channel_title=resolved_title,
                    posts=ordered,
                    source_mode="web",
                )

        except CollectorError:
            raise
        except httpx.ProxyError as exc:
            raise CollectorError(
                f"خطا در اتصال به پروکسی تنظیم‌شده: {exc}. لطفاً آدرس و پورت پروکسی را در تنظیمات بررسی کنید."
            ) from exc
        except httpx.ConnectTimeout as exc:
            raise CollectorError(
                "مهلت زمانی اتصال به سرور تلگرام به پایان رسید (Timeout). در صورت محدودیت اینترنت، پروکسی SOCKS5/HTTP را در تنظیمات فعال کنید."
            ) from exc
        except httpx.ConnectError as exc:
            raise CollectorError(
                f"عدم دسترسی شبکه به سرور تلگرام (t.me): {exc}. لطفاً اتصال اینترنت یا تنظیمات پروکسی را بررسی کنید."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise CollectorError(
                f"سرور تلگرام کد وضعیت ناموفق برگرداند ({exc.response.status_code})."
            ) from exc
        except Exception as exc:
            raise CollectorError(f"خطای غیرمنتظره هنگام دریافت وب کانال: {exc}") from exc
