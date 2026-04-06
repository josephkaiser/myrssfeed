"use strict";
function getElement(id) {
    return document.getElementById(id);
}
function requireInput(id) {
    const element = getElement(id);
    if (!element) {
        throw new Error(`Missing required input #${id}`);
    }
    return element;
}
function requireSelect(id) {
    const element = getElement(id);
    if (!element) {
        throw new Error(`Missing required select #${id}`);
    }
    return element;
}
function clampInt(rawValue, fallback, min, max) {
    const parsed = Number.parseInt(rawValue ?? "", 10);
    if (Number.isNaN(parsed)) {
        return fallback;
    }
    return Math.min(max, Math.max(min, parsed));
}
function readStoredTheme() {
    const stored = localStorage.getItem("theme");
    return stored === "dark" || stored === "light" || stored === "system" ? stored : "system";
}
function applyTheme(theme) {
    const root = document.documentElement;
    if (theme === "light") {
        root.setAttribute("data-theme", "light");
    }
    else if (theme === "dark") {
        root.setAttribute("data-theme", "dark");
    }
    else {
        root.removeAttribute("data-theme");
    }
}
function refreshToggleUI(theme) {
    document.querySelectorAll("#theme-toggle button").forEach((button) => {
        button.classList.toggle("active", button.dataset.themeVal === theme);
    });
}
function setTheme(theme) {
    localStorage.setItem("theme", theme);
    applyTheme(theme);
    refreshToggleUI(theme);
}
(function initThemeToggle() {
    refreshToggleUI(readStoredTheme());
})();
function getFilterAggressiveness() {
    return clampInt(localStorage.getItem("filter_aggressiveness"), 1, 0, 3);
}
function describeAggressiveness(level) {
    switch (level) {
        case 0:
            return "Very gentle";
        case 1:
            return "Balanced";
        case 2:
            return "Firm";
        case 3:
            return "Aggressive";
        default:
            return "Balanced";
    }
}
(function initFilterAggressiveness() {
    const slider = getElement("filter_aggressiveness");
    const label = getElement("filter_aggressiveness_label");
    if (!slider || !label) {
        return;
    }
    const level = getFilterAggressiveness();
    slider.value = String(level);
    label.textContent = describeAggressiveness(level);
    slider.addEventListener("input", () => {
        const nextLevel = clampInt(slider.value, 1, 0, 3);
        localStorage.setItem("filter_aggressiveness", String(nextLevel));
        label.textContent = describeAggressiveness(nextLevel);
    });
})();
function toast(message, ok = true) {
    const element = getElement("toast");
    if (!element) {
        return;
    }
    element.textContent = message;
    element.style.borderColor = ok ? "var(--accent)" : "var(--danger)";
    element.classList.add("show");
    window.setTimeout(() => {
        element.classList.remove("show");
    }, 2800);
}
function getPipelineRefreshMinutes() {
    const input = getElement("pipeline_refresh_minutes");
    return clampInt(input?.value, 15, 5, 240);
}
function describePipelineRefreshMinutes(minutes) {
    const value = Math.min(240, Math.max(5, minutes));
    return `${value} min`;
}
function updatePipelineRefreshDial() {
    const input = getElement("pipeline_refresh_minutes");
    const label = getElement("pipeline_refresh_minutes_value");
    if (!input || !label) {
        return;
    }
    const minutes = getPipelineRefreshMinutes();
    input.value = String(minutes);
    label.textContent = describePipelineRefreshMinutes(minutes);
}
async function readJson(response) {
    return (await response.json().catch(() => ({})));
}
async function saveSettings() {
    const retentionInput = requireInput("retention_days");
    const days = Number.parseInt(retentionInput.value, 10);
    if (Number.isNaN(days) || days < 0 || days > 3650) {
        toast("Retention must be 0–3650 days.", false);
        retentionInput.focus();
        return;
    }
    const maxEntriesInput = requireInput("max_entries");
    const maxEntriesValue = Number.parseInt(maxEntriesInput.value, 10);
    if (Number.isNaN(maxEntriesValue) || maxEntriesValue < 50 || maxEntriesValue > 20000) {
        toast("Maximum articles must be between 50 and 20000.", false);
        maxEntriesInput.focus();
        return;
    }
    const newsletterEnabledSelect = requireSelect("newsletter_enabled");
    const newsletterHostInput = requireInput("newsletter_imap_host");
    const newsletterPortInput = requireInput("newsletter_imap_port");
    const newsletterUserInput = requireInput("newsletter_imap_username");
    const newsletterPassInput = requireInput("newsletter_imap_password");
    const newsletterFolderInput = requireInput("newsletter_imap_folder");
    const newsletterPollInput = requireInput("newsletter_poll_minutes");
    const newsletterPortValue = Number.parseInt(newsletterPortInput.value, 10);
    if (Number.isNaN(newsletterPortValue) || newsletterPortValue < 1 || newsletterPortValue > 65535) {
        toast("Newsletter IMAP port must be between 1 and 65535.", false);
        newsletterPortInput.focus();
        return;
    }
    const newsletterPollValue = Number.parseInt(newsletterPollInput.value, 10);
    if (Number.isNaN(newsletterPollValue) || newsletterPollValue < 5 || newsletterPollValue > 1440) {
        toast("Newsletter poll interval must be between 5 and 1440 minutes.", false);
        newsletterPollInput.focus();
        return;
    }
    if (maxEntriesValue > 5000) {
        toast("Large article lists may be slow on lower-end devices. Make sure this machine has enough disk space and a fast drive.", true);
    }
    const payload = {
        retention_days: String(days),
        theme: readStoredTheme(),
        max_entries: String(maxEntriesValue),
        pipeline_refresh_minutes: String(getPipelineRefreshMinutes()),
        newsletter_enabled: newsletterEnabledSelect.value,
        newsletter_imap_host: newsletterHostInput.value.trim(),
        newsletter_imap_port: String(newsletterPortValue),
        newsletter_imap_username: newsletterUserInput.value.trim(),
        newsletter_imap_password: newsletterPassInput.value,
        newsletter_imap_folder: newsletterFolderInput.value.trim() || "INBOX",
        newsletter_poll_minutes: String(newsletterPollValue),
    };
    const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (response.ok) {
        const statusElement = getElement("save-status");
        if (statusElement) {
            statusElement.classList.add("show");
            window.setTimeout(() => {
                statusElement.classList.remove("show");
            }, 2500);
        }
        window.setTimeout(() => {
            void fetchNewsletterStatus();
        }, 1000);
        return;
    }
    const data = await readJson(response);
    toast(data.detail || "Could not save settings.", false);
}
function updateRefreshStatusUI(state) {
    const dot = getElement("refresh-status-dot");
    const text = getElement("refresh-status-text");
    if (!dot || !text) {
        return;
    }
    dot.className = "refresh-status-dot";
    if (state.running) {
        dot.classList.add("running");
        if (typeof state.completed_feeds === "number" && typeof state.total_feeds === "number" && state.total_feeds > 0) {
            text.textContent = `${state.completed_feeds}/${state.total_feeds} feeds`;
        }
        else {
            text.textContent = state.stage_label || "Running";
        }
        return;
    }
    switch (state.last_status) {
        case "success":
            dot.classList.add("success");
            if (typeof state.minutes_since_last_success === "number") {
                const minutes = state.minutes_since_last_success;
                text.textContent = minutes === 0 ? "Now" : `${minutes}m ago`;
            }
            else {
                text.textContent = "Done";
            }
            break;
        case "error":
            dot.classList.add("error");
            text.textContent = "Failed";
            break;
        case "never":
        default:
            text.textContent = "Ready";
            break;
    }
}
function feedDisplayName(feed) {
    if (!feed) {
        return "feed";
    }
    return feed.title || feed.url || "feed";
}
function renderRefreshProgressDetails(state) {
    const card = getElement("refresh-progress-card");
    const stage = getElement("refresh-progress-stage");
    const count = getElement("refresh-progress-count");
    const fill = getElement("refresh-progress-bar-fill");
    const current = getElement("refresh-progress-current");
    const summary = getElement("refresh-progress-summary");
    const list = getElement("refresh-progress-list");
    if (!card || !stage || !count || !fill || !current || !summary || !list) {
        return;
    }
    const results = Array.isArray(state.feed_results) ? state.feed_results : [];
    const totalFeeds = Math.max(0, Number(state.total_feeds || 0));
    const completedFeeds = Math.max(0, Number(state.completed_feeds || 0));
    const percent = Math.max(0, Math.min(100, Number(state.progress_percent || 0)));
    const shouldShow = state.running || results.length > 0 || totalFeeds > 0 || Boolean(state.message);
    card.hidden = !shouldShow;
    if (!shouldShow) {
        return;
    }
    stage.textContent = state.stage_label || (state.running ? "Refreshing feeds" : "Latest refresh");
    count.textContent = totalFeeds > 0 ? `${completedFeeds} / ${totalFeeds} feeds` : "Waiting";
    fill.style.width = `${percent}%`;
    if (state.running) {
        if (state.current_feed) {
            current.textContent = `Currently pulling ${feedDisplayName(state.current_feed)}`;
        }
        else {
            current.textContent = state.message || "Working…";
        }
    }
    else {
        current.textContent = state.message || "Idle";
    }
    const summaryParts = [];
    if (typeof state.total_items_seen === "number" && state.total_items_seen > 0) {
        summaryParts.push(`${state.total_items_seen.toLocaleString()} items retrieved`);
    }
    if (typeof state.total_new_entries === "number") {
        summaryParts.push(`${state.total_new_entries.toLocaleString()} new`);
    }
    if (typeof state.pruned_entries === "number" && state.pruned_entries > 0) {
        summaryParts.push(`${state.pruned_entries.toLocaleString()} pruned`);
    }
    if (typeof state.quality_updates === "number" && state.quality_updates > 0) {
        summaryParts.push(`${state.quality_updates.toLocaleString()} scored`);
    }
    if (typeof state.theme_updates === "number" && state.theme_updates > 0) {
        summaryParts.push(`${state.theme_updates.toLocaleString()} themed`);
    }
    summary.textContent = summaryParts.join(" • ");
    list.replaceChildren();
    const orderedResults = results.slice().reverse();
    if (!orderedResults.length) {
        const empty = document.createElement("div");
        empty.className = "refresh-progress-empty";
        empty.textContent = state.running ? "No feeds completed yet." : "No recent feed refresh details.";
        list.appendChild(empty);
        return;
    }
    orderedResults.forEach((result) => {
        const item = document.createElement("div");
        item.className = "refresh-progress-item";
        const name = document.createElement("div");
        name.className = "refresh-progress-item-name";
        name.textContent = feedDisplayName(result);
        const status = document.createElement("div");
        status.className = "refresh-progress-item-status";
        const statusValue = (result.status || "success").toLowerCase();
        status.classList.add(statusValue === "error" ? "error" : "success");
        status.textContent = statusValue === "error" ? "Error" : "Done";
        const meta = document.createElement("div");
        meta.className = "refresh-progress-item-meta";
        const metaParts = [
            `${Number(result.items_seen || 0).toLocaleString()} items`,
            `${Number(result.new_entries || 0).toLocaleString()} new`,
        ];
        if (result.warning) {
            metaParts.push("parsed with warnings");
        }
        if (result.error) {
            metaParts.push(result.error);
        }
        meta.textContent = metaParts.join(" • ");
        item.appendChild(name);
        item.appendChild(status);
        item.appendChild(meta);
        list.appendChild(item);
    });
}
async function fetchRefreshStatus() {
    try {
        const response = await fetch("/api/refresh/status?details=1");
        if (!response.ok) {
            return;
        }
        const data = await readJson(response);
        const state = {
            running: Boolean(data.running),
            last_status: data.last_status || "never",
            minutes_since_last_success: typeof data.minutes_since_last_success === "number" ? data.minutes_since_last_success : null,
            stage: data.stage || "",
            stage_label: data.stage_label || "",
            message: data.message || "",
            total_feeds: typeof data.total_feeds === "number" ? data.total_feeds : 0,
            completed_feeds: typeof data.completed_feeds === "number" ? data.completed_feeds : 0,
            progress_percent: typeof data.progress_percent === "number" ? data.progress_percent : 0,
            current_feed: data.current_feed || null,
            total_items_seen: typeof data.total_items_seen === "number" ? data.total_items_seen : 0,
            total_new_entries: typeof data.total_new_entries === "number" ? data.total_new_entries : 0,
            pruned_entries: typeof data.pruned_entries === "number" ? data.pruned_entries : 0,
            quality_updates: typeof data.quality_updates === "number" ? data.quality_updates : 0,
            theme_updates: typeof data.theme_updates === "number" ? data.theme_updates : 0,
            feed_results: Array.isArray(data.feed_results) ? data.feed_results : [],
        };
        updateRefreshStatusUI(state);
        updatePipelineStatusUI(state);
        renderRefreshProgressDetails(state);
    }
    catch {
        // Silently ignore; status light is best-effort only.
    }
}
function updateNewsletterStatusUI(state) {
    const dot = getElement("newsletter-status-dot");
    const text = getElement("newsletter-status-text");
    if (!dot || !text) {
        return;
    }
    dot.className = "refresh-status-dot";
    text.title = "";
    if (state.running) {
        dot.classList.add("running");
        text.textContent = "Sync in progress";
        return;
    }
    switch (state.last_status) {
        case "success":
            dot.classList.add("success");
            if (typeof state.minutes_since_last_success === "number") {
                const minutes = state.minutes_since_last_success;
                text.textContent = minutes === 0 ? "Just now" : `${minutes} min ago`;
            }
            else {
                text.textContent = "Last sync completed";
            }
            break;
        case "error":
            dot.classList.add("error");
            text.textContent = "Last sync failed";
            if (state.last_error) {
                text.title = state.last_error;
            }
            break;
        case "disabled":
            text.textContent = "Disabled";
            break;
        case "never":
        default:
            text.textContent = "No runs yet";
            break;
    }
}
async function fetchNewsletterStatus() {
    try {
        const response = await fetch("/api/newsletters/status");
        if (!response.ok) {
            return;
        }
        const data = await readJson(response);
        updateNewsletterStatusUI({
            running: Boolean(data.running),
            last_status: data.last_status || "never",
            minutes_since_last_success: typeof data.minutes_since_last_success === "number" ? data.minutes_since_last_success : null,
            last_error: data.last_error || "",
        });
    }
    catch {
        // Best-effort only.
    }
}
async function refreshNow() {
    const button = getElement("refresh-now-btn");
    if (!button) {
        return;
    }
    button.disabled = true;
    const originalText = button.textContent;
    button.textContent = "Refreshing...";
    try {
        const response = await fetch("/api/refresh", { method: "POST" });
        const data = await readJson(response);
        if (response.ok) {
            toast(data.message || "Refresh started.");
            updateRefreshStatusUI({ running: true, last_status: "running" });
        }
        else {
            toast(data.detail || "Could not start refresh.", false);
        }
    }
    catch {
        toast("Network error starting refresh.", false);
    }
    finally {
        button.disabled = false;
        button.textContent = originalText;
        window.setTimeout(() => {
            void fetchRefreshStatus();
        }, 2000);
    }
}
(function initStatusPolling() {
    if (getElement("refresh-status-dot")) {
        void fetchRefreshStatus();
        window.setInterval(() => {
            void fetchRefreshStatus();
        }, 2000);
    }
    if (getElement("newsletter-status-dot")) {
        void fetchNewsletterStatus();
        window.setInterval(() => {
            void fetchNewsletterStatus();
        }, 8000);
    }
})();
async function newsletterSyncNow() {
    const button = getElement("newsletter-sync-btn");
    if (!button) {
        return;
    }
    button.disabled = true;
    const originalText = button.textContent;
    button.textContent = "Syncing...";
    try {
        const response = await fetch("/api/newsletters/sync", { method: "POST" });
        const data = await readJson(response);
        if (response.ok) {
            toast(data.message || "Newsletter sync started.");
            updateNewsletterStatusUI({ running: true, last_status: "running" });
        }
        else {
            toast(data.detail || "Could not start newsletter sync.", false);
        }
    }
    catch {
        toast("Network error starting newsletter sync.", false);
    }
    finally {
        button.disabled = false;
        button.textContent = originalText;
        window.setTimeout(() => {
            void fetchNewsletterStatus();
        }, 2000);
    }
}
function updatePipelineStatusUI(state) {
    const dot = getElement("pipeline-status-dot");
    const text = getElement("pipeline-status-text");
    if (!dot || !text) {
        return;
    }
    dot.className = "refresh-status-dot";
    switch (state.last_status) {
        case "success":
            dot.classList.add("success");
            if (typeof state.minutes_since_last_success === "number") {
                const minutes = state.minutes_since_last_success;
                text.textContent = minutes === 0 ? "Now" : `${minutes}m ago`;
            }
            else {
                text.textContent = "Done";
            }
            break;
        case "error":
            dot.classList.add("error");
            text.textContent = "Failed";
            break;
        case "running":
            dot.classList.add("running");
            text.textContent = "Running";
            break;
        case "never":
        default:
            text.textContent = "Ready";
            break;
    }
}
function updateWordrankStatusUI(state) {
    const dot = getElement("wordrank-status-dot");
    const text = getElement("wordrank-status-text");
    if (!dot || !text) {
        return;
    }
    dot.className = "refresh-status-dot";
    if (state.running) {
        dot.classList.add("running");
        text.textContent = "Running";
        return;
    }
    switch (state.last_status) {
        case "success":
            dot.classList.add("success");
            if (typeof state.minutes_since_last_success === "number") {
                const minutes = state.minutes_since_last_success;
                text.textContent = minutes === 0 ? "Now" : `${minutes}m ago`;
            }
            else {
                text.textContent = "Done";
            }
            break;
        case "error":
            dot.classList.add("error");
            text.textContent = "Failed";
            break;
        default:
            text.textContent = "Ready";
            break;
    }
}
async function fetchWordrankStatus() {
    try {
        const response = await fetch("/api/wordrank/status");
        if (!response.ok) {
            return;
        }
        const data = await readJson(response);
        updateWordrankStatusUI({
            running: false,
            last_status: data.last_status || "never",
        });
    }
    catch {
        // best-effort only
    }
}
async function wordrankNow() {
    const button = getElement("wordrank-now-btn");
    if (!button) {
        return;
    }
    button.disabled = true;
    const originalText = button.textContent;
    button.textContent = "Running...";
    updateWordrankStatusUI({ running: true, last_status: "running" });
    try {
        const response = await fetch("/api/wordrank", { method: "POST" });
        const data = await readJson(response);
        if (response.ok && data.status === "success") {
            toast(data.message || "WordRank completed.");
            updateWordrankStatusUI({ running: false, last_status: "success" });
        }
        else {
            toast(data.message || data.detail || "WordRank failed.", false);
            updateWordrankStatusUI({ running: false, last_status: "error" });
        }
    }
    catch {
        toast("Network error running WordRank.", false);
        updateWordrankStatusUI({ running: false, last_status: "error" });
    }
    finally {
        button.disabled = false;
        button.textContent = originalText;
    }
}
(function initPipelineControls() {
    const refreshInput = getElement("pipeline_refresh_minutes");
    if (refreshInput) {
        refreshInput.addEventListener("input", updatePipelineRefreshDial);
        updatePipelineRefreshDial();
    }
    if (getElement("wordrank-status-dot")) {
        void fetchWordrankStatus();
    }
})();
window.setTheme = setTheme;
window.saveSettings = saveSettings;
window.refreshNow = refreshNow;
window.newsletterSyncNow = newsletterSyncNow;
window.wordrankNow = wordrankNow;
