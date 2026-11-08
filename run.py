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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="سامانه هوشمند جمع‌آوری و آرشیو کانال‌های تلگرام",
    )
    parser.add_argument("--host", default=os.getenv("TELEGRAM_COLLECTOR_HOST", "0.0.0.0"), help="آدرس اتصال")
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("TELEGRAM_COLLECTOR_PORT", "8000")), help="پورت سرور"
    )
    parser.add_argument("--reload", action="store_true", help="بارگذاری خودکار هنگام تغییر کد")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    try:
        import uvicorn
    except ImportError:  # pragma: no cover
        print("خطا: کتابخانه uvicorn نصب نشده است.\nابتدا دستور زیر را اجرا کنید:\n  pip install -r requirements.txt")
        raise SystemExit(1)

    from app.config import ensure_directories

    ensure_directories()

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
