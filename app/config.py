from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("TELEGRAM_COLLECTOR_DATA_DIR", str(BASE_DIR / "data")))
EXPORTS_DIR = DATA_DIR / "exports"
DB_PATH = Path(os.getenv("TELEGRAM_COLLECTOR_DB_PATH", str(DATA_DIR / "telegram_collector.sqlite")))
SESSION_PREFIX = Path(os.getenv("TELEGRAM_COLLECTOR_SESSION", str(DATA_DIR / "telethon_session")))

APP_HOST = os.getenv("TELEGRAM_COLLECTOR_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("TELEGRAM_COLLECTOR_PORT", "8000"))

# Telethon is an optional dependency (see requirements-telethon.txt)
try:  # pragma: no cover - trivial import probe
    import telethon as _telethon  # noqa: F401

    TELETHON_INSTALLED = True
except Exception:  # pragma: no cover
    TELETHON_INSTALLED = False

DEFAULT_TIMEZONE = "Asia/Tehran"
DEFAULT_INITIAL_LIMIT = 10
SCHEDULER_TICK_SECONDS = int(os.getenv("TELEGRAM_COLLECTOR_TICK_SECONDS", "30"))


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
