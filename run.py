#!/usr/bin/env python3
"""
اجرای سامانه جمع‌آوری کانال‌های تلگرام.

استفاده:
    python run.py                 # اجرا روی 0.0.0.0:8000
    python run.py --port 9000     # تغییر پورت
    python run.py --reload        # حالت توسعه (بارگذاری خودکار)
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def port_available(host: str, port: int) -> bool:
    """True when nothing else is listening on this port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def is_our_app(host: str, port: int) -> bool:
    """Check whether the service already on that port is this very program."""
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    try:
        with urllib.request.urlopen(f"http://{probe_host}:{port}/healthz", timeout=2) as response:
            body = response.read(200).decode("utf-8", "replace")
        return '"status"' in body and "ok" in body
    except (urllib.error.URLError, OSError, ValueError):
        return False


def pick_free_port(host: str, start_port: int, span: int = 20) -> int:
    for candidate in range(start_port, start_port + span):
        if port_available(host, candidate):
            return candidate
    return start_port


def handle_busy_port(host: str, port: int) -> int:
    """
    Decides what to do when the requested port is occupied.
    Returns the port that should actually be used (exits the process when the
    program is already running, so the user never sees a raw WinError 10048).
    """
    if port_available(host, port):
        return port

    already_running = is_our_app(host, port)

    print()
    print("=" * 62)
    print(f"  پورت {port} در حال حاضر اشغال است.")
    if already_running:
        print("  به نظر می‌رسد برنامه از قبل در حال اجراست.")
        print(f"  پنل مدیریت:  http://localhost:{port}")
        print()
        print("  اگر پنجره قدیمی را می‌بینید، ابتدا آن را ببندید (یا Ctrl+C بزنید)")
        print("  و سپس دوباره برنامه را اجرا کنید.")
        print("=" * 62)
        raise SystemExit(0)

    new_port = pick_free_port(host, port + 1)
    print(f"  برنامه روی پورت آزاد {new_port} اجرا می‌شود:")
    print(f"  پنل مدیریت:  http://localhost:{new_port}")
    print("=" * 62)
    print()
    return new_port


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="سامانه هوشمند جمع‌آوری و آرشیو کانال‌های تلگرام",
    )
    parser.add_argument("--host", default=os.getenv("TELEGRAM_COLLECTOR_HOST", "0.0.0.0"), help="آدرس اتصال")
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("TELEGRAM_COLLECTOR_PORT", "8000")), help="پورت سرور"
    )
    parser.add_argument("--reload", action="store_true", help="بارگذاری خودکار هنگام تغییر کد")
    parser.add_argument(
        "--strict-port",
        action="store_true",
        help="اگر پورت اشغال بود، به‌جای انتخاب پورت آزاد، برنامه متوقف شود",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    try:
        import uvicorn
    except ImportError:  # pragma: no cover
        print("خطا: کتابخانه uvicorn نصب نشده است.\nابتدا دستور زیر را اجرا کنید:\n  pip install -r requirements.txt")
        raise SystemExit(1)

    # کتابخانه‌های ضروری را قبل از بالا آمدن سرور بررسی می‌کنیم تا پیام خطای
    # واضح فارسی ببینید (نه traceback انگلیسی).
    missing: list[str] = []
    for module_name, pip_name in (
        ("fastapi", "fastapi"),
        ("httpx", "httpx[socks]"),
        ("bs4", "beautifulsoup4"),
        ("apscheduler", "apscheduler"),
        ("openpyxl", "openpyxl"),
        ("jdatetime", "jdatetime"),
    ):
        try:
            __import__(module_name)
        except ImportError:
            missing.append(pip_name)
    if missing:
        print("خطا: این بسته‌ها نصب نشده‌اند: " + ", ".join(missing))
        print("دستور نصب:  pip install -r requirements.txt")
        raise SystemExit(1)

    from app.config import ensure_directories

    ensure_directories()

    # پورت اشغال‌شده نباید باعث کرش با WinError 10048 شود
    if port_available(args.host, args.port):
        pass
    elif args.strict_port:
        print(f"خطا: پورت {args.port} اشغال است. یک پورت دیگر با --port انتخاب کنید.")
        raise SystemExit(1)
    else:
        args.port = handle_busy_port(args.host, args.port)

    print("=" * 68)
    print("  سامانه هوشمند جمع‌آوری و آرشیو کانال‌های تلگرام")
    print(f"  آدرس پنل مدیریت:  http://localhost:{args.port}")
    print(f"  آدرس شبکه محلی:   http://{args.host}:{args.port}")
    print("  برای خروج کلیدهای Ctrl + C را فشار دهید")
    print("=" * 68)

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(ROOT / "app")] if args.reload else None,
        log_level="info",
        forwarded_allow_ips="*",
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
