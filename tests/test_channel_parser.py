from __future__ import annotations

import pytest

from app.collectors.base import CollectorError
from app.utils.channel_parser import normalize_digits, parse_channel_input


@pytest.mark.parametrize(
    "raw, username, is_private",
    [
        ("@MyChannel", "mychannel", False),
        ("mychannel", "mychannel", False),
        ("https://t.me/MyChannel", "mychannel", False),
        ("https://t.me/s/MyChannel", "mychannel", False),
        ("https://t.me/MyChannel/1234", "mychannel", False),
        ("t.me/MyChannel", "mychannel", False),
        ("https://www.telegram.me/MyChannel", "mychannel", False),
        ("  @MyChannel  ", "mychannel", False),
        ("@my_channel_2026", "my_channel_2026", False),
    ],
)
def test_parse_public_channel_variants(raw: str, username: str, is_private: bool):
    parsed = parse_channel_input(raw)
    assert parsed.username is not None
    assert parsed.username.lower() == username
    assert parsed.is_private is is_private
    assert parsed.canonical_url.lower() == f"https://t.me/{username}"
    assert parsed.web_preview_url is not None
    assert parsed.web_preview_url.lower() == f"https://t.me/s/{username}"
    # Telegram usernames are case-insensitive, so the dedupe key must be lowercase
    assert parsed.channel_key == username


@pytest.mark.parametrize(
    "raw",
    [
        "https://t.me/+AbCdEfGhIjK",
        "https://t.me/joinchat/AbCdEfGhIjK",
        "t.me/+AbCdEfGhIjK",
    ],
)
def test_parse_private_invite_link(raw: str):
    parsed = parse_channel_input(raw)
    assert parsed.is_private is True
    assert parsed.username is None
    assert parsed.web_preview_url is None


@pytest.mark.parametrize("raw", ["https://t.me/c/1234567890/42", "-1001234567890"])
def test_parse_private_peer_id(raw: str):
    parsed = parse_channel_input(raw)
    assert parsed.is_private is True
    assert parsed.canonical_url.startswith("https://t.me/c/")


def test_duplicate_inputs_share_channel_key():
    a = parse_channel_input("@MyChannel")
    b = parse_channel_input("https://t.me/s/MyChannel/999")
    c = parse_channel_input("mychannel")
    assert a.channel_key == b.channel_key == c.channel_key


def test_persian_digits_are_normalized():
    assert normalize_digits("۱۲۳۴۵۶") == "123456"
    assert normalize_digits("٠١٢٣") == "0123"
    parsed = parse_channel_input("https://t.me/c/۱۲۳۴۵۶۷۸۹۰/۴۲")
    assert parsed.is_private is True


def test_invisible_characters_are_stripped():
    parsed = parse_channel_input("\u200c@MyChannel\u200f")
    assert parsed.username is not None
    assert parsed.username.lower() == "mychannel"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "https://example.com/mychannel",
        "https://t.me/",
        "https://t.me/s/",
        "a",
        "https://t.me/share/url?url=test",
    ],
)
def test_invalid_inputs_raise_value_error(raw: str):
    with pytest.raises(ValueError):
        parse_channel_input(raw)


def test_collector_error_is_runtime_error():
    assert issubclass(CollectorError, RuntimeError)
