/* ------------------------------------------------------------------
 * آرشیو هوشمند کانال‌های تلگرام — Frontend Controller
 * همه درخواست‌ها نسبت به همین دامنه و با مسیرهای /api/... ارسال می‌شوند.
 * ------------------------------------------------------------------ */

"use strict";

const state = {
    timezone: "Asia/Tehran",
    channels: [],
    posts: {
        page: 1,
        pageSize: 25,
        total: 0,
        totalPages: 1,
        items: [],
    },
    filters: {
        channel_id: "",
        search: "",
        date_from: "",
        date_to: "",
        media_type: "all",
    },
    editingChannelId: null,
    activeModalPost: null,
    logRefreshTimer: null,
    overviewTimer: null,
};

const MEDIA_LABELS = {
    text: "متن",
    photo: "تصویر",
    video: "ویدیو",
    document: "فایل",
    voice: "صوت",
    audio: "صوت",
    poll: "نظرسنجی",
    sticker: "استیکر",
    gif: "گیف",
    link: "لینک",
    unknown: "سایر",
};

const TRIGGER_LABELS = {
    manual: "دستی",
    scheduled: "زمان‌بندی خودکار",
};

const STATUS_LABELS = {
    ok: "موفق",
    success: "موفق",
    error: "خطا",
    pending: "در انتظار",
    syncing: "در حال دریافت",
};

/* ------------------------------ Helpers ------------------------------ */

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const FA_DIGITS = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"];

function toFa(input) {
    if (input === null || input === undefined) return "—";
    return String(input).replace(/\d/g, (d) => FA_DIGITS[Number(d)]);
}

function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function formatNumberFa(value) {
    if (value === null || value === undefined || value === "") return "—";
    const num = Number(value);
    if (Number.isNaN(num)) return toFa(value);
    return toFa(num.toLocaleString("en-US"));
}

function formatBytesFa(bytes) {
    const n = Number(bytes || 0);
    if (!n) return "۰ کیلوبایت";
    if (n < 1024) return `${toFa(n)} بایت`;
    if (n < 1024 * 1024) return `${toFa((n / 1024).toFixed(1))} کیلوبایت`;
    return `${toFa((n / (1024 * 1024)).toFixed(2))} مگابایت`;
}

function intervalLabelFa(value, unit) {
    const unitMap = { minutes: "دقیقه", hours: "ساعت", days: "روز" };
    const unitFa = unitMap[unit] || unit;
    const v = Number(value);
    const pretty = Number.isInteger(v) ? v : Number(v.toFixed(2));
    return `هر ${toFa(pretty)} ${unitFa}`;
}

function splitDisplay(display) {
    // "1405/08/17 - 14:32:05"
    if (!display) return { date: "—", time: "—" };
    const parts = String(display).split(" - ");
    if (parts.length === 2) return { date: parts[0], time: parts[1] };
    return { date: display, time: "" };
}

function showToast(message, type = "info", timeout = 4200) {
    const container = $("#toastContainer");
    if (!container) return;
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);
    window.setTimeout(() => {
        el.style.opacity = "0";
        el.style.transition = "opacity 0.2s ease";
        window.setTimeout(() => el.remove(), 220);
    }, timeout);
}

async function apiFetch(path, options = {}) {
    const opts = Object.assign({ headers: {} }, options);
    if (opts.body && typeof opts.body !== "string") {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(opts.body);
    }
    opts.headers["Accept"] = "application/json";

    let response;
    try {
        response = await fetch(path, opts);
    } catch (err) {
        throw new Error("ارتباط با سرور برنامه برقرار نشد. لطفاً مطمئن شوید برنامه در حال اجراست.");
    }

    if (!response.ok) {
        let detail = `خطای سرور (کد ${response.status})`;
        try {
            const body = await response.json();
            if (body && body.detail) {
                detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
            }
        } catch (_) {
            /* ignore parse errors */
        }
        throw new Error(detail);
    }

    if (response.status === 204) return null;
    const contentType = response.headers.get("Content-Type") || "";
    if (contentType.includes("application/json")) return response.json();
    return response;
}

function setBusy(button, busy, busyLabel = "در حال انجام...") {
    if (!button) return;
    if (busy) {
        button.dataset.originalText = button.innerHTML;
        button.disabled = true;
        button.innerHTML = `<span class="spinner-inline"></span>${busyLabel}`;
    } else {
        button.disabled = false;
        if (button.dataset.originalText) button.innerHTML = button.dataset.originalText;
    }
}

function buildQuery(params) {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value === undefined || value === null) return;
        if (typeof value === "string" && value.trim() === "") return;
        if (value === "all") return;
        usp.set(key, String(value).trim());
    });
    const qs = usp.toString();
    return qs ? `?${qs}` : "";
}

/* ------------------------------ Tabs ------------------------------ */

function initTabs() {
    $$(".tab-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            $$(".tab-btn").forEach((b) => b.classList.remove("active"));
            $$(".tab-panel").forEach((p) => p.classList.remove("active"));
            btn.classList.add("active");
            const panel = document.getElementById(`tab-${btn.dataset.tab}`);
            if (panel) panel.classList.add("active");

            if (btn.dataset.tab === "logs") loadLogs();
            if (btn.dataset.tab === "settings") loadSettings();
            if (btn.dataset.tab === "posts") loadPosts();
        });
    });
}

function initModals() {
    $$("[data-close-modal]").forEach((btn) => {
        btn.addEventListener("click", () => {
            const modal = document.getElementById(btn.dataset.closeModal);
            if (modal) modal.classList.add("hidden");
        });
    });

    $$(".modal-backdrop").forEach((backdrop) => {
        backdrop.addEventListener("click", (event) => {
            if (event.target === backdrop) backdrop.classList.add("hidden");
        });
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            $$(".modal-backdrop").forEach((m) => m.classList.add("hidden"));
        }
    });
}

/* ------------------------------ Overview ------------------------------ */

async function loadOverview() {
    try {
        const data = await apiFetch("/api/overview");
        const stats = data.stats || {};
        state.timezone = data.timezone || state.timezone;

        $("#statTotalChannels").textContent = formatNumberFa(stats.total_channels);
        $("#statActiveChannels").textContent = formatNumberFa(stats.active_channels);
        $("#statTotalPosts").textContent = formatNumberFa(stats.total_posts);
        $("#postsCountBadge").textContent = toFa(stats.total_posts || 0);

        const latest = splitDisplay(stats.latest_post_display);
        $("#statLatestPost").textContent = stats.latest_post_display
            ? `آخرین مطلب ذخیره‌شده: ${latest.date} ساعت ${latest.time}`
            : "هنوز مطلبی ذخیره نشده است";

        const nextFetch = splitDisplay(stats.nearest_next_fetch_display);
        $("#statNextFetch").textContent = stats.nearest_next_fetch_display
            ? `${nextFetch.date} ساعت ${nextFetch.time}`
            : "هیچ اجرای خودکاری در صف نیست";

        const modeLabels = {
            auto: "هوشمند (وب + Telethon)",
            web: "نسخه وب عمومی (بدون لاگین)",
            telethon: "پروتکل Telethon (اکانت)",
        };
        $("#statCollectorMode").textContent = modeLabels[data.collector_mode] || "هوشمند";
        $("#statDbInfo").textContent = `حجم SQLite: ${formatBytesFa(stats.db_size_bytes)}`;

        const scheduler = data.scheduler || {};
        const badge = $("#schedulerBadge");
        const badgeText = $("#schedulerBadgeText");
        if (scheduler.running) {
            badge.classList.remove("stopped");
            badge.classList.add("running");
            badgeText.textContent = `زمان‌بند خودکار فعال (هر ${toFa(scheduler.tick_seconds || 30)} ثانیه)`;
        } else {
            badge.classList.remove("running");
            badge.classList.add("stopped");
            badgeText.textContent = "زمان‌بند خودکار غیرفعال";
        }
    } catch (err) {
        console.error(err);
    }
}

/* ------------------------------ Channels ------------------------------ */

function statusBadge(ch) {
    if (!ch.is_active) {
        return '<span class="badge badge-paused">غیرفعال</span>';
    }
    if (ch.last_status === "syncing") {
        return '<span class="badge badge-syncing">در حال دریافت</span>';
    }
    if (ch.last_status === "error") {
        return '<span class="badge badge-error">خطای دریافت</span>';
    }
    if (ch.last_status === "pending") {
        return '<span class="badge badge-pending">در انتظار اولین دریافت</span>';
    }
    return '<span class="badge badge-ok">فعال و پایش‌شده</span>';
}

function renderChannels() {
    const tbody = $("#channelsTableBody");
    if (!tbody) return;

    if (!state.channels.length) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" class="empty-cell">
                    هنوز کانالی اضافه نکرده‌اید. از فرم بالا آدرس کانال تلگرام را وارد کنید.
                    برای تست سریع بدون اینترنت نیز می‌توانید «بارگذاری داده نمونه آزمایشی» را بزنید.
                </td>
            </tr>`;
        return;
    }

    tbody.innerHTML = state.channels
        .map((ch) => {
            const lastId = ch.last_message_id === null || ch.last_message_id === undefined
                ? '<span class="badge badge-pending">— اولین دریافت انجام نشده —</span>'
                : `<span class="id-pill ltr-text">${toFa(ch.last_message_id)}</span>`;
            const lastFetched = splitDisplay(ch.last_fetched_display);
            const nextFetch = splitDisplay(ch.next_fetch_display);
            const demoBadge = ch.is_demo ? '<span class="badge badge-demo">نمونه</span>' : "";
            const privateBadge = ch.is_private
                ? '<span class="badge badge-paused" title="نیازمند Telethon">خصوصی</span>'
                : "";
            const errorHint = ch.last_error
                ? `<div class="error-hint" title="${escapeHtml(ch.last_error)}">${escapeHtml(
                      String(ch.last_error).slice(0, 90)
                  )}${String(ch.last_error).length > 90 ? "…" : ""}</div>`
                : "";

            return `
            <tr>
                <td>
                    <div class="ch-title-wrap">
                        <span class="ch-title">${escapeHtml(ch.title)} ${demoBadge}${privateBadge}</span>
                        <a class="ch-link ltr-text" href="${escapeHtml(ch.canonical_url)}" target="_blank" rel="noopener noreferrer">
                            ${escapeHtml(ch.canonical_url)}
                        </a>
                    </div>
                </td>
                <td>${intervalLabelFa(ch.interval_value, ch.interval_unit)}</td>
                <td>${lastId}</td>
                <td><strong>${formatNumberFa(ch.posts_count)}</strong></td>
                <td>${ch.last_fetched_display
                    ? `<div class="date-stack"><span class="date-jalali">${toFa(lastFetched.date)}</span><span class="date-greg ltr-text">${toFa(lastFetched.time)}</span></div>`
                    : '<span class="muted">—</span>'}</td>
                <td>${ch.is_active && ch.next_fetch_display
                    ? `<div class="date-stack"><span class="date-jalali">${toFa(nextFetch.date)}</span><span class="date-greg ltr-text">${toFa(nextFetch.time)}</span></div>`
                    : '<span class="muted">—</span>'}</td>
                <td>${statusBadge(ch)}${errorHint}</td>
                <td>
                    <div class="row-actions">
                        <button class="btn btn-outline btn-sm" data-action="sync" data-id="${ch.id}">دریافت الان</button>
                        <button class="btn btn-ghost btn-sm" data-action="edit" data-id="${ch.id}">ویرایش</button>
                        <button class="btn btn-ghost btn-sm" data-action="toggle" data-id="${ch.id}">
                            ${ch.is_active ? "غیرفعال" : "فعال"}
                        </button>
                        <button class="btn btn-danger-ghost btn-sm" data-action="delete" data-id="${ch.id}">حذف</button>
                    </div>
                </td>
            </tr>`;
        })
        .join("");
}

async function loadChannels() {
    try {
        const data = await apiFetch("/api/channels");
        state.channels = data.items || [];
        renderChannels();
        populateChannelFilter();
    } catch (err) {
        showToast(err.message, "error");
    }
}

function populateChannelFilter() {
    const select = $("#filterChannel");
    if (!select) return;
    const current = select.value;
    const options = ['<option value="">همه کانال‌ها</option>'].concat(
        state.channels.map(
            (ch) => `<option value="${ch.id}">${escapeHtml(ch.title)}</option>`
        )
    );
    select.innerHTML = options.join("");
    if (current && state.channels.some((c) => String(c.id) === String(current))) {
        select.value = current;
    }
}

function initChannelForm() {
    const form = $("#addChannelForm");
    const intervalValue = $("#intervalValue");
    const intervalUnit = $("#intervalUnit");

    $$(".chip").forEach((chip) => {
        chip.addEventListener("click", () => {
            $$(".chip").forEach((c) => c.classList.remove("active"));
            chip.classList.add("active");
            intervalValue.value = chip.dataset.val;
            intervalUnit.value = chip.dataset.unit;
        });
    });

    [intervalValue, intervalUnit].forEach((el) => {
        el.addEventListener("input", () => {
            const match = $$(".chip").find(
                (c) =>
                    String(c.dataset.val) === String(intervalValue.value) &&
                    c.dataset.unit === intervalUnit.value
            );
            $$(".chip").forEach((c) => c.classList.toggle("active", c === match));
        });
    });

    if (!form) return;

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = $("#btnAddChannel");

        const payload = {
            channel_input: $("#channelInput").value.trim(),
            title: $("#channelTitle").value.trim() || null,
            interval_value: Number(intervalValue.value) || 6,
            interval_unit: intervalUnit.value,
            initial_limit: Number($("#initialLimit").value) || 10,
            is_active: true,
            fetch_now: $("#fetchNowCheck").checked,
        };

        if (!payload.channel_input) {
            showToast("آدرس یا یوزرنیم کانال را وارد کنید.", "error");
            return;
        }
        if (payload.interval_value <= 0) {
            showToast("بازه زمانی بررسی باید بزرگ‌تر از صفر باشد.", "error");
            return;
        }

        setBusy(button, true, "در حال افزودن و دریافت...");
        try {
            const res = await apiFetch("/api/channels", { method: "POST", body: payload });
            const ch = res.channel || {};
            let msg = `کانال «${ch.title || payload.channel_input}» با موفقیت اضافه شد.`;
            if (res.sync_result) {
                if (res.sync_result.status === "success") {
                    msg += ` ${toFa(res.sync_result.new_saved_count || 0)} مطلب جدید ذخیره شد.`;
                } else {
                    msg += ` اما دریافت اولیه انجام نشد: ${res.sync_result.message || ""}`;
                }
            }
            showToast(msg, res.sync_result && res.sync_result.status !== "success" ? "error" : "success");

            form.reset();
            $("#initialLimit").value = "10";
            $("#fetchNowCheck").checked = true;
            $("#intervalValue").value = "6";
            $("#intervalUnit").value = "hours";
            $$(".chip").forEach((c) =>
                c.classList.toggle("active", c.dataset.val === "6" && c.dataset.unit === "hours")
            );

            await Promise.all([loadChannels(), loadOverview()]);
        } catch (err) {
            showToast(err.message, "error");
        } finally {
            setBusy(button, false);
        }
    });
}

function openEditModal(channelId) {
    const ch = state.channels.find((c) => String(c.id) === String(channelId));
    if (!ch) return;
    state.editingChannelId = ch.id;
    $("#editChannelId").value = ch.id;
    $("#editChannelTitle").value = ch.title || "";
    $("#editIntervalValue").value = ch.interval_value;
    $("#editIntervalUnit").value = ch.interval_unit;
    $("#editInitialLimit").value = ch.initial_limit;
    $("#editChannelActive").checked = Boolean(ch.is_active);
    $("#editChannelModal").classList.remove("hidden");
}

function initEditForm() {
    const form = $("#editChannelForm");
    if (!form) return;
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const id = $("#editChannelId").value;
        if (!id) return;

        const payload = {
            title: $("#editChannelTitle").value.trim(),
            interval_value: Number($("#editIntervalValue").value),
            interval_unit: $("#editIntervalUnit").value,
            initial_limit: Number($("#editInitialLimit").value),
            is_active: $("#editChannelActive").checked,
        };

        try {
            await apiFetch(`/api/channels/${id}`, { method: "PUT", body: payload });
            $("#editChannelModal").classList.add("hidden");
            showToast("تنظیمات کانال با موفقیت ذخیره شد.", "success");
            await Promise.all([loadChannels(), loadOverview()]);
        } catch (err) {
            showToast(err.message, "error");
        }
    });
}

async function handleChannelAction(action, channelId, button) {
    const ch = state.channels.find((c) => String(c.id) === String(channelId));

    if (action === "edit") {
        openEditModal(channelId);
        return;
    }

    if (action === "sync") {
        setBusy(button, true, "دریافت...");
        try {
            const res = await apiFetch(`/api/channels/${channelId}/sync`, { method: "POST" });
            const r = res.sync_result || {};
            if (r.status === "success") {
                showToast(
                    `${r.channel_title || "کانال"}: ${toFa(r.new_saved_count || 0)} مطلب جدید ذخیره شد. (شناسه آخرین پیام: ${toFa(r.new_last_message_id)})`,
                    "success"
                );
            } else {
                showToast(r.message || "دریافت مطالب با خطا مواجه شد.", "error");
            }
            await Promise.all([loadChannels(), loadOverview()]);
        } catch (err) {
            showToast(err.message, "error");
        } finally {
            setBusy(button, false);
        }
        return;
    }

    if (action === "toggle") {
        if (!ch) return;
        try {
            await apiFetch(`/api/channels/${channelId}`, {
                method: "PUT",
                body: { is_active: !ch.is_active },
            });
            showToast(
                `کانال «${ch.title}» ${ch.is_active ? "غیرفعال" : "فعال"} شد.`,
                "success"
            );
            await Promise.all([loadChannels(), loadOverview()]);
        } catch (err) {
            showToast(err.message, "error");
        }
        return;
    }

    if (action === "delete") {
        if (!ch) return;
        const confirmed = window.confirm(
            `آیا از حذف کانال «${ch.title}» به همراه تمام مطالب ذخیره‌شده آن مطمئن هستید؟`
        );
        if (!confirmed) return;
        try {
            await apiFetch(`/api/channels/${channelId}`, { method: "DELETE" });
            showToast("کانال و مطالب مرتبط با آن حذف شد.", "success");
            await Promise.all([loadChannels(), loadOverview(), loadPosts()]);
        } catch (err) {
            showToast(err.message, "error");
        }
    }
}

function initChannelTableEvents() {
    const tbody = $("#channelsTableBody");
    if (!tbody) return;
    tbody.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-action]");
        if (!button) return;
        handleChannelAction(button.dataset.action, button.dataset.id, button);
    });
}

async function syncAllChannels() {
    const button = $("#btnSyncAll");
    setBusy(button, true, "در حال دریافت از همه کانال‌ها...");
    try {
        const res = await apiFetch("/api/channels/sync-all", { method: "POST" });
        if (!res.checked_channels) {
            showToast("هیچ کانال فعالی برای دریافت وجود ندارد.", "info");
        } else {
            showToast(
                `بررسی ${toFa(res.checked_channels)} کانال انجام شد: ${toFa(res.success_count)} موفق، ${toFa(
                    res.error_count
                )} خطا و ${toFa(res.total_new_posts)} مطلب جدید.`,
                res.error_count ? "error" : "success",
                6000
            );
        }
        await Promise.all([loadChannels(), loadOverview(), loadPosts(), loadLogs()]);
    } catch (err) {
        showToast(err.message, "error");
    } finally {
        setBusy(button, false);
    }
}

/* ------------------------------ Posts ------------------------------ */

function mediaBadge(mediaType) {
    const key = (mediaType || "text").toLowerCase();
    const label = MEDIA_LABELS[key] || key;
    const cls = key === "text" ? "badge-paused" : "badge-syncing";
    return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
}

function renderPosts() {
    const tbody = $("#postsTableBody");
    if (!tbody) return;
    const items = state.posts.items;

    if (!items.length) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" class="empty-cell">
                    مطلبی مطابق با فیلترهای فعلی یافت نشد. اگر هنوز هیچ مطلبی ندارید، ابتدا یک کانال اضافه کنید یا داده نمونه را بارگذاری نمایید.
                </td>
            </tr>`;
    } else {
        tbody.innerHTML = items
            .map((p) => {
                const views = p.views === null || p.views === undefined ? "—" : formatNumberFa(p.views);
                const snippet = escapeHtml(p.content || "[بدون متن]");
                return `
                <tr>
                    <td>
                        <div class="ch-title-wrap">
                            <span class="ch-title">${escapeHtml(p.channel_title)}</span>
                            <a class="ch-link ltr-text" href="${escapeHtml(
                                p.channel_url || p.post_url
                            )}" target="_blank" rel="noopener noreferrer">@${escapeHtml(
                    p.channel_username || ""
                )}</a>
                        </div>
                    </td>
                    <td><span class="id-pill ltr-text">${toFa(p.message_id)}</span></td>
                    <td>
                        <div class="date-stack">
                            <span class="date-jalali">${toFa(p.published_jalali_date)}</span>
                            <span class="date-greg ltr-text">${toFa(p.published_date)}</span>
                        </div>
                    </td>
                    <td class="ltr-text">${toFa(p.published_time)}</td>
                    <td>
                        <div class="date-stack">
                            ${mediaBadge(p.media_type)}
                            <span class="date-greg">${views} بازدید</span>
                        </div>
                    </td>
                    <td><div class="post-snippet">${snippet}</div></td>
                    <td>
                        <a class="btn btn-outline btn-sm" href="${escapeHtml(
                            p.post_url
                        )}" target="_blank" rel="noopener noreferrer">مشاهده در تلگرام</a>
                    </td>
                    <td>
                        <div class="row-actions">
                            <button class="btn btn-ghost btn-sm" data-post-action="detail" data-id="${p.id}">جزئیات</button>
                            <button class="btn btn-danger-ghost btn-sm" data-post-action="delete" data-id="${p.id}">حذف</button>
                        </div>
                    </td>
                </tr>`;
            })
            .join("");
    }

    const info = $("#postsPaginationInfo");
    if (info) {
        const start = state.posts.total === 0 ? 0 : (state.posts.page - 1) * state.posts.pageSize + 1;
        const end = Math.min(state.posts.page * state.posts.pageSize, state.posts.total);
        info.textContent = `نمایش ${toFa(start)} تا ${toFa(end)} از مجموع ${toFa(
            state.posts.total
        )} مطلب`;
    }
    const indicator = $("#pageIndicator");
    if (indicator) {
        indicator.textContent = `صفحه ${toFa(state.posts.page)} از ${toFa(state.posts.totalPages)}`;
    }
    const prev = $("#btnPrevPage");
    const next = $("#btnNextPage");
    if (prev) prev.disabled = state.posts.page <= 1;
    if (next) next.disabled = state.posts.page >= state.posts.totalPages;
}

async function loadPosts() {
    try {
        const query = buildQuery({
            channel_id: state.filters.channel_id,
            search: state.filters.search,
            date_from: state.filters.date_from,
            date_to: state.filters.date_to,
            media_type: state.filters.media_type,
            page: state.posts.page,
            page_size: state.posts.pageSize,
        });
        const data = await apiFetch(`/api/posts${query}`);
        state.posts.items = data.items || [];
        state.posts.total = data.total || 0;
        state.posts.page = data.page || 1;
        state.posts.totalPages = data.total_pages || 1;
        renderPosts();
    } catch (err) {
        showToast(err.message, "error");
    }
}

function openPostDetail(postId) {
    const post = state.posts.items.find((p) => String(p.id) === String(postId));
    if (!post) return;
    state.activeModalPost = post;

    $("#modalPostChannelTitle").textContent = post.channel_title;
    $("#modalPostMsgId").textContent = toFa(post.message_id);
    $("#modalPostJalali").textContent = toFa(post.published_jalali_date);
    $("#modalPostGreg").textContent = toFa(post.published_date);
    $("#modalPostTime").textContent = toFa(post.published_time);
    $("#modalPostViews").textContent =
        post.views === null || post.views === undefined ? "—" : formatNumberFa(post.views);
    $("#modalPostContent").textContent = post.content || "[بدون متن]";
    const link = $("#modalPostUrl");
    link.textContent = post.post_url;
    link.href = post.post_url;

    $("#postDetailModal").classList.remove("hidden");
}

async function copyToClipboard(text) {
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
        } else {
            const area = document.createElement("textarea");
            area.value = text;
            area.style.position = "fixed";
            area.style.opacity = "0";
            document.body.appendChild(area);
            area.select();
            document.execCommand("copy");
            area.remove();
        }
        showToast("در حافظه کپی شد.", "success", 2200);
    } catch (err) {
        showToast("کپی کردن ممکن نشد. لطفاً متن را دستی انتخاب کنید.", "error");
    }
}

function initPostsEvents() {
    const form = $("#postFiltersForm");
    if (form) {
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            state.filters.channel_id = $("#filterChannel").value;
            state.filters.search = $("#filterSearch").value.trim();
            state.filters.date_from = $("#filterDateFrom").value.trim();
            state.filters.date_to = $("#filterDateTo").value.trim();
            state.filters.media_type = $("#filterMediaType").value;
            state.posts.page = 1;
            loadPosts();
        });
    }

    const clearBtn = $("#btnClearFilters");
    if (clearBtn) {
        clearBtn.addEventListener("click", () => {
            $("#filterChannel").value = "";
            $("#filterSearch").value = "";
            $("#filterDateFrom").value = "";
            $("#filterDateTo").value = "";
            $("#filterMediaType").value = "all";
            state.filters = { channel_id: "", search: "", date_from: "", date_to: "", media_type: "all" };
            state.posts.page = 1;
            loadPosts();
        });
    }

    const prev = $("#btnPrevPage");
    const next = $("#btnNextPage");
    if (prev) {
        prev.addEventListener("click", () => {
            if (state.posts.page > 1) {
                state.posts.page -= 1;
                loadPosts();
            }
        });
    }
    if (next) {
        next.addEventListener("click", () => {
            if (state.posts.page < state.posts.totalPages) {
                state.posts.page += 1;
                loadPosts();
            }
        });
    }

    const tbody = $("#postsTableBody");
    if (tbody) {
        tbody.addEventListener("click", async (event) => {
            const button = event.target.closest("button[data-post-action]");
            if (!button) return;
            const action = button.dataset.postAction;
            const id = button.dataset.id;

            if (action === "detail") {
                openPostDetail(id);
                return;
            }

            if (action === "delete") {
                if (!window.confirm("آیا این مطلب از آرشیو حذف شود؟")) return;
                try {
                    await apiFetch(`/api/posts/${id}`, { method: "DELETE" });
                    showToast("مطلب حذف شد.", "success");
                    await Promise.all([loadPosts(), loadOverview()]);
                } catch (err) {
                    showToast(err.message, "error");
                }
            }
        });
    }

    const copyText = $("#btnCopyPostText");
    if (copyText) {
        copyText.addEventListener("click", () => {
            if (state.activeModalPost) copyToClipboard(state.activeModalPost.content || "");
        });
    }
    const copyLink = $("#btnCopyPostLink");
    if (copyLink) {
        copyLink.addEventListener("click", () => {
            if (state.activeModalPost) copyToClipboard(state.activeModalPost.post_url || "");
        });
    }
}

/* ------------------------------ Exports ------------------------------ */

function currentFiltersForExport() {
    return {
        channel_id: state.filters.channel_id,
        search: state.filters.search,
        date_from: state.filters.date_from,
        date_to: state.filters.date_to,
        media_type: state.filters.media_type,
    };
}

function triggerDownload(url) {
    const link = document.createElement("a");
    link.href = url;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
}

function initExports() {
    const quickExcel = $("#btnQuickExcel");
    if (quickExcel) {
        quickExcel.addEventListener("click", () => {
            triggerDownload("/api/exports/excel");
            showToast("فایل اکسل کامل در حال دانلود است...", "success");
        });
    }

    const quickSqlite = $("#btnQuickSqlite");
    if (quickSqlite) {
        quickSqlite.addEventListener("click", () => {
            triggerDownload("/api/exports/sqlite");
            showToast("فایل دیتابیس SQLite در حال دانلود است...", "success");
        });
    }

    const filteredExcel = $("#btnExportFilteredExcel");
    if (filteredExcel) {
        filteredExcel.addEventListener("click", () => {
            triggerDownload(`/api/exports/excel${buildQuery(currentFiltersForExport())}`);
            showToast("خروجی اکسل بر اساس فیلتر فعلی در حال دانلود است...", "success");
        });
    }

    const fullSqlite = $("#btnExportFullSqlite");
    if (fullSqlite) {
        fullSqlite.addEventListener("click", () => {
            triggerDownload("/api/exports/sqlite");
            showToast("کل دیتابیس در حال دانلود است...", "success");
        });
    }

    const filteredSqlite = $("#btnExportFilteredSqlite");
    if (filteredSqlite) {
        filteredSqlite.addEventListener("click", () => {
            const query = buildQuery(Object.assign({ filtered_only: "true" }, currentFiltersForExport()));
            triggerDownload(`/api/exports/sqlite${query}`);
            showToast("خروجی SQLite فیلترشده در حال دانلود است...", "success");
        });
    }
}

/* ------------------------------ Logs ------------------------------ */

function renderLogs(items) {
    const tbody = $("#logsTableBody");
    if (!tbody) return;

    if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-cell">هنوز گزارشی از دریافت مطالب ثبت نشده است.</td></tr>';
        return;
    }

    tbody.innerHTML = items
        .map((log) => {
            const statusCls = log.status === "success" ? "badge-ok" : "badge-error";
            const statusText = STATUS_LABELS[log.status] || log.status;
            return `
            <tr>
                <td class="ltr-text">${toFa(log.created_display || log.created_at)}</td>
                <td>${escapeHtml(log.channel_title)}</td>
                <td>${escapeHtml(TRIGGER_LABELS[log.trigger_type] || log.trigger_type)}</td>
                <td>${escapeHtml(log.source_mode === "telethon" ? "Telethon" : "وب عمومی")}</td>
                <td><strong>${formatNumberFa(log.new_saved_count)}</strong></td>
                <td class="ltr-text">${toFa(log.previous_last_message_id)} &rarr; ${toFa(log.new_last_message_id)}</td>
                <td>${toFa(log.duration_ms)} ms</td>
                <td>
                    <span class="badge ${statusCls}">${escapeHtml(statusText)}</span>
                    <div class="error-hint" style="color:#475569" title="${escapeHtml(log.message || "")}">
                        ${escapeHtml(String(log.message || "").slice(0, 110))}${String(log.message || "").length > 110 ? "…" : ""}
                    </div>
                </td>
            </tr>`;
        })
        .join("");
}

async function loadLogs() {
    try {
        const data = await apiFetch("/api/logs?limit=150");
        renderLogs(data.items || []);
    } catch (err) {
        showToast(err.message, "error");
    }
}

function initLogsEvents() {
    const refresh = $("#btnRefreshLogs");
    if (refresh) refresh.addEventListener("click", () => loadLogs());

    const clear = $("#btnClearLogs");
    if (clear) {
        clear.addEventListener("click", async () => {
            if (!window.confirm("تمام تاریخچه گزارش‌ها پاک شود؟")) return;
            try {
                await apiFetch("/api/logs", { method: "DELETE" });
                showToast("تاریخچه گزارش‌ها پاک شد.", "success");
                loadLogs();
            } catch (err) {
                showToast(err.message, "error");
            }
        });
    }
}

/* ------------------------------ Settings ------------------------------ */

function updateTelethonBanner(telethon, installed = true) {
    const banner = $("#telethonStatusBanner");
    if (!banner) return;
    const info = telethon || {};

    if (installed === false) {
        banner.className = "status-banner warning";
        banner.textContent =
            "کتابخانه Telethon روی این سیستم نصب نیست. کانال‌های عمومی با موتور وب کار می‌کنند؛ برای کانال‌های خصوصی در پوشه برنامه اجرا کنید: pip install -r requirements-telethon.txt";
        return;
    }

    if (info.authorized) {
        banner.className = "status-banner connected";
        banner.textContent = info.account
            ? `وضعیت Telethon: متصل (${info.account})`
            : "وضعیت Telethon: متصل به اکانت تلگرام";
        $("#telethonVerifyBox").classList.add("hidden");
    } else if (info.configured) {
        banner.className = "status-banner neutral";
        banner.textContent =
            "وضعیت Telethon: کلیدهای API ذخیره شده اما نشست فعال نیست. برای کانال‌های خصوصی روی «ارسال کد تایید» بزنید.";
    } else {
        banner.className = "status-banner neutral";
        banner.textContent =
            "وضعیت Telethon: متصل نشده — موتور وب عمومی بدون لاگین برای کانال‌های عمومی فعال است.";
    }
    if (info.error) {
        banner.textContent += ` | ${info.error}`;
    }
}

async function loadSettings(checkNetwork = false) {
    try {
        const data = await apiFetch(`/api/settings?check_telethon_network=${checkNetwork ? "true" : "false"}`);
        const s = data.settings || {};

        $("#settingCollectorMode").value = s.collector_mode || "auto";
        $("#settingTimezone").value = s.timezone || "Asia/Tehran";
        $("#settingDefaultLimit").value = s.default_initial_limit || 10;

        $("#settingProxyEnabled").checked = Boolean(s.proxy_enabled);
        $("#settingProxyType").value = s.proxy_type || "socks5";
        $("#settingProxyHost").value = s.proxy_host || "";
        $("#settingProxyPort").value = s.proxy_port || "";
        $("#settingProxyUser").value = s.proxy_username || "";
        $("#settingProxyPass").value = s.proxy_password_set ? "********" : "";
        toggleProxyFields();

        $("#telethonApiId").value = s.telethon_api_id || "";
        $("#telethonApiHash").value = s.telethon_api_hash_set ? "********" : "";
        $("#telethonPhone").value = s.telethon_phone || "";

        updateTelethonBanner(data.telethon, data.telethon_installed);
    } catch (err) {
        showToast(err.message, "error");
    }
}

function toggleProxyFields() {
    const enabled = $("#settingProxyEnabled").checked;
    const box = $("#proxyFieldsBox");
    if (!box) return;
    box.style.opacity = enabled ? "1" : "0.55";
    box.style.pointerEvents = enabled ? "auto" : "none";
}

function collectSettingsPayload() {
    return {
        collector_mode: $("#settingCollectorMode").value,
        timezone: $("#settingTimezone").value,
        default_initial_limit: Number($("#settingDefaultLimit").value) || 10,
        telethon_api_id: $("#telethonApiId").value.trim(),
        telethon_api_hash: $("#telethonApiHash").value,
        telethon_phone: $("#telethonPhone").value.trim(),
        proxy_enabled: $("#settingProxyEnabled").checked,
        proxy_type: $("#settingProxyType").value,
        proxy_host: $("#settingProxyHost").value.trim(),
        proxy_port: $("#settingProxyPort").value.trim(),
        proxy_username: $("#settingProxyUser").value.trim(),
        proxy_password: $("#settingProxyPass").value,
    };
}

function initSettingsEvents() {
    const proxyToggle = $("#settingProxyEnabled");
    if (proxyToggle) proxyToggle.addEventListener("change", toggleProxyFields);

    const form = $("#settingsForm");
    if (form) {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const button = form.querySelector('button[type="submit"]');
            setBusy(button, true, "در حال ذخیره...");
            try {
                const data = await apiFetch("/api/settings", {
                    method: "PUT",
                    body: collectSettingsPayload(),
                });
                updateTelethonBanner(data.telethon, data.telethon_installed);
                showToast("تنظیمات با موفقیت ذخیره شد.", "success");
                await loadOverview();
            } catch (err) {
                showToast(err.message, "error");
            } finally {
                setBusy(button, false);
            }
        });
    }

    const sendCode = $("#btnSendCode");
    if (sendCode) {
        sendCode.addEventListener("click", async () => {
            const phone = $("#telethonPhone").value.trim();
            if (!phone) {
                showToast("شماره موبایل اکانت تلگرام را وارد کنید.", "error");
                return;
            }
            setBusy(sendCode, true, "ارسال کد...");
            try {
                const payload = {
                    phone,
                    api_id: $("#telethonApiId").value.trim() || null,
                    api_hash: $("#telethonApiHash").value,
                };
                const res = await apiFetch("/api/telethon/send-code", { method: "POST", body: payload });
                $("#telethonVerifyBox").classList.remove("hidden");
                showToast(res.message || "کد تایید ارسال شد. کد دریافتی را وارد کنید.", "success", 6000);
            } catch (err) {
                showToast(err.message, "error", 7000);
            } finally {
                setBusy(sendCode, false);
            }
        });
    }

    const verify = $("#btnVerifyCode");
    if (verify) {
        verify.addEventListener("click", async () => {
            const phone = $("#telethonPhone").value.trim();
            const code = $("#telethonCode").value.trim();
            const password = $("#telethon2FA").value.trim() || null;
            if (!code) {
                showToast("کد تایید دریافتی را وارد کنید.", "error");
                return;
            }
            setBusy(verify, true, "در حال تایید...");
            try {
                const res = await apiFetch("/api/telethon/verify-code", {
                    method: "POST",
                    body: { phone, code, password },
                });
                showToast(res.message || "اتصال اکانت تلگرام با موفقیت انجام شد.", "success", 6000);
                await loadSettings(true);
            } catch (err) {
                showToast(err.message, "error", 7000);
            } finally {
                setBusy(verify, false);
            }
        });
    }

    const saveCreds = $("#btnSaveTelethonCreds");
    if (saveCreds) {
        saveCreds.addEventListener("click", async () => {
            setBusy(saveCreds, true, "ذخیره...");
            try {
                const data = await apiFetch("/api/settings", {
                    method: "PUT",
                    body: collectSettingsPayload(),
                });
                updateTelethonBanner(data.telethon, data.telethon_installed);
                showToast("کلیدهای API ذخیره شد.", "success");
            } catch (err) {
                showToast(err.message, "error");
            } finally {
                setBusy(saveCreds, false);
            }
        });
    }

    const logout = $("#btnLogoutTelethon");
    if (logout) {
        logout.addEventListener("click", async () => {
            if (!window.confirm("نشست Telethon حذف شود؟ برای کانال‌های خصوصی باید دوباره وارد شوید.")) return;
            setBusy(logout, true, "خروج...");
            try {
                const res = await apiFetch("/api/telethon/logout", { method: "POST" });
                showToast(res.message || "نشست حذف شد.", "success");
                await loadSettings(false);
            } catch (err) {
                showToast(err.message, "error");
            } finally {
                setBusy(logout, false);
            }
        });
    }

    const seed = $("#btnSeedDemo");
    if (seed) seed.addEventListener("click", () => runSeedDemo(seed));

    const seedQuick = $("#btnSeedDemoQuick");
    if (seedQuick) seedQuick.addEventListener("click", () => runSeedDemo(seedQuick));

    const clearDemo = $("#btnClearDemo");
    if (clearDemo) {
        clearDemo.addEventListener("click", async () => {
            if (!window.confirm("تمام کانال‌ها و مطالب آزمایشی (نمونه) حذف شوند؟")) return;
            setBusy(clearDemo, true, "پاک‌سازی...");
            try {
                const res = await apiFetch("/api/demo", { method: "DELETE" });
                showToast(res.message || "داده‌های آزمایشی پاک شد.", "success");
                await Promise.all([loadChannels(), loadOverview(), loadPosts(), loadLogs()]);
            } catch (err) {
                showToast(err.message, "error");
            } finally {
                setBusy(clearDemo, false);
            }
        });
    }
}

async function runSeedDemo(button) {
    setBusy(button, true, "در حال ساخت داده نمونه...");
    try {
        const res = await apiFetch("/api/demo/seed", { method: "POST" });
        showToast(res.message || "داده‌های نمونه بارگذاری شد.", "success", 6000);
        await Promise.all([loadChannels(), loadOverview(), loadPosts(), loadLogs()]);
    } catch (err) {
        showToast(err.message, "error");
    } finally {
        setBusy(button, false);
    }
}

/* ------------------------------ Boot ------------------------------ */

function initMiscEvents() {
    const refreshChannels = $("#btnRefreshChannels");
    if (refreshChannels) {
        refreshChannels.addEventListener("click", async () => {
            await Promise.all([loadChannels(), loadOverview()]);
            showToast("لیست کانال‌ها بروزرسانی شد.", "success", 2000);
        });
    }

    const syncAll = $("#btnSyncAll");
    if (syncAll) syncAll.addEventListener("click", syncAllChannels);
}

async function boot() {
    initTabs();
    initModals();
    initMiscEvents();
    initChannelForm();
    initChannelTableEvents();
    initEditForm();
    initPostsEvents();
    initExports();
    initLogsEvents();
    initSettingsEvents();

    await loadOverview();
    await loadChannels();
    await loadPosts();

    // Auto-refresh overview every 20s so scheduled fetches stay visible
    state.overviewTimer = window.setInterval(() => {
        if (!document.hidden) loadOverview();
    }, 20000);
}

document.addEventListener("DOMContentLoaded", boot);
