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
./.venv/bin/python -m pip install -r requirements.txt

echo "→ اجرای برنامه ..."
exec ./.venv/bin/python run.py "$@"
