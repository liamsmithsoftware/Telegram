from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.collectors.base import CollectorError
from app.collectors.web_scraper import (
    parse_telegram_web_html,
    parse_views_count,
)

FIXTURE = Path(__file__).parent / "fixtures" / "channel_page.html"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1.2K", 1200),
        ("12K", 12000),
        ("2M", 2_000_000),
        ("1,234", 1234),
        ("987", 987),
        (" 5.5K ", 5500),
        ("", None),
        (None, None),
        ("abc", None),
    ],
)
def test_parse_views_count(raw, expected):
    assert parse_views_count(raw) == expected


def test_parse_html_extracts_structured_posts():
    html = FIXTURE.read_text(encoding="utf-8")
    title, posts = parse_telegram_web_html(html, "sample_channel")

    assert title == "کانال نمونه آموزشی"
    # Service messages must be skipped
    assert [p.message_id for p in posts] == [100, 102, 103]

    by_id = {p.message_id: p for p in posts}

    third = by_id[103]
    assert third.post_url == "https://t.me/sample_channel/103"
    assert third.published_at == datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc)
    assert third.content == "مطلب سوم\nخط دوم مطلب سوم"
    assert third.media_type == "text"
    assert third.views == 1200

    second = by_id[102]
    # Reply preview must be stripped, <br> handled, photo detected
    assert "نقل قول" not in second.content
    assert second.content == "مطلب دوم"
    assert second.media_type == "photo"
    assert second.media_url == "https://cdn.example.com/photo102.jpg"
    assert second.views == 875

    document = by_id[100]
    assert document.media_type == "document"
    assert document.views == 2_000_000
    assert "گزارش-هفتگی.pdf" in document.content


def test_parse_html_raises_for_channel_without_web_preview():
    with pytest.raises(CollectorError):
        parse_telegram_web_html("<html><body><div>nothing here</div></body></html>", "ghost_channel")


def test_parse_html_timestamps_are_utc_aware():
    html = FIXTURE.read_text(encoding="utf-8")
    _, posts = parse_telegram_web_html(html, "sample_channel")
    for post in posts:
        assert post.published_at.tzinfo is not None
        assert post.published_at.utcoffset() == timezone.utc.utcoffset(None)


def test_parse_html_photo_message_without_text_gets_fallback_label():
    html = """
    <section class="tgme_channel_history">
      <div class="tgme_widget_message" data-post="chan/7">
        <div class="tgme_widget_message_bubble">
          <a class="tgme_widget_message_date" href="https://t.me/chan/7">
            <time datetime="2026-11-08T10:00:00+00:00"></time>
          </a>
          <a class="tgme_widget_message_photo_wrap" style="background-image:url('https://cdn.example.com/x.jpg')"></a>
        </div>
      </div>
    </section>
    """
    _, posts = parse_telegram_web_html(html, "chan")
    assert len(posts) == 1
    assert posts[0].media_type == "photo"
    assert posts[0].content.startswith("[")
