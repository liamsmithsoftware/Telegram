"""
راه‌انداز برنامه روی ویندوز.

این فایل توسط start_windows.bat فراخوانی می‌شود و کارهای زیر را انجام می‌دهد:
  1) نصب وابستگی‌ها (فقط از wheel آماده — بدون نیاز به کامپایلر C)
  2) نصب اختیاری Telethon
  3) اجرای سرور روی http://localhost:8000

چرا این فایل وجود دارد؟ منطق کنسول ویندوز (cmd.exe) برای متن فارسی و
پرانتزهای داخل if/else بسیار شکننده است؛ بنابراین تمام منطق به پایتون منتقل
شده تا هیچ دستور پیچیده‌ای در فایل .bat باقی نماند.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
VENV_PY = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
MIN_PYTHON = (3, 10)
DEFAULT_PORT = int(os.getenv("TELEGRAM_COLLECTOR_PORT", "8000"))


def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def pick_port(preferred: int) -> int:
    if port_is_free(preferred):
        return preferred
    print(f"      Port {preferred} is already in use, looking for a free one ...")
    for candidate in range(preferred + 1, preferred + 21):
        if port_is_free(candidate):
            print(f"      Using port {candidate} instead.")
            return candidate
    return preferred


def open_browser(port: int) -> None:
    def _open() -> None:
        try:
            webbrowser.open(f"http://localhost:{port}")
        except Exception:
            pass

    threading.Timer(3.5, _open).start()


def hr() -> None:
    print("=" * 62)


def fail(message: str) -> int:
    print()
    print("[ERROR] " + message)
    print()
    return 1


def find_system_python() -> str | None:
    """Find a usable Python interpreter *before* .venv exists."""
    for candidate in ("py", "python", "python3"):
        try:
            result = subprocess.run(
                [candidate, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            continue
        if result.returncode != 0:
            continue
        try:
            major, minor = (int(x) for x in result.stdout.split()[:2])
        except ValueError:
            continue
        if (major, minor) >= MIN_PYTHON:
            if candidate == "py":
                return "py -3"
            return candidate
    return None


def venv_python() -> str:
    return str(VENV_PY)


def ensure_venv() -> tuple[bool, str]:
    if VENV_PY.exists():
        print("[1/3] Virtual environment found: .venv")
        return True, ""

    print("[1/3] Creating virtual environment (.venv) ...")
    system_python = find_system_python()
    if not system_python:
        return False, (
            "Python 3.10+ not found.\n"
            "        Install it from https://www.python.org/downloads/\n"
            '        IMPORTANT: tick "Add python.exe to PATH" during setup.'
        )

    parts = system_python.split()
    result = subprocess.run([*parts, "-m", "venv", str(VENV_DIR)], cwd=str(ROOT))
    if result.returncode != 0 or not VENV_PY.exists():
        return False, "Failed to create the virtual environment."
    return True, ""


def pip_install(python: str, args: list[str]) -> int:
    cmd = [python, "-m", "pip", "install", "--prefer-binary", "--retries", "5", "--timeout", "60", *args]
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def install_dependencies(python: str) -> tuple[bool, str]:
    print("[2/3] Installing dependencies (no C++ compiler needed) ...")
    subprocess.run(
        [python, "-m", "pip", "install", "--upgrade", "pip"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if pip_install(python, ["-r", "requirements.txt"]) != 0:
        print()
        print("[ERROR] Dependency installation failed.")
        print("        - Check your internet / proxy connection.")
        print("        - Manual retry:")
        print("            .venv\\Scripts\\python.exe -m pip install --prefer-binary -r requirements.txt")
        print()
        return False, "dependencies"

    # Telethon is optional: private channels only.
    probe = subprocess.run(
        [python, "-c", "import telethon"], capture_output=True, text=True
    )
    if probe.returncode != 0:
        print("      Installing optional Telethon engine (for private channels) ...")
        if pip_install(python, ["-r", "requirements-telethon.txt"]) != 0:
            print("      [WARN] Telethon was not installed. Public channels still work.")
        else:
            print("      Telethon installed.")
    return True, ""


def main() -> int:
    # Make progress messages visible immediately, even when output is piped
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass

    hr()
    print("  Telegram Channel Collector")
    print("  سامانه جمع‌آوری و آرشیو کانال‌های تلگرام")
    hr()
    print()

    ok, error = ensure_venv()
    if not ok:
        return fail(error)

    python = venv_python()

    ok, error = install_dependencies(python)
    if not ok:
        return fail(error)

    if not (VENV_PY.parent.parent / "lib").exists() and os.name != "nt":
        pass

    args = list(sys.argv[1:])
    port = DEFAULT_PORT
    for idx, arg in enumerate(args):
        if arg in ("--port", "-p") and idx + 1 < len(args):
            try:
                port = int(args[idx + 1])
            except ValueError:
                pass
        elif arg.startswith("--port="):
            try:
                port = int(arg.split("=", 1)[1])
            except ValueError:
                pass

    if "--port" not in " ".join(args) and not any(a.startswith("--port=") for a in args):
        port = pick_port(port)
        args += ["--port", str(port)]
    else:
        port = pick_port(port)
        # replace the given port with the resolved free one
        for idx, arg in enumerate(args):
            if arg in ("--port", "-p") and idx + 1 < len(args):
                args[idx + 1] = str(port)
            elif arg.startswith("--port="):
                args[idx] = f"--port={port}"

    print("[3/3] Starting server ...")
    print(f"      Address:  http://localhost:{port}")
    print("      The browser opens automatically in a few seconds.")
    print("      Press Ctrl + C to stop the program.")
    print()

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")

    open_browser(port)
    try:
        return subprocess.run([python, str(ROOT / "run.py"), *args], cwd=str(ROOT), env=env).returncode
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
