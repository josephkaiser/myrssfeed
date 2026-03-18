  // ── Theme toggle ────────────────────────────────────────────────
  function applyTheme(t) {
    const el = document.documentElement;
    if (t === "light")       el.setAttribute("data-theme", "light");
    else if (t === "dark")   el.setAttribute("data-theme", "dark");
    else                     el.removeAttribute("data-theme");
  }

  function refreshToggleUI(t) {
    document.querySelectorAll("#theme-toggle button").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.themeVal === t);
    });
  }

  function setTheme(t) {
    localStorage.setItem("theme", t);
    applyTheme(t);
    refreshToggleUI(t);
  }

  // Initialise toggle to match current localStorage value
  (function() {
    const t = localStorage.getItem("theme") || "system";
    refreshToggleUI(t);
  })();

  // ── Quality filter aggressiveness slider ─────────────────────────
  function getFilterAggressiveness() {
    const raw = localStorage.getItem("filter_aggressiveness");
    const level = parseInt(raw ?? "1", 10);
    if (Number.isNaN(level)) return 1;
    return Math.min(3, Math.max(0, level));
  }

  function describeAggressiveness(level) {
    switch (level) {
      case 0: return "Very gentle";
      case 1: return "Balanced";
      case 2: return "Firm";
      case 3: return "Aggressive";
      default: return "Balanced";
    }
  }

  (function initFilterAggressiveness() {
    const slider = document.getElementById("filter_aggressiveness");
    const label = document.getElementById("filter_aggressiveness_label");
    if (!slider || !label) return;

    const level = getFilterAggressiveness();
    slider.value = String(level);
    label.textContent = describeAggressiveness(level);

    slider.addEventListener("input", () => {
      const val = parseInt(slider.value, 10);
      const level = Number.isNaN(val) ? 1 : Math.min(3, Math.max(0, val));
      localStorage.setItem("filter_aggressiveness", String(level));
      label.textContent = describeAggressiveness(level);
    });
  })();

  // ── Toast ───────────────────────────────────────────────────────
  function toast(msg, ok = true) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.style.borderColor = ok ? "var(--accent)" : "var(--danger)";
    el.classList.add("show");
    setTimeout(() => el.classList.remove("show"), 2800);
  }

  // ── Save settings ───────────────────────────────────────────────
  function getPipelineRefreshMinutes() {
    const input = document.getElementById("pipeline_refresh_minutes");
    const raw = input ? parseInt(input.value, 10) : 15;
    if (isNaN(raw)) return 15;
    return Math.min(240, Math.max(5, raw));
  }

  function describePipelineRefreshMinutes(minutes) {
    const value = Math.min(240, Math.max(5, minutes));
    return `${value} min`;
  }

  function updatePipelineRefreshDial() {
    const input = document.getElementById("pipeline_refresh_minutes");
    const label = document.getElementById("pipeline_refresh_minutes_value");
    if (!input || !label) return;
    const minutes = getPipelineRefreshMinutes();
    input.value = String(minutes);
    label.textContent = describePipelineRefreshMinutes(minutes);
  }

  async function saveSettings() {
    const retentionInput = document.getElementById("retention_days");
    const days = parseInt(retentionInput.value, 10);

    if (isNaN(days) || days < 0 || days > 3650) {
      toast("Retention must be 0–3650 days.", false);
      retentionInput.focus();
      return;
    }

    const maxEntriesInput = document.getElementById("max_entries");
    const maxEntriesVal = parseInt(maxEntriesInput.value, 10);
    if (isNaN(maxEntriesVal) || maxEntriesVal < 50 || maxEntriesVal > 20000) {
      toast("Maximum articles must be between 50 and 20000.", false);
      maxEntriesInput.focus();
      return;
    }

    const newsletterEnabledSelect = document.getElementById("newsletter_enabled");
    const newsletterHostInput = document.getElementById("newsletter_imap_host");
    const newsletterPortInput = document.getElementById("newsletter_imap_port");
    const newsletterUserInput = document.getElementById("newsletter_imap_username");
    const newsletterPassInput = document.getElementById("newsletter_imap_password");
    const newsletterFolderInput = document.getElementById("newsletter_imap_folder");
    const newsletterPollInput = document.getElementById("newsletter_poll_minutes");

    const newsletterEnabled = newsletterEnabledSelect ? newsletterEnabledSelect.value : "false";
    const newsletterPortVal = parseInt(newsletterPortInput.value, 10);
    if (isNaN(newsletterPortVal) || newsletterPortVal < 1 || newsletterPortVal > 65535) {
      toast("Newsletter IMAP port must be between 1 and 65535.", false);
      newsletterPortInput.focus();
      return;
    }

    const newsletterPollVal = parseInt(newsletterPollInput.value, 10);
    if (isNaN(newsletterPollVal) || newsletterPollVal < 5 || newsletterPollVal > 1440) {
      toast("Newsletter poll interval must be between 5 and 1440 minutes.", false);
      newsletterPollInput.focus();
      return;
    }

    if (maxEntriesVal > 5000) {
      toast("Large article lists may be slow on lower-end devices. Make sure this machine has enough disk space and a fast drive.", true);
    }

    const theme = localStorage.getItem("theme") || "system";
    const refreshMinutes = getPipelineRefreshMinutes();

    const payload = {
      retention_days: String(days),
      theme,
      max_entries: String(maxEntriesVal),
      pipeline_refresh_minutes: String(refreshMinutes),
      newsletter_enabled: newsletterEnabled,
      newsletter_imap_host: newsletterHostInput.value.trim(),
      newsletter_imap_port: String(newsletterPortVal),
      newsletter_imap_username: newsletterUserInput.value.trim(),
      newsletter_imap_password: newsletterPassInput.value,
      newsletter_imap_folder: newsletterFolderInput.value.trim() || "INBOX",
      newsletter_poll_minutes: String(newsletterPollVal),
    };

    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      const statusEl = document.getElementById("save-status");
      statusEl.classList.add("show");
      setTimeout(() => statusEl.classList.remove("show"), 2500);
      setTimeout(fetchNewsletterStatus, 1000);
    } else {
      const data = await res.json().catch(() => ({}));
      toast(data.detail || "Could not save settings.", false);
    }
  }

  // ── Manual refresh ──────────────────────────────────────────────
  function updateRefreshStatusUI(state) {
    const dot = document.getElementById("refresh-status-dot");
    const text = document.getElementById("refresh-status-text");
    if (!dot || !text) return;

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
          const mins = state.minutes_since_last_success;
          text.textContent = mins === 0 ? "Now" : `${mins}m ago`;
        } else {
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

  async function fetchRefreshStatus() {
    try {
      const res = await fetch("/api/refresh/status");
      if (!res.ok) return;
      const data = await res.json().catch(() => ({}));
      updateRefreshStatusUI({
        running: !!data.running,
        last_status: data.last_status || "never",
        minutes_since_last_success: typeof data.minutes_since_last_success === "number"
          ? data.minutes_since_last_success
          : null,
      });
      updatePipelineStatusUI({
        last_status: data.last_status || "never",
        minutes_since_last_success: typeof data.minutes_since_last_success === "number"
          ? data.minutes_since_last_success
          : null,
      });
    } catch {
      // Silently ignore; status light is best-effort only.
    }
  }

  function updateScrapeStatusUI(state) {
    const dot = document.getElementById("scrape-status-dot");
    const text = document.getElementById("scrape-status-text");
    if (!dot || !text) return;

    dot.className = "refresh-status-dot";

    if (state.running) {
      dot.classList.add("running");
      text.textContent = "Job in progress";
      return;
    }

    switch (state.last_status) {
      case "success":
        dot.classList.add("success");
        if (typeof state.minutes_since_last_success === "number") {
          const mins = state.minutes_since_last_success;
          text.textContent = mins === 0 ? "Just now" : `${mins} min ago`;
        } else {
          text.textContent = "Last job completed";
        }
        break;
      case "error":
        dot.classList.add("error");
        text.textContent = "Last job failed";
        break;
      case "never":
      default:
        text.textContent = "No runs yet";
        break;
    }
  }

  async function fetchScrapeStatus() {
    try {
      const res = await fetch("/api/scrape/status");
      if (!res.ok) return;
      const data = await res.json().catch(() => ({}));
      updateScrapeStatusUI({
        running: !!data.running,
        last_status: data.last_status || "never",
        minutes_since_last_success: typeof data.minutes_since_last_success === "number"
          ? data.minutes_since_last_success
          : null,
      });
    } catch {
      // Best-effort only.
    }
  }

  function updateNewsletterStatusUI(state) {
    const dot = document.getElementById("newsletter-status-dot");
    const text = document.getElementById("newsletter-status-text");
    if (!dot || !text) return;

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
          const mins = state.minutes_since_last_success;
          text.textContent = mins === 0 ? "Just now" : `${mins} min ago`;
        } else {
          text.textContent = "Last sync completed";
        }
        break;
      case "error":
        dot.classList.add("error");
        text.textContent = "Last sync failed";
        if (state.last_error) text.title = state.last_error;
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
      const res = await fetch("/api/newsletters/status");
      if (!res.ok) return;
      const data = await res.json().catch(() => ({}));
      updateNewsletterStatusUI({
        running: !!data.running,
        last_status: data.last_status || "never",
        minutes_since_last_success: typeof data.minutes_since_last_success === "number"
          ? data.minutes_since_last_success
          : null,
        last_error: data.last_error || "",
      });
    } catch {
      // Best-effort only.
    }
  }

  async function refreshNow() {
    const btn = document.getElementById("refresh-now-btn");
    if (!btn) return;
    btn.disabled = true;
    const originalText = btn.textContent;
    btn.textContent = "Refreshing...";
    try {
      const res = await fetch("/api/refresh", { method: "POST" });
      if (res.ok) {
        const data = await res.json().catch(() => ({}));
        toast(data.message || "Refresh started.");
        // Immediately reflect state in the status light
        updateRefreshStatusUI({ running: true, last_status: "running" });
      } else {
        const data = await res.json().catch(() => ({}));
        toast(data.detail || "Could not start refresh.", false);
      }
    } catch (e) {
      toast("Network error starting refresh.", false);
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
      // Re-sync with server state shortly after triggering
      setTimeout(fetchRefreshStatus, 2000);
    }
  }

  // Kick off periodic polling for the status lights on settings page load.
  (function () {
    const hasRefresh = document.getElementById("refresh-status-dot");
    const hasScrape = document.getElementById("scrape-status-dot");
    const hasNewsletter = document.getElementById("newsletter-status-dot");

    if (hasRefresh) {
      fetchRefreshStatus();
      setInterval(fetchRefreshStatus, 8000);
    }
    if (hasScrape) {
      fetchScrapeStatus();
      setInterval(fetchScrapeStatus, 8000);
    }
    if (hasNewsletter) {
      fetchNewsletterStatus();
      setInterval(fetchNewsletterStatus, 8000);
    }
  })();

  // ── Manual scrape/enrichment ────────────────────────────────────
  async function scrapeNow() {
    const btn = document.getElementById("scrape-now-btn");
    if (!btn) return;
    btn.disabled = true;
    const originalText = btn.textContent;
    btn.textContent = "Enriching...";
    try {
      const res = await fetch("/api/scrape", { method: "POST" });
      if (res.ok) {
        const data = await res.json().catch(() => ({}));
        toast(data.message || "Scrape started.");
        updateScrapeStatusUI({ running: true, last_status: "running" });
      } else {
        const data = await res.json().catch(() => ({}));
        toast(data.detail || "Could not start scrape.", false);
      }
    } catch (e) {
      toast("Network error starting scrape.", false);
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
      setTimeout(fetchScrapeStatus, 2000);
    }
  }

  async function newsletterSyncNow() {
    const btn = document.getElementById("newsletter-sync-btn");
    if (!btn) return;
    btn.disabled = true;
    const originalText = btn.textContent;
    btn.textContent = "Syncing...";
    try {
      const res = await fetch("/api/newsletters/sync", { method: "POST" });
      if (res.ok) {
        const data = await res.json().catch(() => ({}));
        toast(data.message || "Newsletter sync started.");
        updateNewsletterStatusUI({ running: true, last_status: "running" });
      } else {
        const data = await res.json().catch(() => ({}));
        toast(data.detail || "Could not start newsletter sync.", false);
      }
    } catch (e) {
      toast("Network error starting newsletter sync.", false);
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
      setTimeout(fetchNewsletterStatus, 2000);
    }
  }

  // ── Pipeline status light (last run) ────────────────────────────
  function updatePipelineStatusUI(state) {
    const dot = document.getElementById("pipeline-status-dot");
    const text = document.getElementById("pipeline-status-text");
    if (!dot || !text) return;

    dot.className = "refresh-status-dot";

    switch (state.last_status) {
      case "success":
        dot.classList.add("success");
        if (typeof state.minutes_since_last_success === "number") {
          const mins = state.minutes_since_last_success;
          text.textContent = mins === 0 ? "Now" : `${mins}m ago`;
        } else {
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

  // ── Manual WordRank recompute ────────────────────────────────────
  function updateWordrankStatusUI(state) {
    const dot = document.getElementById("wordrank-status-dot");
    const text = document.getElementById("wordrank-status-text");
    if (!dot || !text) return;

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
          const mins = state.minutes_since_last_success;
          text.textContent = mins === 0 ? "Now" : `${mins}m ago`;
        } else {
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
      const res = await fetch("/api/wordrank/status");
      if (!res.ok) return;
      const data = await res.json().catch(() => ({}));
      updateWordrankStatusUI({
        running: false,
        last_status: data.last_status || "never",
      });
    } catch {
      // best-effort only
    }
  }

  async function wordrankNow() {
    const btn = document.getElementById("wordrank-now-btn");
    if (!btn) return;
    btn.disabled = true;
    const originalText = btn.textContent;
    btn.textContent = "Running…";
    updateWordrankStatusUI({ running: true, last_status: "running" });
    try {
      const res = await fetch("/api/wordrank", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.status === "success") {
        toast(data.message || "WordRank completed.");
        updateWordrankStatusUI({ running: false, last_status: "success" });
      } else {
        toast(data.message || data.detail || "WordRank failed.", false);
        updateWordrankStatusUI({ running: false, last_status: "error" });
      }
    } catch (e) {
      toast("Network error running WordRank.", false);
      updateWordrankStatusUI({ running: false, last_status: "error" });
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }

  // Initialise dynamic schedule time field on settings page load
  (function () {
    const refreshInput = document.getElementById("pipeline_refresh_minutes");
    if (refreshInput) {
      refreshInput.addEventListener("input", updatePipelineRefreshDial);
      updatePipelineRefreshDial();
    }

    const wordrankDot = document.getElementById("wordrank-status-dot");
    if (wordrankDot) {
      fetchWordrankStatus();
    }
  })();
