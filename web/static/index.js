  // ── Nav drawer (overlay only on mobile; desktop uses sidebar) ─────
  const navOverlay = document.getElementById("nav-overlay");
  const NAV_OPEN_KEY = "nav-open";
  const MOBILE_MAX = 640;
const ARTICLE_CONTEXT_KEYS = ["q", "feed_id", "quality_level", "days", "scope", "themes", "sort"];

  function isMobileViewport() {
    return typeof window !== "undefined" && window.innerWidth <= MOBILE_MAX;
  }

function getCurrentFilters() {
  const params = new URLSearchParams(window.location.search || "");
  return {
    q: params.get("q") || "",
    scope: params.get("scope") || "my",
    feedId: params.get("feed_id") || "",
    qualityLevel: params.get("quality_level") || "",
    days: params.get("days") || "",
    themes: params.get("themes") || "",
    sort: params.get("sort") || "chronological",
  };
}

function _articleContextParams() {
  const params = new URLSearchParams();
  const current = new URLSearchParams(window.location.search || "");
  ARTICLE_CONTEXT_KEYS.forEach((key) => {
    const value = current.get(key);
    if (value) params.set(key, value);
  });
  return params;
}

function _articleUrlForId(entryId) {
  const params = _articleContextParams();
  const qs = params.toString();
  return "/article/" + encodeURIComponent(entryId) + (qs ? "?" + qs : "");
}

function _withArticleContext(href) {
  if (!href) return href;
  try {
    const url = new URL(href, window.location.origin);
    if (url.origin !== window.location.origin || !url.pathname.startsWith("/article/")) {
      return href;
    }
    const params = _articleContextParams();
    params.forEach((value, key) => {
      if (!url.searchParams.has(key)) {
        url.searchParams.set(key, value);
      }
    });
    const qs = url.searchParams.toString();
    return url.pathname + (qs ? "?" + qs : "");
  } catch (_) {
    return href;
  }
}

  function openNav() {
    if (!navOverlay) return;
    if (!isMobileViewport()) return;
    navOverlay.classList.add("open");
    try { localStorage.setItem(NAV_OPEN_KEY, "1"); } catch (_) {}
  }

  function closeNav() {
    if (!navOverlay) return;
    navOverlay.classList.remove("open");
    try { localStorage.setItem(NAV_OPEN_KEY, "0"); } catch (_) {}
  }

  function toggleNav() {
    if (!navOverlay) return;
    if (!isMobileViewport()) return;
    if (navOverlay.classList.contains("open")) {
      closeNav();
    } else {
      openNav();
    }
  }

  // Restore nav state only on mobile so the menu can stay open while navigating.
  (function restoreNavState() {
    if (!navOverlay) return;
    if (!isMobileViewport()) return;
    try {
      if (localStorage.getItem(NAV_OPEN_KEY) === "1") {
        navOverlay.classList.add("open");
      }
    } catch (_) {}
  })();

  function buildTabletHeaderControls() {
    const headerRight = document.querySelector("header .header-right");
    if (!headerRight || headerRight.querySelector(".header-actions-compact")) return;

    const compact = document.createElement("div");
    compact.className = "header-actions-compact";
    compact.innerHTML = `
      <button
        class="btn icon-btn header-compact-refresh-btn"
        type="button"
        title="Fetch latest from all feeds"
        aria-label="Fetch latest from all feeds"
      >
        &#10227;
      </button>
      <div class="header-compact-more-wrap">
        <button
          class="btn icon-btn header-compact-more-btn"
          type="button"
          title="More actions"
          aria-label="More actions"
          aria-haspopup="true"
          aria-expanded="false"
        >
          &#8942;
        </button>
        <div class="header-compact-menu" hidden>
          <button type="button" data-action="wordrank">
            <span class="menu-icon">WR</span><span>Run WordRank</span>
          </button>
          <button type="button" data-action="filter">
            <span class="menu-icon">&#128269;</span><span>Toggle filter</span>
          </button>
          <a href="/settings">
            <span class="menu-icon">&#9881;</span><span>Settings</span>
          </a>
        </div>
      </div>
    `;

    headerRight.appendChild(compact);

    const refreshBtn = compact.querySelector(".header-compact-refresh-btn");
    const moreBtn = compact.querySelector(".header-compact-more-btn");
    const menu = compact.querySelector(".header-compact-menu");

    function closeMenu() {
      menu.hidden = true;
      menu.classList.remove("open");
      moreBtn.setAttribute("aria-expanded", "false");
    }

    function toggleMenu() {
      const open = menu.hidden;
      menu.hidden = !open;
      menu.classList.toggle("open", open);
      moreBtn.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) {
        const first = menu.querySelector("button, a");
        if (first && typeof first.focus === "function") first.focus();
      }
    }

    refreshBtn.addEventListener("click", (e) => {
      e.preventDefault();
      closeMenu();
      headerRefreshNow();
    });

    moreBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleMenu();
    });

    menu.querySelectorAll("[data-action]").forEach((item) => {
      item.addEventListener("click", (e) => {
        e.preventDefault();
        closeMenu();
        switch (item.dataset.action) {
          case "wordrank":
            headerWordrankNow();
            break;
          case "filter":
            headerToggleFilter();
            break;
          default:
            break;
        }
      });
    });

    document.addEventListener("click", (e) => {
      if (!compact.contains(e.target)) {
        closeMenu();
      }
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        closeMenu();
      }
    });
  }
  buildTabletHeaderControls();

  function toggleNavFeeds() {
    const btn = document.getElementById("nav-feeds-toggle");
    const list = document.getElementById("nav-feeds-list");
    btn.classList.toggle("open");
    list.classList.toggle("open");
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && navOverlay && navOverlay.classList.contains("open")) {
      closeNav();
    }
  });

  // ── Header quick-action status lights ─────────────────────────────
  function _headerFeedName(feed) {
    if (!feed) return "";
    return feed.title || feed.url || "";
  }

  function _headerRefreshRunningLabel(state) {
    const total = typeof state.total_feeds === "number" ? state.total_feeds : 0;
    const completed = typeof state.completed_feeds === "number" ? state.completed_feeds : 0;
    const current = _headerFeedName(state.current_feed);
    if (total > 0 && current) {
      return `${completed}/${total} • ${current}`;
    }
    if (total > 0) {
      return `${completed}/${total} feeds`;
    }
    return state.stage_label || "Running";
  }

  function _updateHeaderDot(id, state, opts = {}) {
    const dot = document.getElementById(id);
    if (!dot) return;
    dot.className = "refresh-status-dot";
    if (state.running) {
      dot.classList.add("running");
      if (opts.textId) {
        const textEl = document.getElementById(opts.textId);
        if (textEl) {
          textEl.textContent = opts.kind === "refresh"
            ? _headerRefreshRunningLabel(state)
            : "Running";
        }
      }
      return;
    }
    const last = state.last_status;
    switch (last) {
      case "success":
        dot.classList.add("success");
        break;
      case "error":
        dot.classList.add("error");
        break;
      default:
        // leave as neutral
        break;
    }
    if (opts.textId) {
      const textEl = document.getElementById(opts.textId);
      if (textEl) {
        let label = "Ready";
        const mins = typeof state.minutes_since_last_success === "number"
          ? state.minutes_since_last_success
          : null;
        if (opts.kind === "refresh") {
          if (last === "success") {
            if (mins !== null) {
              label = mins === 0 ? "Now" : `${mins}m ago`;
            } else {
              label = "Done";
            }
          } else if (last === "error") {
            label = "Failed";
          }
        } else if (opts.kind === "wordrank") {
          if (last === "success") {
            if (mins !== null) {
              label = mins === 0 ? "Now" : `${mins}m ago`;
            } else {
              label = "Done";
            }
          } else if (last === "error") {
            label = "Failed";
          } else if (!last || last === "idle" || last === "never") {
            label = "Ready";
          }
        }
        textEl.textContent = label;
      }
    }
  }

  async function _fetchHeaderRefreshStatus() {
    const dotId = "header-refresh-status-dot";
    if (!document.getElementById(dotId)) return;
    try {
      const res = await fetch("/api/refresh/status");
      if (!res.ok) return;
      const data = await res.json().catch(() => ({}));
      _updateHeaderDot(dotId, {
        running: !!data.running,
        last_status: data.last_status || "never",
        minutes_since_last_success: typeof data.minutes_since_last_success === "number"
          ? data.minutes_since_last_success
          : null,
        total_feeds: typeof data.total_feeds === "number" ? data.total_feeds : 0,
        completed_feeds: typeof data.completed_feeds === "number" ? data.completed_feeds : 0,
        current_feed: data.current_feed || null,
        stage_label: data.stage_label || "",
      }, { kind: "refresh", textId: "header-refresh-status-text" });
    } catch (_) {
      // best-effort only
    }
  }

  let _headerWordrankState = { running: false, last_status: "idle" };
  function _renderHeaderWordrankState() {
    _updateHeaderDot(
      "header-wordrank-status-dot",
      _headerWordrankState,
      { kind: "wordrank", textId: "header-wordrank-status-text" },
    );
  }

  async function headerRefreshNow() {
    const btn = document.getElementById("header-refresh-btn");
    if (!btn) return;
    if (btn.disabled) return;
    btn.disabled = true;
    try {
      const res = await fetch("/api/refresh", { method: "POST" });
      if (res.ok) {
        const data = await res.json().catch(() => ({}));
        toast(data.message || "Refresh started.");
        _updateHeaderDot(
          "header-refresh-status-dot",
          { running: true, last_status: "running" },
          { kind: "refresh", textId: "header-refresh-status-text" },
        );
        setTimeout(_fetchHeaderRefreshStatus, 2000);
      } else {
        const data = await res.json().catch(() => ({}));
        toast(data.detail || "Could not start refresh.", false);
      }
    } catch (_) {
      toast("Network error starting refresh.", false);
    } finally {
      btn.disabled = false;
    }
  }
  window.headerRefreshNow = headerRefreshNow;

  async function _fetchHeaderWordrankStatus() {
    const dotId = "header-wordrank-status-dot";
    if (!document.getElementById(dotId)) return;
    try {
      const res = await fetch("/api/wordrank/status");
      if (!res.ok) return;
      const data = await res.json().catch(() => ({}));
      _headerWordrankState = {
        running: false,
        last_status: data.last_status || "never",
        minutes_since_last_success: typeof data.minutes_since_last_success === "number"
          ? data.minutes_since_last_success
          : null,
      };
      _renderHeaderWordrankState();
    } catch (_) {
      // best-effort only
    }
  }

  async function headerWordrankNow() {
    const btn = document.getElementById("header-wordrank-btn");
    if (!btn) return;
    if (btn.disabled) return;
    btn.disabled = true;
    _headerWordrankState = { running: true, last_status: "running" };
    _renderHeaderWordrankState();
    try {
      const res = await fetch("/api/wordrank", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.status === "success") {
        toast(data.message || "WordRank completed.");
        _headerWordrankState = { running: false, last_status: "success" };
      } else {
        toast(data.message || data.detail || "WordRank failed.", false);
        _headerWordrankState = { running: false, last_status: "error" };
      }
    } catch (_) {
      toast("Network error running WordRank.", false);
      _headerWordrankState = { running: false, last_status: "error" };
    } finally {
      btn.disabled = false;
      _renderHeaderWordrankState();
    }
  }
  window.headerWordrankNow = headerWordrankNow;

  (function initHeaderStatus() {
    if (document.getElementById("header-refresh-status-dot")) {
      _fetchHeaderRefreshStatus();
      setInterval(_fetchHeaderRefreshStatus, 2000);
    }
    if (document.getElementById("header-wordrank-status-dot")) {
      _fetchHeaderWordrankStatus();
    }
  })();

  // ── Quality filter for feed items ─────────────────────────────────
  let _entryFilterEnabled = false;

  function _getFilterAggressiveness() {
    try {
      const raw = localStorage.getItem("filter_aggressiveness");
      const level = parseInt(raw ?? "1", 10);
      if (Number.isNaN(level)) return 1;
      return Math.min(3, Math.max(0, level));
    } catch {
      return 1;
    }
  }

  function headerToggleFilter() {
    const params = new URLSearchParams(window.location.search || "");
    const currentlyOn = params.has("quality_level");
    const nextOn = !currentlyOn;
    if (nextOn) {
      const level = _getFilterAggressiveness();
      params.set("quality_level", String(level));
    } else {
      params.delete("quality_level");
    }
    window.location.search = params.toString();
  }
  window.headerToggleFilter = headerToggleFilter;

  (function initHeaderFilterFromUrl() {
    const params = new URLSearchParams(window.location.search || "");
    const btn = document.getElementById("header-filter-btn");

    const enabled = params.has("quality_level");
    // Keep the main feed filter in sync with the settings-page slider.
    // The server uses `quality_level` from the URL, while the slider only
    // writes to `localStorage.filter_aggressiveness`.
    if (enabled) {
      const desiredLevel = _getFilterAggressiveness();
      const rawCurrent = params.get("quality_level") ?? "";
      const parsedCurrent = parseInt(rawCurrent, 10);
      const currentLevel = Number.isNaN(parsedCurrent) ? 1 : Math.min(3, Math.max(0, parsedCurrent));
      if (String(currentLevel) !== String(desiredLevel)) {
        params.set("quality_level", String(desiredLevel));
        window.location.search = params.toString();
        return;
      }
    }

    _entryFilterEnabled = enabled;
    if (btn) {
      btn.classList.toggle("active", _entryFilterEnabled);
      btn.setAttribute("aria-pressed", _entryFilterEnabled ? "true" : "false");
    }
  })();

  // ── Theme category filter (checkboxes) ─────────────────────────────
  const THEME_LABELS = ["Politics", "Technology", "Business", "Stocks", "Spam", "Science", "World News"];

  function _themePanel() {
    return document.getElementById("theme-filter-panel");
  }

  function _themeBtn() {
    return document.getElementById("theme-filter-btn");
  }

  function _readSelectedThemesFromPanel() {
    const panel = _themePanel();
    if (!panel) return new Set();
    const checked = panel.querySelectorAll(".theme-filter-checkbox:checked");
    return new Set(Array.from(checked).map((cb) => cb.value));
  }

  function _setPanelChecked(themesSet) {
    const panel = _themePanel();
    if (!panel) return;
    const checkboxes = panel.querySelectorAll(".theme-filter-checkbox");
    checkboxes.forEach((cb) => {
      cb.checked = themesSet.has(cb.value);
    });
  }

  function _allThemesSelected() {
    const selected = _readSelectedThemesFromPanel();
    return selected.size === THEME_LABELS.length;
  }

  function toggleThemeFilter() {
    const panel = _themePanel();
    const btn = _themeBtn();
    if (!panel || !btn) return;
    const isHidden = !!panel.hidden;
    panel.hidden = !isHidden;
    btn.setAttribute("aria-expanded", isHidden ? "true" : "false");
  }
  window.toggleThemeFilter = toggleThemeFilter;

  function applyThemeFilter() {
    const panel = _themePanel();
    if (!panel) return;

    const selected = Array.from(_readSelectedThemesFromPanel());
    const params = new URLSearchParams(window.location.search || "");

    if (selected.length === THEME_LABELS.length) {
      params.delete("themes");
    } else {
      // Keep stable ordering for deterministic URLs.
      selected.sort((a, b) => THEME_LABELS.indexOf(a) - THEME_LABELS.indexOf(b));
      params.set("themes", selected.join(","));
    }

    window.location.search = params.toString();
  }
  window.applyThemeFilter = applyThemeFilter;

  function clearThemeFilter() {
    const panel = _themePanel();
    if (!panel) return;
    _setPanelChecked(new Set(THEME_LABELS));
    const params = new URLSearchParams(window.location.search || "");
    params.delete("themes");
    window.location.search = params.toString();
  }
  window.clearThemeFilter = clearThemeFilter;

  (function initThemeFilterFromUrl() {
    const panel = _themePanel();
    const btn = _themeBtn();
    if (!panel || !btn) return;

    const params = new URLSearchParams(window.location.search || "");
    const raw = params.get("themes");

    let themesSet;
    if (raw === null) {
      themesSet = new Set(THEME_LABELS);
    } else {
      const parts = raw.split(",").map((s) => (s || "").trim()).filter(Boolean);
      const allowed = new Set(THEME_LABELS);
      themesSet = new Set(parts.filter((p) => allowed.has(p)));
      // If nothing valid is specified, match nothing (leave unchecked).
    }

    _setPanelChecked(themesSet);
    btn.classList.toggle("active", !_allThemesSelected());
  })();

  (function initSortSelect() {
    const sortSelect = document.getElementById("sort-select");
    if (!sortSelect) return;
    sortSelect.addEventListener("change", function () {
      const value = this.value;
      const params = new URLSearchParams(window.location.search || "");
      if (value === "chronological") {
        params.delete("sort");
      } else {
        params.set("sort", value);
      }
      window.location.search = params.toString();
    });
  })();

  (function initThemeFilterButton() {
    const btn = _themeBtn();
    if (!btn) return;
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      toggleThemeFilter();
    });
  })();

  // Close the panel when clicking outside it.
  (function initThemeFilterOutsideClick() {
    const panel = _themePanel();
    const btn = _themeBtn();
    if (!panel || !btn) return;
    document.addEventListener("click", (e) => {
      const target = e.target;
      if (!target) return;
      const clickedInside = panel.contains(target) || btn.contains(target);
      if (!clickedInside) {
        panel.hidden = true;
        btn.setAttribute("aria-expanded", "false");
      }
    });
  })();

(function initArticleLinkContext() {
  document.querySelectorAll('a[href^="/article/"]').forEach((link) => {
    link.href = _withArticleContext(link.getAttribute("href") || link.href);
  });
})();

(function initArticleVoteOffset() {
  if (!document.body.classList.contains("article-page")) return;
  const header = document.querySelector(".article-header");
  if (!header) return;

  function syncHeaderHeight() {
    const height = Math.ceil(header.getBoundingClientRect().height || 0);
    document.documentElement.style.setProperty("--article-header-height", height + "px");
  }

  syncHeaderHeight();
  window.addEventListener("resize", syncHeaderHeight);
  if (document.fonts && document.fonts.ready && typeof document.fonts.ready.then === "function") {
    document.fonts.ready.then(syncHeaderHeight).catch(() => {});
  }
})();

(function initEntryHoverPreview() {
  const preview = document.getElementById("entry-hover-preview");
  const previewUrl = document.getElementById("entry-hover-preview-url");
  const previewImage = document.getElementById("entry-hover-preview-image");
  const canHover = typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  let activeRow = null;

  if (!preview || !previewUrl || !previewImage) return;

  function normalizePreviewUrl(value) {
    const raw = String(value || "").trim();
    if (!raw) return "";
    try {
      return new URL(raw, window.location.origin).href;
    } catch (_) {
      return raw;
    }
  }

  function positionPreview(clientX, clientY) {
    if (preview.hidden) return;
    const margin = 18;
    const rect = preview.getBoundingClientRect();
    const maxLeft = Math.max(margin, window.innerWidth - rect.width - margin);
    const maxTop = Math.max(margin, window.innerHeight - rect.height - margin);
    preview.style.left = `${Math.max(margin, Math.min(clientX + 20, maxLeft))}px`;
    preview.style.top = `${Math.max(margin, Math.min(clientY + 20, maxTop))}px`;
  }

  function showPreview(row, clientX = null, clientY = null) {
    if (!row) return;
    const url = normalizePreviewUrl(row.dataset.previewUrl || row.getAttribute("href") || "");
    const image = String(row.dataset.previewImage || "").trim();
    if (!url && !image) return;

    activeRow = row;
    previewUrl.textContent = url;

    if (image) {
      previewImage.src = image;
      previewImage.hidden = false;
    } else {
      previewImage.hidden = true;
      previewImage.removeAttribute("src");
    }

    preview.hidden = false;
    preview.classList.add("visible");

    if (typeof clientX === "number" && typeof clientY === "number") {
      positionPreview(clientX, clientY);
      return;
    }

    const rect = row.getBoundingClientRect();
    positionPreview(rect.right, rect.top + 10);
  }

  function hidePreview(row = null) {
    if (row && activeRow && row !== activeRow) return;
    activeRow = null;
    preview.hidden = true;
    preview.classList.remove("visible");
    previewImage.hidden = true;
    previewImage.removeAttribute("src");
  }

  function bindRow(row) {
    if (!row || row.dataset.hoverBound === "1") return;
    row.dataset.hoverBound = "1";

    row.addEventListener("mouseenter", (event) => {
      if (!canHover) return;
      showPreview(row, event.clientX, event.clientY);
    });
    row.addEventListener("mousemove", (event) => {
      if (!canHover || activeRow !== row) return;
      positionPreview(event.clientX, event.clientY);
    });
    row.addEventListener("mouseleave", () => {
      if (!canHover) return;
      hidePreview(row);
    });
    row.addEventListener("focus", () => {
      showPreview(row);
    });
    row.addEventListener("blur", () => {
      hidePreview(row);
    });
  }

  document.querySelectorAll(".entry-row").forEach(bindRow);
  window.bindEntryRowHoverPreview = bindRow;

  document.addEventListener("scroll", () => {
    if (!activeRow || !canHover) return;
    const rect = activeRow.getBoundingClientRect();
    positionPreview(rect.right, rect.top + 10);
  }, { passive: true });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hidePreview();
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

  // ── Navbar "Add Feed" (URL lookup) ──────────────────────────────
  async function handleNavbarAddFeed(scope) {
    const inputId = scope === "sidebar" ? "sidebar-add-feed-input" : "nav-add-feed-input";
    const btnId = scope === "sidebar" ? "sidebar-add-feed-btn" : "nav-add-feed-btn";

    const input = document.getElementById(inputId);
    const btn = document.getElementById(btnId);
    if (!input || !btn) return;

    const raw = String(input.value || "").trim();
    if (!raw) {
      toast("Enter a website or feed URL.", false);
      return;
    }

    if (btn.disabled) return;
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Adding...";

    try {
      // Use the same detection logic as the old feeds page, then add every detected feed.
      const detectRes = await fetch("/api/discover/detect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: raw }),
      });

      const detectData = await detectRes.json().catch(() => ({}));
      if (!detectRes.ok) {
        toast(detectData.detail || "Could not detect feeds.", false);
        return;
      }

      const feeds = Array.isArray(detectData.feeds) ? detectData.feeds : [];
      if (feeds.length === 0) {
        toast("No feeds found at that URL.", false);
        return;
      }

      let addedAny = false;
      for (const f of feeds) {
        const feedUrl = f && f.url ? String(f.url).trim() : "";
        if (!feedUrl) continue;
        const title = f && f.name ? String(f.name).trim() : null;

        const addRes = await fetch("/api/feeds", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: feedUrl, title }),
        });

        if (addRes.ok || addRes.status === 409) {
          addedAny = true;
        }
      }

      toast(addedAny ? "Feed(s) added." : "No new feeds added.", addedAny);
      if (addedAny) {
        // Reload so Discover catalogue/removal buttons reflect updated user_catalog.
        window.location.reload();
      }
    } catch (_) {
      toast("Network error adding feed.", false);
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
      input.value = "";
    }
  }
  window.handleNavbarAddFeed = handleNavbarAddFeed;

  // ── Read state ──────────────────────────────────────────────────
  function markRead(entryId, eventOrEl) {
    const target = eventOrEl && eventOrEl.currentTarget ? eventOrEl.currentTarget : eventOrEl;
    const row = target && typeof target.closest === "function"
      ? target.closest(".entry-row")
      : null;
    if (row && !row.classList.contains("read")) {
      row.classList.add("read");
    }
    fetch(`/api/entries/${entryId}/read`, { method: "POST", keepalive: true }).catch(() => {});
  }
  window.markRead = markRead;

  // ── Delete feed from sidebar/nav ────────────────────────────────────
  async function deleteFeed(feedId, btn) {
    if (btn) btn.disabled = true;
    try {
      const res = await fetch(`/api/feeds/${feedId}`, { method: "DELETE" });
      if (res.ok) {
        // Remove this feed from both sidebar and overlay nav lists
        document.querySelectorAll(`[data-feed-id="${feedId}"]`).forEach((row) => row.remove());
        // If we were viewing this feed, send user back to main list
        const params = new URLSearchParams(window.location.search);
        if (params.get("feed_id") === String(feedId)) {
          window.location.href = "/";
        }
        toast("Feed removed.");
      } else {
        toast("Could not remove feed.", false);
      }
    } catch (_) {
      toast("Network error removing feed.", false);
    } finally {
      if (btn) btn.disabled = false;
    }
  }
  window.deleteFeed = deleteFeed;

  // ── Helpers ──────────────────────────────────────────────────────
  function escHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

function _toDate(value) {
  if (!value) return null;
  const dt = new Date(value);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

function _formatDate(value, options) {
  const dt = _toDate(value);
  if (!dt) return "";
  try {
    return new Intl.DateTimeFormat(undefined, options).format(dt);
  } catch (_) {
    return dt.toLocaleString();
  }
}

function formatLocalDate(value) {
  return _formatDate(value, {
    year: "2-digit",
    month: "numeric",
    day: "numeric",
  });
}

function formatLocalDateTime(value) {
  return _formatDate(value, {
    year: "2-digit",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

function applyLocalPublishedDates(root = document) {
  if (!root || typeof root.querySelectorAll !== "function") return;
  root.querySelectorAll("[data-published]").forEach((el) => {
    const published = el.getAttribute("data-published") || el.getAttribute("datetime") || "";
    if (!published) return;
    const fmt = (el.getAttribute("data-published-format") || "date").toLowerCase();
    const text = fmt === "datetime" ? formatLocalDateTime(published) : formatLocalDate(published);
    if (text) {
      el.textContent = text;
    }
  });
}

applyLocalPublishedDates();

function _publishedDateText(published) {
  return formatLocalDate(published);
}

  function stripTags(s) {
    const tmp = document.createElement("div");
    tmp.innerHTML = s;
    return tmp.textContent || tmp.innerText || "";
  }

  // ── Lazy loading for main article list ────────────────────────────
  (function initLazyLoading() {
    const entriesList = document.getElementById("entries-list");
    if (!entriesList) return;

    const topicSections = new Map();

    function normalizeThemeLabel(value) {
      const label = String(value || "").trim();
      return label || "World News";
    }

    function collectTopicSections() {
      topicSections.clear();
      entriesList.querySelectorAll(".topic-section").forEach((section) => {
        const label = section.dataset.topicLabel || "";
        const rows = section.querySelector(".topic-section-rows");
        if (label && rows) {
          topicSections.set(label, rows);
        }
      });
    }

    function ensureTopicSection(label) {
      const normalized = normalizeThemeLabel(label);
      if (topicSections.has(normalized)) {
        return topicSections.get(normalized);
      }

      const section = document.createElement("section");
      section.className = "topic-section";
      section.dataset.topicLabel = normalized;

      const header = document.createElement("div");
      header.className = "topic-section-header";
      const title = document.createElement("h2");
      title.className = "topic-section-title";
      title.textContent = normalized;
      header.appendChild(title);

      const rows = document.createElement("div");
      rows.className = "topic-section-rows";

      section.appendChild(header);
      section.appendChild(rows);
      entriesList.appendChild(section);
      topicSections.set(normalized, rows);
      return rows;
    }

    function buildEntryRow(e) {
      const row = document.createElement("a");
      const href = e.link || _articleUrlForId(e.id);
      const topicLabel = normalizeThemeLabel(e.theme_label);
      const previewImage = e.og_image_url || e.thumbnail_url || "";

      row.href = href;
      row.className = "entry-row" + (e.read ? " read" : "");
      row.dataset.entryId = String(e.id);
      row.dataset.topicLabel = topicLabel;
      row.dataset.previewUrl = href;
      row.dataset.previewImage = previewImage;
      row.title = href;
      row.addEventListener("click", (event) => {
        markRead(e.id, event);
      });

      const feedInfo = (window.FEED_MAP && window.FEED_MAP[e.feed_id]) || {};
      const domain = e.feed_domain || feedInfo.domain;

      const logo = document.createElement("span");
      logo.className = "entry-row-logo";
      if (domain) {
        const favicon = document.createElement("img");
        favicon.className = "entry-favicon";
        favicon.src = "https://www.google.com/s2/favicons?domain=" +
          encodeURIComponent(domain) + "&sz=32";
        favicon.width = 16;
        favicon.height = 16;
        favicon.loading = "lazy";
        favicon.alt = "";
        logo.appendChild(favicon);
      } else {
        const placeholder = document.createElement("span");
        placeholder.className = "entry-favicon entry-favicon-placeholder";
        logo.appendChild(placeholder);
      }

      const main = document.createElement("span");
      main.className = "entry-row-main";

      const headline = document.createElement("span");
      headline.className = "entry-row-headline";
      headline.textContent = e.title || "(no title)";
      main.appendChild(headline);

      const summaryText = stripTags(e.summary || "").trim();
      if (summaryText) {
        const divider = document.createElement("span");
        divider.className = "entry-row-divider";
        divider.textContent = ":";
        const description = document.createElement("span");
        description.className = "entry-row-description";
        description.textContent = summaryText;
        main.appendChild(divider);
        main.appendChild(description);
      }

      const source = document.createElement("span");
      source.className = "entry-row-source";
      source.textContent = e.feed_title || "Unknown";

      const date = document.createElement("time");
      date.className = "entry-row-date";
      date.textContent = _publishedDateText(e.published);
      if (e.published) {
        date.setAttribute("data-published", e.published);
        date.setAttribute("data-published-format", "date");
        date.dateTime = e.published;
      }

      row.appendChild(logo);
      row.appendChild(main);
      row.appendChild(source);
      row.appendChild(date);

      if (typeof window.bindEntryRowHoverPreview === "function") {
        window.bindEntryRowHoverPreview(row);
      }

      return row;
    }

    collectTopicSections();

    let isLoadingMore = false;
    let allLoaded = false;

    const INITIAL_ROWS = entriesList.querySelectorAll(".entry-row").length;
    const PAGE_SIZE = INITIAL_ROWS || 40;

    async function loadMoreEntries() {
      if (isLoadingMore || allLoaded) return;
      const existing = entriesList.querySelectorAll(".entry-row").length;
      if (!existing && INITIAL_ROWS === 0) {
        allLoaded = true;
        return;
      }

      isLoadingMore = true;
      const { q, scope, feedId, qualityLevel, days, themes, sort } = getCurrentFilters();
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(existing));
      if (q) params.set("q", q);
      params.set("scope", scope);
      if (scope === "my" && feedId) params.set("feed_id", feedId);
      if (qualityLevel) params.set("quality_level", qualityLevel);
      if (days) params.set("days", days);
      if (themes) params.set("themes", themes);
      if (sort && sort !== "chronological") params.set("sort", sort);

      try {
        const res = await fetch("/api/entries?" + params.toString());
        if (!res.ok) throw new Error("Bad response");
        const data = await res.json();
        if (!Array.isArray(data) || data.length === 0) {
          allLoaded = true;
          return;
        }
        appendEntries(data);
        if (data.length < PAGE_SIZE) {
          allLoaded = true;
        }
      } catch (_) {
        // Silent failure – lazy loading is best-effort only.
      } finally {
        isLoadingMore = false;
      }
    }

    function appendEntries(entries) {
      const emptyState = entriesList.querySelector(".empty-state");
      if (emptyState) emptyState.remove();
      for (const e of entries) {
        const rows = ensureTopicSection(e.theme_label);
        rows.appendChild(buildEntryRow(e));
      }
      applyLocalPublishedDates(entriesList);
    }

    function maybeLoadMore() {
      if (isLoadingMore || allLoaded) return;
      const scrollY = window.scrollY || window.pageYOffset || 0;
      const viewport = window.innerHeight || document.documentElement.clientHeight || 0;
      const docHeight = document.documentElement.scrollHeight || document.body.scrollHeight || 0;
      // Start loading a bit before the user hits the end.
      if (scrollY + viewport + 400 >= docHeight) {
        loadMoreEntries();
      }
    }

    window.addEventListener("scroll", maybeLoadMore, { passive: true });
    window.addEventListener("resize", maybeLoadMore);

    // In case the initial page is short, attempt an eager load.
    setTimeout(maybeLoadMore, 300);
  })();

  // ── Advanced search dropdown ────────────────────────────────────
  (function initAdvancedDropdown() {
    const advToggle = document.getElementById("advanced-toggle");
    const advDropdown = document.getElementById("advanced-dropdown");
    if (!advToggle || !advDropdown) return;
    advToggle.addEventListener("click", (e) => {
      e.preventDefault();
      const isOpen = !advDropdown.hidden;
      advDropdown.hidden = isOpen;
      advToggle.setAttribute("aria-expanded", isOpen ? "false" : "true");
    });
  })();

  // ── Live search ──────────────────────────────────────────────────
  const searchInput    = document.getElementById("search-input");
  const searchDropdown = document.getElementById("search-dropdown");
  const searchForm     = document.getElementById("search-form");
  const searchQueryBase = document.getElementById("search-query-base");
  const searchTermRemove = document.getElementById("search-term-remove");
  let _searchTimer     = null;
  let _lastQuery       = "";

  function _searchBaseQuery() {
    return searchQueryBase ? searchQueryBase.value.trim() : "";
  }

  function _searchDraftQuery() {
    return searchInput ? searchInput.value.trim() : "";
  }

  function _composeSearchQuery() {
    const parts = [];
    const base = _searchBaseQuery();
    const draft = _searchDraftQuery();
    if (base) parts.push(base);
    if (draft) parts.push(draft);
    return parts.join(" ").trim();
  }

  function _safeSessionGet(key) {
    try { return sessionStorage.getItem(key) || ""; } catch (_) { return ""; }
  }

  function _safeSessionSet(key, value) {
    try { sessionStorage.setItem(key, value); } catch (_) {}
  }

  function _rememberFeedUrl() {
    if (window.location.pathname !== "/") return;
    const params = new URLSearchParams(window.location.search || "");
    if (params.has("q")) return;
    _safeSessionSet("myrssfeed_last_feed_url", window.location.href);
  }

  function _returnToFeed() {
    const fallback = _safeSessionGet("myrssfeed_last_feed_url") || "/";
    let referrer = "";
    try { referrer = document.referrer || ""; } catch (_) {}
    if (referrer) {
      try {
        const refUrl = new URL(referrer, window.location.href);
        if (refUrl.origin === window.location.origin) {
          window.history.back();
          return;
        }
      } catch (_) {}
    }
    window.location.replace(fallback);
  }

  function _closeDropdown(clear = false) {
    searchDropdown.style.display = "none";
    if (clear) {
      searchDropdown.innerHTML = "";
      _lastQuery = "";
    }
  }

  if (searchInput && searchDropdown) {
    _rememberFeedUrl();

    if (searchForm) {
      searchForm.addEventListener("submit", () => {
        _rememberFeedUrl();
        if (searchQueryBase) {
          searchQueryBase.value = _composeSearchQuery();
        }
      });
    }

    if (searchTermRemove) {
      const removeSearchTerm = (e) => {
        if (e) e.preventDefault();
        const params = new URLSearchParams(window.location.search || "");
        if (!params.has("q")) return;
        params.delete("q");
        if (searchQueryBase) {
          searchQueryBase.value = "";
        }
        searchInput.value = "";
        _closeDropdown(true);
        const nextUrl = params.toString() ? "?" + params.toString() : "";
        window.location.replace(nextUrl || window.location.pathname);
      };

      searchTermRemove.addEventListener("click", removeSearchTerm);
      searchTermRemove.addEventListener("keydown", (e) => {
        if (e.key === "Backspace" || e.key === "Delete") {
          removeSearchTerm(e);
        }
      });
    }

    const searchClear = document.getElementById("search-clear");
    if (searchClear) {
      searchClear.addEventListener("click", (e) => {
        const params = new URLSearchParams(window.location.search || "");
        if (!params.has("q")) {
          return;
        }
        e.preventDefault();
        _closeDropdown(true);
        _returnToFeed();
      });
    }

    searchInput.addEventListener("input", () => {
      clearTimeout(_searchTimer);
      const draft = _searchDraftQuery();
      if (!draft) {
        _closeDropdown(true);
        return;
      }
      _searchTimer = setTimeout(() => _doLiveSearch(), 220);
    });

    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Backspace" && !searchInput.value && _searchBaseQuery()) {
        e.preventDefault();
        if (searchTermRemove) {
          searchTermRemove.click();
        }
        return;
      }
      if (e.key === "Escape") { _closeDropdown(); searchInput.blur(); }
    });

    searchInput.addEventListener("focus", () => {
      if (_lastQuery && searchDropdown.children.length) {
        searchDropdown.style.display = "";
      }
    });

    document.addEventListener("click", (e) => {
      if (!searchInput.contains(e.target) && !searchDropdown.contains(e.target)) {
        _closeDropdown();
      }
      const advToggle = document.getElementById("advanced-toggle");
      const advDropdown = document.getElementById("advanced-dropdown");
      if (advToggle && advDropdown && !advToggle.contains(e.target) && !advDropdown.contains(e.target)) {
        advDropdown.hidden = true;
        advToggle.setAttribute("aria-expanded", "false");
      }
    });

    async function _doLiveSearch() {
      const q = _composeSearchQuery();
      if (!q) {
        _closeDropdown(true);
        return;
      }
      _lastQuery = q;
      try {
        const params = getCurrentFilters();
        const searchParams = new URLSearchParams();
        searchParams.set("q", q);
        searchParams.set("limit", "8");
        searchParams.set("scope", params.scope);
        if (params.scope === "my" && params.feedId) searchParams.set("feed_id", params.feedId);
        if (params.qualityLevel) searchParams.set("quality_level", params.qualityLevel);
        if (params.days) searchParams.set("days", params.days);
        const res = await fetch("/api/search?" + searchParams.toString());
        if (!res.ok) return;
        if (q !== _composeSearchQuery()) return;
        const data = await res.json();
        _renderDropdown(q, data);
      } catch (_) {}
    }

    function _renderDropdown(q, { suggestions, entries }) {
      if (!suggestions.length && !entries.length) {
        searchDropdown.innerHTML = '<div class="search-no-results">No results for "' + escHtml(q) + '"</div>';
        searchDropdown.style.display = "";
        return;
      }

      const frag = document.createDocumentFragment();

      if (suggestions.length) {
        const row = document.createElement("div");
        row.className = "search-suggestions";
        row.innerHTML = '<span class="search-suggest-label">Complete:</span>';
        suggestions.forEach((s) => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "search-chip";
          btn.textContent = s;
          btn.addEventListener("click", () => _applySuggestion(s));
          row.appendChild(btn);
        });
        frag.appendChild(row);
      }

      entries.forEach((e) => {
        const a = document.createElement("a");
        a.className = "search-result-item";
        a.href = e.link || _articleUrlForId(e.id);
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        const date = _publishedDateText(e.published);
        a.innerHTML =
          '<div class="search-result-title">' + escHtml(e.title || "(no title)") + '</div>' +
          '<div class="search-result-meta">' +
            (e.feed_title ? '<span class="tag" style="font-size:0.65rem;padding:1px 6px;">' + escHtml(e.feed_title) + '</span>' : '') +
            (date ? '<span>' + date + '</span>' : '') +
          '</div>';
        frag.appendChild(a);
      });

      searchDropdown.innerHTML = "";
      searchDropdown.appendChild(frag);
      searchDropdown.style.display = "";
    }

    function _applySuggestion(word) {
      const val   = searchInput.value;
      const parts = val.split(" ");
      parts[parts.length - 1] = word;
      searchInput.value = parts.join(" ") + " ";
      searchInput.focus();
      clearTimeout(_searchTimer);
      _doLiveSearch();
    }
  }
