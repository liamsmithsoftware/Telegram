"""
تست‌های حذف مطالب: حالت انتخابی (فیلتر) و حالت انتخاب دستی ردیف‌ها، به‌همراه پاک‌سازی کلی.
"""
from __future__ import annotations

from tests.conftest import make_post


def _seed_two_channels(app_client, fake_web):
    """کانال A با ۴ مطلب (شامل photo و یک تبلیغ) و کانال B با ۲ مطلب."""
    fake_web.set_posts(
        [
            make_post(1, username="chan_a", text="خبر اول", hours_ago=48, media_type="text"),
            make_post(2, username="chan_a", text="تبلیغ ویژه", hours_ago=36, media_type="photo"),
            make_post(3, username="chan_a", text="خبر سوم", hours_ago=24, media_type="video"),
            make_post(4, username="chan_a", text="خبر چهارم", hours_ago=12, media_type="text"),
        ]
    )
    app_client.post(
        "/api/channels",
        json={"channel_input": "@chan_a", "interval_value": 6, "interval_unit": "hours", "fetch_now": True},
    )

    fake_web.set_posts(
        [
            make_post(10, username="chan_b", text="مطلب ب۱", hours_ago=30, media_type="text"),
            make_post(11, username="chan_b", text="مطلب ب۲", hours_ago=2, media_type="document"),
        ]
    )
    app_client.post(
        "/api/channels",
        json={"channel_input": "@chan_b", "interval_value": 12, "interval_unit": "hours", "fetch_now": True},
    )

    channels = {c["username"]: c for c in app_client.get("/api/channels").json()["items"]}
    return channels["chan_a"], channels["chan_b"]


# ---------------------------------------------------------------------------
# حالت ۱: حذف بر اساس فیلتر
# ---------------------------------------------------------------------------
def test_bulk_delete_by_channel_only_touches_that_channel(app_client, fake_web):
    chan_a, chan_b = _seed_two_channels(app_client, fake_web)
    assert app_client.get("/api/posts").json()["total"] == 6

    body = app_client.post("/api/posts/bulk-delete", json={"channel_id": chan_a["id"]}).json()
    assert body["deleted_posts"] == 4
    assert body["affected_channels"] == [chan_a["id"]]
    assert body["channels_reset"] == 1
    assert "۴ مطلب حذف شد" in body["message"]

    remaining = app_client.get("/api/posts").json()
    assert remaining["total"] == 2
    assert all(p["channel_username"] == "chan_b" for p in remaining["items"])

    refreshed = {c["username"]: c for c in app_client.get("/api/channels").json()["items"]}
    assert refreshed["chan_a"]["last_message_id"] is None
    assert refreshed["chan_a"]["last_status"] == "pending"
    assert refreshed["chan_b"]["last_message_id"] == 11


def test_bulk_delete_by_media_type(app_client, fake_web):
    _seed_two_channels(app_client, fake_web)
    body = app_client.post("/api/posts/bulk-delete", json={"media_type": "photo"}).json()
    assert body["deleted_posts"] == 1

    remaining = app_client.get("/api/posts?page_size=50").json()["items"]
    assert len(remaining) == 5
    assert all(p["media_type"] != "photo" for p in remaining)


def test_bulk_delete_by_date_range_both_calendars(app_client, fake_web):
    _seed_two_channels(app_client, fake_web)

    greg = app_client.post(
        "/api/posts/bulk-delete", json={"date_from": "2026-11-06", "date_to": "2026-11-07"}
    ).json()
    # Tehran-local dates: posts 48h/36h/30h/24h old all land on 2026-11-06..07
    assert greg["deleted_posts"] == 4
    assert app_client.get("/api/posts").json()["total"] == 2

    jalali = app_client.post(
        "/api/posts/bulk-delete", json={"date_from": "1405/08/17", "date_to": "1405/08/17"}
    ).json()
    assert jalali["deleted_posts"] == 2  # the two newest posts (12h and 2h ago)
    assert app_client.get("/api/posts").json()["total"] == 0


def test_bulk_delete_with_search_term(app_client, fake_web):
    _seed_two_channels(app_client, fake_web)
    body = app_client.post("/api/posts/bulk-delete", json={"search": "تبلیغ"}).json()
    assert body["deleted_posts"] == 1
    remaining = app_client.get("/api/posts?page_size=50").json()["items"]
    assert all("تبلیغ" not in p["content"] for p in remaining)


def test_bulk_delete_invalid_inputs(app_client, fake_web):
    _seed_two_channels(app_client, fake_web)

    assert app_client.post("/api/posts/bulk-delete", json={"date_from": "bad"}).status_code == 400
    assert (
        app_client.post(
            "/api/posts/bulk-delete", json={"date_from": "2026-11-09", "date_to": "2026-11-01"}
        ).status_code
        == 400
    )
    assert app_client.post("/api/posts/bulk-delete", json={"channel_id": 999999}).status_code == 404


def test_bulk_delete_without_reset_keeps_cursor(app_client, fake_web):
    chan_a, _ = _seed_two_channels(app_client, fake_web)
    body = app_client.post(
        "/api/posts/bulk-delete",
        json={"channel_id": chan_a["id"], "reset_channel_cursors": False},
    ).json()
    assert body["deleted_posts"] == 4
    assert body["channels_reset"] == 0

    refreshed = {c["username"]: c for c in app_client.get("/api/channels").json()["items"]}
    assert refreshed["chan_a"]["last_message_id"] == 4


def test_bulk_delete_all_without_filters(app_client, fake_web):
    _seed_two_channels(app_client, fake_web)
    body = app_client.post("/api/posts/bulk-delete", json={}).json()
    assert body["deleted_posts"] == 6
    assert app_client.get("/api/posts").json()["total"] == 0
    # channels survive a filter-less bulk delete
    assert len(app_client.get("/api/channels").json()["items"]) == 2


# ---------------------------------------------------------------------------
# حالت ۲: حذف ردیف‌های انتخاب‌شده (post_ids)
# ---------------------------------------------------------------------------
def test_delete_only_selected_post_ids(app_client, fake_web):
    _seed_two_channels(app_client, fake_web)
    posts = app_client.get("/api/posts?page_size=50").json()["items"]
    chosen = [posts[0]["id"], posts[2]["id"]]
    chosen_channel_ids = {p["channel_id"] for p in (posts[0], posts[2])}

    body = app_client.post("/api/posts/bulk-delete", json={"post_ids": chosen}).json()
    assert body["deleted_posts"] == 2
    assert body["requested_ids"] == 2
    assert sorted(body["affected_channels"]) == sorted(chosen_channel_ids)
    assert "انتخاب‌شده" in body["message"]

    remaining_ids = {p["id"] for p in app_client.get("/api/posts?page_size=50").json()["items"]}
    assert remaining_ids.isdisjoint(set(chosen))
    assert len(remaining_ids) == 4


def test_selected_delete_ignores_ids_from_other_channels(app_client, fake_web):
    _seed_two_channels(app_client, fake_web)
    posts = app_client.get("/api/posts?page_size=50").json()["items"]
    one_id = posts[0]["id"]
    body = app_client.post("/api/posts/bulk-delete", json={"post_ids": [one_id]}).json()
    assert body["deleted_posts"] == 1


def test_empty_selection_is_rejected(app_client, fake_web):
    _seed_two_channels(app_client, fake_web)
    res = app_client.post("/api/posts/bulk-delete", json={"post_ids": []})
    assert res.status_code == 400
    assert "انتخاب" in res.json()["detail"]
    assert app_client.get("/api/posts").json()["total"] == 6


def test_nonexistent_ids_delete_nothing(app_client, fake_web):
    _seed_two_channels(app_client, fake_web)
    body = app_client.post("/api/posts/bulk-delete", json={"post_ids": [999999, 888888]}).json()
    assert body["deleted_posts"] == 0
    assert "یافت نشد" in body["message"]
    assert app_client.get("/api/posts").json()["total"] == 6


def test_selected_delete_combines_with_reset_toggle(app_client, fake_web):
    chan_a, _ = _seed_two_channels(app_client, fake_web)
    posts = app_client.get(f"/api/posts?channel_id={chan_a['id']}&page_size=50").json()["items"]
    body = app_client.post(
        "/api/posts/bulk-delete",
        json={"post_ids": [posts[0]["id"]], "reset_channel_cursors": True},
    ).json()
    assert body["deleted_posts"] == 1
    refreshed = {c["username"]: c for c in app_client.get("/api/channels").json()["items"]}
    assert refreshed["chan_a"]["last_message_id"] is None


def test_posts_ids_endpoint_returns_filtered_ids(app_client, fake_web):
    _seed_two_channels(app_client, fake_web)

    all_ids = app_client.get("/api/posts/ids").json()
    assert all_ids["total"] == 6
    assert len(all_ids["ids"]) == 6

    photos = app_client.get("/api/posts/ids?media_type=photo").json()
    assert photos["total"] == 1

    by_date = app_client.get("/api/posts/ids?date_from=1405/08/17&date_to=1405/08/17").json()
    assert by_date["total"] == 2

    bad = app_client.get("/api/posts/ids?date_from=nope")
    assert bad.status_code == 400


def test_select_all_matching_then_delete(app_client, fake_web):
    """سناریوی دکمه «انتخاب همه نتایج فیلتر» و سپس حذف."""
    _seed_two_channels(app_client, fake_web)
    ids = app_client.get("/api/posts/ids?media_type=text").json()["ids"]
    body = app_client.post("/api/posts/bulk-delete", json={"post_ids": ids}).json()
    assert body["deleted_posts"] == len(ids)
    assert app_client.get("/api/posts").json()["total"] == 6 - len(ids)


# ---------------------------------------------------------------------------
# پاک‌سازی کلی
# ---------------------------------------------------------------------------
def test_purge_posts_keeps_channels(app_client, fake_web):
    _seed_two_channels(app_client, fake_web)
    body = app_client.post("/api/posts/purge", json={"keep_channels": True}).json()

    assert body["deleted_posts"] == 6
    assert body["deleted_channels"] == 0
    assert body["channels_kept"] is True

    channels = app_client.get("/api/channels").json()["items"]
    assert len(channels) == 2
    assert all(c["last_message_id"] is None for c in channels)
    assert app_client.get("/api/posts").json()["total"] == 0
    assert app_client.get("/api/logs").json()["items"] == []


def test_purge_everything_removes_channels_too(app_client, fake_web):
    _seed_two_channels(app_client, fake_web)
    body = app_client.post("/api/posts/purge", json={"keep_channels": False}).json()

    assert body["deleted_channels"] == 2
    assert body["deleted_posts"] == 6
    assert body["channels_kept"] is False

    assert app_client.get("/api/channels").json()["items"] == []
    assert app_client.get("/api/posts").json()["total"] == 0
    # user settings must survive
    assert app_client.get("/api/settings").json()["settings"]["timezone"] == "Asia/Tehran"


def test_purge_is_idempotent_when_already_empty(app_client):
    res = app_client.post("/api/posts/purge", json={"keep_channels": True})
    assert res.status_code == 200
    assert res.json()["deleted_posts"] == 0


def test_delete_after_purge_reimports_initial_ten(app_client, fake_web):
    chan_a, _ = _seed_two_channels(app_client, fake_web)
    app_client.post("/api/posts/purge", json={"keep_channels": True})

    fake_web.set_posts([make_post(100 + i, username="chan_a", hours_ago=20 - i) for i in range(20)])
    sync = app_client.post(f"/api/channels/{chan_a['id']}/sync").json()
    assert sync["sync_result"]["new_saved_count"] == 10
    assert sync["sync_result"]["new_last_message_id"] == 119


# ---------------------------------------------------------------------------
# رابط کاربری
# ---------------------------------------------------------------------------
def test_cleanup_and_selection_ui_present(app_client):
    page = app_client.get("/").text
    assert 'data-tab="cleanup"' in page
    assert "حذف گروهی مطالب" in page
    assert "bulkDeleteForm" in page
    assert "btnPurgeEverything" in page
    assert "btnDeleteSelected" in page
    assert "selectAllPosts" in page
    assert "selectionToolbar" in page

    js = app_client.get("/static/js/app.js").text
    for fn in ("deleteSelectedPosts", "selectAllMatchingFilter", "runScopedDelete", "loadCleanupTab"):
        assert fn in js
