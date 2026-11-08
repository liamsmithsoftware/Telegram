#!/usr/bin/env bash
# اجرای برنامه روی لینوکس و مک
# استفاده:  bash start_linux_mac.sh   یا   ./start_linux_mac.sh
set -e

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "خطا: پایتون 3 یافت نشد. لطفاً Python 3.10 یا بالاتر را نصب کنید."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "→ ساخت محیط مجازی پایتون ..."
    "$PYTHON_BIN" -m venv .venv
fi

echo "→ نصب / بررسی وابستگی‌ها ..."
./.venv/bin/python -m pip install --upgrade pip >/dev/null

# نصب فقط از فایل‌های wheel آماده (بدون نیاز به کامپایلر C)
if ! ./.venv/bin/python -m pip install --prefer-binary -r requirements.txt; then
    echo "هشدار: نصب عادی ناموفق بود؛ تلاش دوباره با گزینه‌های بیشتر ..."
    ./.venv/bin/python -m pip install --prefer-binary --retries 5 --timeout 60 -r requirements.txt
fi

# موتور اختیاری Telethon (برای کانال‌های خصوصی) — خطای آن برنامه را متوقف نمی‌کند
if ! ./.venv/bin/python -c "import telethon" >/dev/null 2>&1; then
    echo "→ نصب موتور اختیاری Telethon (برای کانال‌های خصوصی) ..."
    ./.venv/bin/python -m pip install --prefer-binary -r requirements-telethon.txt \
        || echo "هشدار: Telethon نصب نشد. کانال‌های عمومی با موتور وب کار می‌کنند."
fi

echo "→ اجرای برنامه ..."
exec ./.venv/bin/python run.py "$@"
