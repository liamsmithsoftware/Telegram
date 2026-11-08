"""
اگر Telethon نصب نباشد (حالت «ویندوز بدون Microsoft C++ Build Tools»)، برنامه
باید کامل بالا بیاید و فقط امکانات مربوط به کانال خصوصی غیرفعال شود.
"""
from __future__ import annotations

import sys
import types

import pytest


class _TelethonBlocker:
    """sys.meta_path hook that pretends telethon is not installed."""

    def find_module(self, name, path=None):  # legacy API, still consulted
        if name == "telethon" or name.startswith("telethon."):
            return self
        return None

    def load_module(self, name):
        raise ImportError("No module named 'telethon' (simulated)")


@pytest.fixture()
def without_telethon(monkeypatch):
    blocked = _TelethonBlocker()
    monkeypatch.setattr(sys, "meta_path", [blocked, *sys.meta_path])
    for mod in [m for m in sys.modules if m == "telethon" or m.startswith("telethon.")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)

    import app.collectors.telethon_client as tc
    import app.config as cfg

    monkeypatch.setattr(tc, "TELETHON_AVAILABLE", False)
    monkeypatch.setattr(cfg, "TELETHON_INSTALLED", False)
    return tc


def test_missing_telethon_module_does_not_break_import(without_telethon):
    import app.collectors.telethon_client as tc

    assert tc.TELETHON_AVAILABLE is False
    assert "نصب نیست" in tc.TELETHON_MISSING_MESSAGE


def test_collector_reports_unavailable_and_refuses_login(without_telethon):
    import asyncio

    from app.collectors.base import CollectorError
    from app.collectors.telethon_client import TelethonCollector

    collector = TelethonCollector()

    assert collector.has_credentials({"telethon_api_id": "12345", "telethon_api_hash": "x" * 32}) is False

    status = asyncio.run(collector.get_auth_status({}))
    assert status["available"] is False
    assert status["authorized"] is False

    with pytest.raises(CollectorError):
        asyncio.run(collector.send_login_code({}, "+989120000000"))

    # logout must still succeed so a stale session file can be removed
    out = asyncio.run(collector.logout({}))
    assert out["logged_out"] is True


def test_web_engine_still_works_and_app_reports_flag(without_telethon, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app.services.exporter as exporter_module
    from app.main import create_app
    from tests.conftest import FakeTelethonCollector, FakeWebCollector, make_post

    monkeypatch.setattr(exporter_module, "EXPORTS_DIR", tmp_path / "exports")

    web = FakeWebCollector()
    web.set_posts([make_post(1 + i, hours_ago=5 - i) for i in range(3)])

    application = create_app(
        db_path=tmp_path / "opt.sqlite",
        session_prefix=tmp_path / "sess",
        enable_scheduler=False,
        web_collector=web,
        telethon_collector=FakeTelethonCollector(),
    )

    with TestClient(application) as client:
        settings = client.get("/api/settings").json()
        assert settings["telethon_installed"] is False

        created = client.post(
            "/api/channels",
            json={"channel_input": "@public_chan", "interval_value": 6, "interval_unit": "hours", "fetch_now": True},
        ).json()
        assert created["sync_result"]["new_saved_count"] == 3

        assert client.get("/api/exports/excel").status_code == 200
        assert client.get("/api/exports/sqlite").status_code == 200

        refused = client.post("/api/telethon/send-code", json={"phone": "+989120000000"})
        assert refused.status_code == 400
