from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote


@dataclass
class FetchedPost:
    message_id: int
    post_url: str
    published_at: datetime
    content: str
    media_type: str = "text"
    media_url: Optional[str] = None
    views: Optional[int] = None


@dataclass
class FetchBatchResult:
    channel_title: Optional[str]
    posts: List[FetchedPost]
    source_mode: str  # 'web' | 'telethon'


class CollectorError(RuntimeError):
    """Raised when fetching posts from Telegram fails."""


def build_httpx_proxy_url(settings: Dict[str, str]) -> Optional[str]:
    if settings.get("proxy_enabled") != "1":
        return None
    host = (settings.get("proxy_host") or "").strip()
    port = (settings.get("proxy_port") or "").strip()
    if not host or not port:
        return None

    scheme = (settings.get("proxy_type") or "socks5").strip().lower()
    if scheme not in ("socks5", "http", "https"):
        scheme = "socks5"
    if scheme == "socks5":
        # socks5h ensures DNS resolution goes through proxy too
        scheme_prefix = "socks5"
    else:
        scheme_prefix = scheme

    username = (settings.get("proxy_username") or "").strip()
    password = (settings.get("proxy_password") or "").strip()
    if username:
        auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    else:
        auth = ""

    return f"{scheme_prefix}://{auth}{host}:{port}"


def build_telethon_proxy_dict(settings: Dict[str, str]) -> Optional[Dict[str, Any]]:
    if settings.get("proxy_enabled") != "1":
        return None
    host = (settings.get("proxy_host") or "").strip()
    port_str = (settings.get("proxy_port") or "").strip()
    if not host or not port_str or not port_str.isdigit():
        return None

    ptype = (settings.get("proxy_type") or "socks5").strip().lower()
    proxy_cfg: Dict[str, Any] = {
        "proxy_type": "socks5" if ptype == "socks5" else "http",
        "addr": host,
        "port": int(port_str),
        "rdns": True,
    }
    username = (settings.get("proxy_username") or "").strip()
    password = (settings.get("proxy_password") or "").strip()
    if username:
        proxy_cfg["username"] = username
        proxy_cfg["password"] = password
    return proxy_cfg
