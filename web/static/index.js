  // ── Nav drawer (overlay only on mobile; desktop uses sidebar) ─────
  const navOverlay = document.getElementById("nav-overlay");
  const NAV_OPEN_KEY = "nav-open";
  const MOBILE_MAX = 640;
const ARTICLE_CONTEXT_KEYS = ["q", "feed_id", "quality_level", "days", "scope", "themes", "read_status", "sort"];
const ENTRY_VIEW_MODE_KEY = "entry_view_mode";
const FEED_VIEW_STATE_KEY = "myrssfeed_feed_view_state";
let _restoredFeedViewState = null;

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
    readStatus: params.get("read_status") || "",
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

function normalizePreviewUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    return new URL(raw, window.location.origin).href;
  } catch (_) {
    return raw;
  }
}

function normalizeEntryViewMode(value) {
  return String(value || "").trim().toLowerCase() === "expanded" ? "expanded" : "condensed";
}

function getStoredEntryViewMode() {
  try {
    return normalizeEntryViewMode(localStorage.getItem(ENTRY_VIEW_MODE_KEY));
  } catch (_) {
    return "condensed";
  }
}

function applyEntryViewMode(mode) {
  const normalized = normalizeEntryViewMode(mode);
  document.documentElement.setAttribute("data-entry-view", normalized);
  return normalized;
}

function getFeedScrollContainer() {
  const panel = document.getElementById("entries-panel");
  if (!panel || typeof window === "undefined" || typeof window.getComputedStyle !== "function") {
    return window;
  }
  try {
    const style = window.getComputedStyle(panel);
    if (style.overflowY === "auto" || style.overflowY === "scroll") {
      return panel;
    }
  } catch (_) {}
  return window;
}

function getFeedScrollPosition() {
  const scrollContainer = getFeedScrollContainer();
  if (scrollContainer && scrollContainer !== window) {
    return scrollContainer.scrollTop || 0;
  }
  return window.scrollY || window.pageYOffset || 0;
}

function setFeedScrollPosition(value) {
  const nextValue = Math.max(0, Number(value) || 0);
  const scrollContainer = getFeedScrollContainer();
  if (scrollContainer && scrollContainer !== window) {
    scrollContainer.scrollTop = nextValue;
    return;
  }
  if (typeof window.scrollTo === "function") {
    window.scrollTo(0, nextValue);
  }
}

function adjustFeedScroll(delta) {
  if (!delta) return;
  setFeedScrollPosition(getFeedScrollPosition() + delta);
}

function _safeSessionGet(key) {
  try { return sessionStorage.getItem(key) || ""; } catch (_) { return ""; }
}

function _safeSessionSet(key, value) {
  try { sessionStorage.setItem(key, value); } catch (_) {}
}

function _safeSessionRemove(key) {
  try { sessionStorage.removeItem(key); } catch (_) {}
}

function _currentFeedViewUrl() {
  return window.location.pathname + window.location.search;
}

function _readFeedViewState() {
  const raw = _safeSessionGet(FEED_VIEW_STATE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (_) {
    return null;
  }
}

function rememberFeedViewState(options = {}) {
  if (window.location.pathname !== "/") return;
  const currentUrl = _currentFeedViewUrl();
  const previous = _readFeedViewState();
  const state = {
    url: currentUrl,
    scrollTop: Math.max(0, Math.round(getFeedScrollPosition())),
    anchorEntryId: options.anchorEntryId
      || (previous && previous.url === currentUrl ? previous.anchorEntryId || "" : ""),
    activeEntryId: options.activeEntryId
      || (previous && previous.url === currentUrl ? previous.activeEntryId || "" : ""),
    savedAt: Date.now(),
  };
  _safeSessionSet(FEED_VIEW_STATE_KEY, JSON.stringify(state));
}

(function initFeedViewStateRestore() {
  if (window.location.pathname !== "/") return;
  if (typeof history !== "undefined" && "scrollRestoration" in history) {
    history.scrollRestoration = "manual";
  }
  const state = _readFeedViewState();
  if (!state || state.url !== _currentFeedViewUrl()) return;
  _restoredFeedViewState = state;
  const scrollTop = typeof state.scrollTop === "number" ? state.scrollTop : 0;
  requestAnimationFrame(() => {
    setFeedScrollPosition(scrollTop);
    requestAnimationFrame(() => {
      _safeSessionRemove(FEED_VIEW_STATE_KEY);
    });
  });
})();

window.addEventListener("pagehide", () => {
  rememberFeedViewState();
});

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
    if (total > 0) {
      return `Sync ${completed}/${total}`;
    }
    return "Syncing";
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
          const current = _headerFeedName(state.current_feed);
          textEl.textContent = opts.kind === "refresh"
            ? _headerRefreshRunningLabel(state)
            : "Running";
          if (current) {
            textEl.title = `Refreshing ${current}`;
          } else {
            textEl.removeAttribute("title");
          }
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
        textEl.removeAttribute("title");
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

  function _readStatusBtn() {
    return document.getElementById("read-status-btn");
  }

  function _normalizeReadStatus(value) {
    const raw = String(value || "").trim().toLowerCase();
    if (raw === "all" || raw === "read" || raw === "unread") return raw;
    return "unread";
  }

  function _showReadEnabled(readStatus) {
    return _normalizeReadStatus(readStatus) !== "unread";
  }

  function _renderReadStatusButton(readStatus) {
    const btn = _readStatusBtn();
    if (!btn) return;
    const showRead = _showReadEnabled(readStatus);
    btn.textContent = showRead ? "All" : "Unread";
    btn.dataset.readStatus = showRead ? "all" : "unread";
    btn.classList.toggle("active", showRead);
    btn.setAttribute("aria-pressed", showRead ? "true" : "false");
    btn.setAttribute(
      "aria-label",
      showRead
        ? "Currently showing all articles. Switch to unread only."
        : "Currently showing unread articles only. Switch to all articles."
    );
    btn.title = showRead ? "Showing all articles" : "Showing unread articles only";
  }

  function cycleReadStatusFilter() {
    const params = new URLSearchParams(window.location.search || "");
    if (_showReadEnabled(params.get("read_status"))) {
      params.delete("read_status");
    } else {
      params.set("read_status", "all");
    }
    window.location.search = params.toString();
  }
  window.cycleReadStatusFilter = cycleReadStatusFilter;

  (function initReadStatusFilter() {
    const btn = _readStatusBtn();
    if (!btn) return;
    const params = new URLSearchParams(window.location.search || "");
    _renderReadStatusButton(params.get("read_status"));
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      cycleReadStatusFilter();
    });
  })();

  function _entryViewModeBtn() {
    return document.getElementById("entry-view-mode-btn");
  }

  function _renderEntryViewModeButton(mode) {
    const btn = _entryViewModeBtn();
    if (!btn) return;
    const normalized = normalizeEntryViewMode(mode);
    const label = normalized === "expanded" ? "Expanded" : "Condensed";
    btn.textContent = label;
    btn.dataset.viewMode = normalized;
    btn.classList.toggle("active", normalized === "expanded");
    btn.setAttribute("aria-pressed", normalized === "expanded" ? "true" : "false");
    btn.setAttribute("aria-label", `Toggle row view. Currently ${label}.`);
    btn.title = `Row view: ${label}`;
  }

  function setEntryViewMode(mode) {
    const normalized = applyEntryViewMode(mode);
    try {
      localStorage.setItem(ENTRY_VIEW_MODE_KEY, normalized);
    } catch (_) {}
    _renderEntryViewModeButton(normalized);
    if (typeof window.__entryRowActivityRefreshViewMode === "function") {
      window.__entryRowActivityRefreshViewMode(normalized);
    }
    return normalized;
  }
  window.setEntryViewMode = setEntryViewMode;

  (function initEntryViewModeToggle() {
    const btn = _entryViewModeBtn();
    const initialMode = applyEntryViewMode(getStoredEntryViewMode());
    _renderEntryViewModeButton(initialMode);
    if (!btn) return;
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      const nextMode = normalizeEntryViewMode(btn.dataset.viewMode) === "expanded"
        ? "condensed"
        : "expanded";
      setEntryViewMode(nextMode);
    });
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

(function initEntryRowActivity() {
  const entriesPanel = document.getElementById("entries-panel");
  const entriesListRoot = document.getElementById("entries-list");
  if (!entriesPanel || !entriesListRoot) return;

  let activeRow = null;
  let inlineExpandedRow = null;
  let lastInputWasKeyboard = false;
  let pendingGUntil = 0;
  let shortcutsHelpTimer = 0;
  let currentViewMode = normalizeEntryViewMode(
    document.documentElement.getAttribute("data-entry-view") || getStoredEntryViewMode()
  );
  const shortcutsHelp = document.getElementById("feed-shortcuts-help");
  const shortcutsHelpClose = document.getElementById("feed-shortcuts-help-close");
  const SHORTCUTS_HELP_SESSION_KEY = "feed_shortcuts_help_seen";
  const coarsePointer = typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(hover: none), (pointer: coarse)").matches;

  function getRows() {
    return Array.from(document.querySelectorAll(".entry-row"));
  }

  function shouldIgnoreRowShortcuts(target) {
    if (!target || typeof target.closest !== "function") {
      return false;
    }
    return !!target.closest("input, textarea, select, [contenteditable], [role='textbox']");
  }

  function showShortcutsHelp(options = {}) {
    if (!shortcutsHelp) return;
    const autoHide = options.autoHide === true;
    const durationMs = typeof options.durationMs === "number" ? options.durationMs : 7000;
    if (shortcutsHelpTimer) {
      clearTimeout(shortcutsHelpTimer);
      shortcutsHelpTimer = 0;
    }
    shortcutsHelp.hidden = false;
    requestAnimationFrame(() => {
      shortcutsHelp.classList.add("show");
    });
    if (autoHide) {
      shortcutsHelpTimer = window.setTimeout(() => {
        hideShortcutsHelp();
      }, durationMs);
    }
  }

  function hideShortcutsHelp() {
    if (!shortcutsHelp) return;
    if (shortcutsHelpTimer) {
      clearTimeout(shortcutsHelpTimer);
      shortcutsHelpTimer = 0;
    }
    shortcutsHelp.classList.remove("show");
    window.setTimeout(() => {
      if (!shortcutsHelp.classList.contains("show")) {
        shortcutsHelp.hidden = true;
      }
    }, 180);
  }

  function syncRowPreview(row) {
    if (!row) return;
    const preview = row.querySelector(".entry-row-preview");
    if (!preview) return;
    const previewCopy = preview.querySelector(".entry-row-preview-copy");
    const previewUrl = preview.querySelector(".entry-row-preview-url");
    const previewImage = preview.querySelector(".entry-row-preview-image");
    const copy = String(row.dataset.previewCopy || "").trim();
    const url = normalizePreviewUrl(row.dataset.previewUrl || row.getAttribute("href") || "");
    const image = String(row.dataset.previewImage || "").trim();

    if (previewCopy) {
      previewCopy.textContent = copy;
      previewCopy.hidden = !copy;
    }
    if (previewUrl) {
      previewUrl.textContent = url;
    }
    if (previewImage) {
      if (image) {
        previewImage.src = image;
        previewImage.hidden = false;
      } else {
        previewImage.hidden = true;
        previewImage.removeAttribute("src");
      }
    }
  }

  function rowPreviewIsVisible(row) {
    return rowPreviewVisible(row, row === activeRow);
  }

  function openInlinePreview(row) {
    if (!row) return;
    syncRowPreview(row);
    if (!shouldShowExpandedPreview()) {
      expandInlinePreview(row);
    }
  }

  function focusRow(row) {
    if (!row || typeof row.focus !== "function") return;
    if (document.activeElement === row) return;
    try {
      row.focus({ preventScroll: true });
    } catch (_) {
      row.focus();
    }
  }

  function shouldShowExpandedPreview() {
    return currentViewMode === "expanded";
  }

  function rowPreviewVisible(row, isActive) {
    if (!row) return false;
    if (shouldShowExpandedPreview()) return !!isActive;
    return inlineExpandedRow === row;
  }

  function renderRowState(row, isActive) {
    if (!row) return;
    const preview = row.querySelector(".entry-row-preview");
    const previewVisible = rowPreviewVisible(row, isActive);
    row.classList.toggle("active", !!isActive);
    row.classList.toggle("preview-open", previewVisible);
    row.setAttribute("aria-expanded", previewVisible ? "true" : "false");
    if (preview) {
      preview.hidden = !previewVisible;
    }
  }

  function collapseInlinePreview() {
    if (!inlineExpandedRow) return;
    const row = inlineExpandedRow;
    inlineExpandedRow = null;
    renderRowState(row, row === activeRow);
  }

  function expandInlinePreview(row) {
    if (!row || shouldShowExpandedPreview()) return;
    if (inlineExpandedRow && inlineExpandedRow !== row) {
      renderRowState(inlineExpandedRow, inlineExpandedRow === activeRow);
    }
    inlineExpandedRow = row;
    renderRowState(row, row === activeRow);
  }

  function openRow(row) {
    if (!row || !row.href) return;
    rememberFeedViewState({
      anchorEntryId: row.dataset.entryId || "",
      activeEntryId: row.dataset.entryId || "",
    });
    window.location.assign(row.href);
  }

  function setExpanded(row, expanded) {
    renderRowState(row, expanded);
  }

  function viewportBounds() {
    const scrollContainer = getFeedScrollContainer();
    if (scrollContainer && scrollContainer !== window) {
      const rect = scrollContainer.getBoundingClientRect();
      return {
        top: rect.top + 8,
        bottom: rect.bottom - 14,
      };
    }
    const header = document.querySelector("header");
    const topInset = header ? Math.ceil(header.getBoundingClientRect().bottom) + 8 : 8;
    const bottomInset = 14;
    return {
      top: topInset,
      bottom: window.innerHeight - bottomInset,
    };
  }

  function scrollMetrics() {
    const scrollContainer = getFeedScrollContainer();
    if (scrollContainer && scrollContainer !== window) {
      return {
        scrollContainer,
        viewport: scrollContainer.clientHeight || 0,
      };
    }
    return {
      scrollContainer: window,
      viewport: window.innerHeight || document.documentElement.clientHeight || 0,
    };
  }

  function scrollRowIntoViewIfNeeded(row, behavior = "auto") {
    if (!row) return;
    const scrollContainer = getFeedScrollContainer();
    const rect = row.getBoundingClientRect();
    const bounds = viewportBounds();
    const deltaTop = rect.top - bounds.top;
    const deltaBottom = rect.bottom - bounds.bottom;
    const delta = deltaTop < 0 ? deltaTop : (deltaBottom > 0 ? deltaBottom : 0);
    if (!delta) return;

    if (scrollContainer && scrollContainer !== window) {
      if (typeof scrollContainer.scrollBy === "function") {
        scrollContainer.scrollBy({ top: delta, behavior });
      } else {
        scrollContainer.scrollTop += delta;
      }
      return;
    }
    if (typeof window.scrollBy !== "function") return;
    if (rect.top < bounds.top) {
      window.scrollBy({ top: rect.top - bounds.top, behavior });
    } else if (rect.bottom > bounds.bottom) {
      window.scrollBy({ top: rect.bottom - bounds.bottom, behavior });
    }
  }

  function findBestVisibleRow() {
    const rows = getRows();
    if (!rows.length) return null;
    const bounds = viewportBounds();
    const anchor = bounds.top + ((bounds.bottom - bounds.top) * 0.35);
    let bestRow = null;
    let bestDistance = Number.POSITIVE_INFINITY;

    for (const row of rows) {
      const rect = row.getBoundingClientRect();
      const visibleTop = Math.max(rect.top, bounds.top);
      const visibleBottom = Math.min(rect.bottom, bounds.bottom);
      const visibleHeight = visibleBottom - visibleTop;
      if (visibleHeight <= 0) continue;
      const distance = Math.abs(rect.top - anchor);
      if (distance < bestDistance) {
        bestDistance = distance;
        bestRow = row;
      }
    }

    return bestRow || rows[0];
  }

  function findAdjacentRow(row, direction = 1) {
    const rows = getRows();
    const index = rows.indexOf(row);
    if (index < 0) return null;
    return rows[index + direction] || null;
  }

  function syncActiveRowToViewport(options = {}) {
    const nextRow = findBestVisibleRow();
    if (!nextRow) return;
    activateRow(nextRow, {
      focus: options.focus === true,
      scroll: false,
      behavior: options.behavior || "auto",
    });
  }

  function pageScroll(direction, fraction) {
    const { scrollContainer, viewport } = scrollMetrics();
    if (!viewport) return;
    const overlap = fraction >= 1 ? 24 : 0;
    const amount = Math.max(0, Math.round((viewport * fraction) - overlap)) * direction;

    if (scrollContainer && scrollContainer !== window) {
      if (typeof scrollContainer.scrollBy === "function") {
        scrollContainer.scrollBy({ top: amount, behavior: "auto" });
      } else {
        scrollContainer.scrollTop += amount;
      }
    } else if (typeof window.scrollBy === "function") {
      window.scrollBy({ top: amount, behavior: "auto" });
    }

    requestAnimationFrame(() => {
      syncActiveRowToViewport({ focus: true, behavior: "auto" });
    });
  }

  function activateRow(row, options = {}) {
    if (!row) return;
    const shouldFocus = options.focus === true;
    const shouldScroll = options.scroll === true;
    const scrollBehavior = options.behavior || "auto";

    if (activeRow && activeRow !== row) {
      collapseInlinePreview();
      setExpanded(activeRow, false);
    }

    activeRow = row.isConnected ? row : null;
    if (!activeRow) return;
    syncRowPreview(activeRow);
    setExpanded(activeRow, true);
    rememberFeedViewState({ activeEntryId: activeRow.dataset.entryId || "" });

    if (shouldFocus && typeof activeRow.focus === "function" && document.activeElement !== activeRow) {
      try {
        activeRow.focus({ preventScroll: true });
      } catch (_) {
        activeRow.focus();
      }
    }

    if (shouldScroll) {
      requestAnimationFrame(() => {
        if (activeRow === row) {
          scrollRowIntoViewIfNeeded(row, scrollBehavior);
        }
      });
    }
  }

  function moveActiveRow(delta) {
    const rows = getRows();
    if (!rows.length) return;
    let index = activeRow ? rows.indexOf(activeRow) : -1;
    if (index < 0) {
      index = delta > 0 ? -1 : rows.length;
    }
    index = Math.max(0, Math.min(rows.length - 1, index + delta));
    activateRow(rows[index], { focus: true, scroll: true, behavior: "auto" });
  }

  function jumpToRow(position) {
    const rows = getRows();
    if (!rows.length) return;
    const row = position === "end" ? rows[rows.length - 1] : rows[0];
    activateRow(row, { focus: true, scroll: true, behavior: "auto" });
  }

  function bindRow(row) {
    if (!row || row.dataset.activityBound === "1") return;
    row.dataset.activityBound = "1";
    row.dataset.read = row.classList.contains("read") ? "1" : (row.dataset.read || "0");
    syncRowPreview(row);
    setExpanded(row, false);

    row.addEventListener("click", (event) => {
      const isPrimaryClick = event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;

      if (!isPrimaryClick) {
        return;
      }

      if (activeRow !== row) {
        event.preventDefault();
        activateRow(row, { focus: true, behavior: "auto" });
        return;
      }

      rememberFeedViewState({
        anchorEntryId: row.dataset.entryId || "",
        activeEntryId: row.dataset.entryId || "",
      });
    });

    row.addEventListener("focus", () => {
      if (!lastInputWasKeyboard) return;
      activateRow(row, { behavior: "auto" });
    });

    row.addEventListener("keydown", (event) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key !== "Enter") return;

      if (activeRow !== row) {
        event.preventDefault();
        activateRow(row, { focus: true, behavior: "auto" });
        openInlinePreview(row);
        return;
      }

      if (!rowPreviewIsVisible(row)) {
        event.preventDefault();
        focusRow(row);
        openInlinePreview(row);
      }
    });
  }

  document.addEventListener("keydown", () => {
    lastInputWasKeyboard = true;
  }, true);
  document.addEventListener("pointerdown", () => {
    lastInputWasKeyboard = false;
  }, true);

  if (shortcutsHelpClose) {
    shortcutsHelpClose.addEventListener("click", (event) => {
      event.preventDefault();
      hideShortcutsHelp();
    });
  }

  document.querySelectorAll(".entry-row").forEach(bindRow);
  window.bindEntryRowActivity = bindRow;

  window.__entryRowActivityRefreshViewMode = function refreshViewMode(mode) {
    currentViewMode = normalizeEntryViewMode(mode);
    collapseInlinePreview();
    getRows().forEach((row) => {
      setExpanded(row, row === activeRow);
    });
    if (activeRow && shouldShowExpandedPreview()) {
      syncRowPreview(activeRow);
    }
  };

  if (!coarsePointer) {
    const initialRows = getRows();
    const restoredActiveId = _restoredFeedViewState
      ? String(_restoredFeedViewState.activeEntryId || "").trim()
      : "";
    const initialActive = initialRows.find((row) => row.dataset.entryId === restoredActiveId)
      || initialRows.find((row) => !row.classList.contains("read"))
      || initialRows[0]
      || null;
    if (initialActive) {
      activateRow(initialActive, { behavior: "auto" });
    }
  }

  try {
    if (sessionStorage.getItem(SHORTCUTS_HELP_SESSION_KEY) !== "1") {
      sessionStorage.setItem(SHORTCUTS_HELP_SESSION_KEY, "1");
      window.setTimeout(() => {
        showShortcutsHelp({ autoHide: true, durationMs: 8000 });
      }, 450);
    }
  } catch (_) {
    window.setTimeout(() => {
      showShortcutsHelp({ autoHide: true, durationMs: 8000 });
    }, 450);
  }

  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
    if (shouldIgnoreRowShortcuts(event.target)) return;

    if (event.key === "Escape") {
      collapseInlinePreview();
      hideShortcutsHelp();
      pendingGUntil = 0;
      return;
    }

    if (event.key === "?" || (event.code === "Slash" && event.shiftKey)) {
      event.preventDefault();
      pendingGUntil = 0;
      showShortcutsHelp({ autoHide: false });
      return;
    }

    if (event.key === "g" && !event.shiftKey) {
      const now = Date.now();
      event.preventDefault();
      if (pendingGUntil > now) {
        pendingGUntil = 0;
        jumpToRow("start");
      } else {
        pendingGUntil = now + 450;
      }
      return;
    }

    pendingGUntil = 0;

    if (event.key === "Enter") {
      if (!activeRow) return;
      if (!rowPreviewIsVisible(activeRow)) {
        event.preventDefault();
        activateRow(activeRow, { focus: true, behavior: "auto" });
        openInlinePreview(activeRow);
        return;
      }
      if (document.activeElement === activeRow) {
        return;
      }
      event.preventDefault();
      activateRow(activeRow, { focus: true, behavior: "auto" });
    } else if (event.key === "j" || event.key === "ArrowDown") {
      event.preventDefault();
      moveActiveRow(1);
    } else if (event.key === "k" || event.key === "ArrowUp") {
      event.preventDefault();
      moveActiveRow(-1);
    } else if (event.key === "G") {
      event.preventDefault();
      jumpToRow("end");
    } else if (event.key === "d" && !event.shiftKey) {
      event.preventDefault();
      pageScroll(1, 0.5);
    } else if (event.key === "u" && !event.shiftKey) {
      event.preventDefault();
      pageScroll(-1, 0.5);
    } else if (event.key === " " || event.code === "Space") {
      event.preventDefault();
      pageScroll(event.shiftKey ? -1 : 1, 1);
    }
  });

  let previewCollapseQueued = false;
  function queueInlinePreviewCollapseCheck() {
    if (previewCollapseQueued) return;
    previewCollapseQueued = true;
    requestAnimationFrame(() => {
      previewCollapseQueued = false;
      if (!inlineExpandedRow || shouldShowExpandedPreview()) return;
      const rect = inlineExpandedRow.getBoundingClientRect();
      const bounds = viewportBounds();
      if (rect.bottom < bounds.top || rect.top > bounds.bottom) {
        collapseInlinePreview();
      }
    });
  }

  window.addEventListener("scroll", queueInlinePreviewCollapseCheck, { passive: true });
  entriesPanel.addEventListener("scroll", queueInlinePreviewCollapseCheck, { passive: true });
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
  const _pendingReadIds = new Set();

  function markRead(entryId, eventOrEl) {
    const target = eventOrEl && eventOrEl.currentTarget ? eventOrEl.currentTarget : eventOrEl;
    const row = target && typeof target.closest === "function"
      ? target.closest(".entry-row")
      : null;
    const key = String(entryId);
    const alreadyRead = row
      ? row.classList.contains("read") || row.dataset.read === "1"
      : _pendingReadIds.has(key);
    if (row) {
      row.classList.add("read");
      row.dataset.read = "1";
    }
    if (alreadyRead || _pendingReadIds.has(key)) {
      return;
    }
    _pendingReadIds.add(key);
    fetch(`/api/entries/${entryId}/read`, { method: "POST", keepalive: true })
      .then((res) => {
        if (!res.ok) {
          _pendingReadIds.delete(key);
        }
      })
      .catch(() => {
        _pendingReadIds.delete(key);
      });
  }
  window.markRead = markRead;

  // ── Delete feed from sidebar/nav ────────────────────────────────────
  function refreshTrendingAfterFeedRemoval() {
    document.querySelectorAll(".trending-list").forEach((list) => {
      const items = Array.from(list.querySelectorAll(".trending-item"));
      const section = list.closest(".sidebar-section");
      const empty = section ? section.querySelector(".trending-empty") : null;
      if (!items.length) {
        if (empty) return;
        const emptyState = document.createElement("div");
        emptyState.className = "trending-empty";
        emptyState.innerHTML = "<p>No trending articles yet.</p>";
        list.insertAdjacentElement("afterend", emptyState);
        return;
      }
      if (empty) {
        empty.remove();
      }
      items.forEach((item, index) => {
        const link = item.querySelector(".trending-title");
        if (!link) return;
        link.textContent = link.textContent.replace(/^\d+\.\s+/, `${index + 1}. `);
      });
    });
  }

  function refreshSubscriptionsAfterFeedRemoval() {
    const list = document.getElementById("feeds-list");
    if (!list) return;
    const hasRows = !!list.querySelector(".subscriptions-row");
    let empty = document.querySelector(".catalog-empty");
    if (hasRows) {
      if (empty) empty.remove();
      return;
    }
    if (!empty) {
      empty = document.createElement("p");
      empty.className = "catalog-empty";
      empty.innerHTML = 'No subscriptions yet. <a href="/add-feed">Add a feed</a> or browse <a href="/discover">Discover</a>.';
      list.insertAdjacentElement("afterend", empty);
    }
  }

  async function deleteFeed(feedId, btn, options = {}) {
    if (btn) btn.disabled = true;
    try {
      const res = await fetch(`/api/feeds/${feedId}`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        document.querySelectorAll(`[data-feed-id="${feedId}"]`).forEach((row) => row.remove());
        refreshTrendingAfterFeedRemoval();
        refreshSubscriptionsAfterFeedRemoval();
        if (typeof window.refreshEntryListAfterFeedRemoval === "function") {
          window.refreshEntryListAfterFeedRemoval(feedId);
        }
        // If we were viewing this feed, send user back to main list
        const params = new URLSearchParams(window.location.search);
        if (params.get("feed_id") === String(feedId)) {
          window.location.href = "/";
          return { ok: true, data };
        }
        toast(data.message || options.successMessage || "Feed removed.");
        return { ok: true, data };
      } else {
        toast(data.detail || options.failureMessage || "Could not remove feed.", false);
        return { ok: false, data };
      }
    } catch (_) {
      toast(options.networkMessage || "Network error removing feed.", false);
      return { ok: false, data: null };
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
    const entriesPanel = document.getElementById("entries-panel");
    if (!entriesList) return;

    function buildEntryRow(e) {
      const row = document.createElement("a");
      const articleHref = _articleUrlForId(e.id);
      const previewUrl = e.link || articleHref;
      const previewImage = e.og_image_url || e.thumbnail_url || "";
      const previewCopyText = stripTags(e.og_description || e.summary || "").trim();
      const previewId = `entry-preview-${e.id}`;

      row.href = articleHref;
      row.className = "entry-row" + (e.read ? " read" : "");
      row.dataset.entryId = String(e.id);
      row.dataset.feedId = String(e.feed_id);
      row.dataset.read = e.read ? "1" : "0";
      row.dataset.previewUrl = previewUrl;
      row.dataset.previewImage = previewImage;
      row.dataset.previewCopy = previewCopyText;
      row.setAttribute("aria-expanded", "false");
      row.setAttribute("aria-controls", previewId);

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

      if (previewCopyText) {
        const divider = document.createElement("span");
        divider.className = "entry-row-divider";
        divider.textContent = ":";
        const description = document.createElement("span");
        description.className = "entry-row-description";
        description.textContent = previewCopyText;
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

      const preview = document.createElement("span");
      preview.className = "entry-row-preview";
      preview.id = previewId;
      preview.dataset.hasImage = previewImage ? "1" : "0";
      preview.hidden = true;

      const previewBody = document.createElement("span");
      previewBody.className = "entry-row-preview-body";
      if (previewCopyText) {
        const previewCopy = document.createElement("span");
        previewCopy.className = "entry-row-preview-copy";
        previewCopy.textContent = previewCopyText;
        previewBody.appendChild(previewCopy);
      }

      const previewUrlEl = document.createElement("span");
      previewUrlEl.className = "entry-row-preview-url";
      previewUrlEl.textContent = normalizePreviewUrl(row.dataset.previewUrl || "");
      previewBody.appendChild(previewUrlEl);
      preview.appendChild(previewBody);

      const previewImg = document.createElement("img");
      previewImg.className = "entry-row-preview-image";
      previewImg.alt = "";
      previewImg.loading = "lazy";
      if (previewImage) {
        previewImg.src = previewImage;
        previewImg.hidden = false;
      } else {
        previewImg.hidden = true;
      }
      preview.appendChild(previewImg);

      row.appendChild(preview);

      if (typeof window.bindEntryRowActivity === "function") {
        window.bindEntryRowActivity(row);
      }

      return row;
    }

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
      const { q, scope, feedId, qualityLevel, days, themes, readStatus, sort } = getCurrentFilters();
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(existing));
      if (q) params.set("q", q);
      params.set("scope", scope);
      if (scope === "my" && feedId) params.set("feed_id", feedId);
      if (qualityLevel) params.set("quality_level", qualityLevel);
      if (days) params.set("days", days);
      if (themes) params.set("themes", themes);
      if (readStatus) params.set("read_status", readStatus);
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
        entriesList.appendChild(buildEntryRow(e));
      }
      applyLocalPublishedDates(entriesList);
      if (typeof window.__entryRowActivityRefreshViewMode === "function") {
        window.__entryRowActivityRefreshViewMode(
          document.documentElement.getAttribute("data-entry-view") || getStoredEntryViewMode()
        );
      }
    }

    function updateEntriesSummary() {
      const count = entriesList.querySelectorAll(".entry-row").length;
      const countValue = document.querySelector(".entries-header-count-value");
      const countCopy = document.querySelector(".entries-header-count-copy");
      if (countValue) {
        countValue.textContent = count.toLocaleString();
      }
      if (countCopy) {
        countCopy.textContent = count === 1 ? "article" : "articles";
      }
    }

    function ensureEmptyEntriesState() {
      if (entriesList.querySelector(".entry-row") || entriesList.querySelector(".empty-state")) {
        return;
      }
      const filters = typeof getCurrentFilters === "function"
        ? getCurrentFilters()
        : { scope: "my" };
      const emptyState = document.createElement("div");
      emptyState.className = "empty-state";
      emptyState.innerHTML = filters.scope === "discover"
        ? '<div style="font-size:2.5rem">&#128237;</div><p>No discover articles yet. Switch back to <a href="/">My Feed</a> or add more feeds to the catalogue.</p>'
        : '<div style="font-size:2.5rem">&#128237;</div><p>No articles left in this feed. Use <a href="/add-feed">Add Feed</a> to add feeds, then switch to <a href="/?scope=discover">Discover</a>.</p>';
      entriesList.appendChild(emptyState);
    }

    window.refreshEntryListAfterFeedRemoval = function refreshEntryListAfterFeedRemoval() {
      updateEntriesSummary();
      ensureEmptyEntriesState();
    };

    function maybeLoadMore() {
      if (isLoadingMore || allLoaded) return;
      const scrollContainer = getFeedScrollContainer();
      let scrollY = 0;
      let viewport = 0;
      let docHeight = 0;

      if (scrollContainer && scrollContainer !== window) {
        scrollY = scrollContainer.scrollTop || 0;
        viewport = scrollContainer.clientHeight || 0;
        docHeight = scrollContainer.scrollHeight || 0;
      } else {
        scrollY = window.scrollY || window.pageYOffset || 0;
        viewport = window.innerHeight || document.documentElement.clientHeight || 0;
        docHeight = document.documentElement.scrollHeight || document.body.scrollHeight || 0;
      }

      // Start loading a bit before the user hits the end.
      if (scrollY + viewport + 400 >= docHeight) {
        loadMoreEntries();
      }
    }

    window.addEventListener("scroll", maybeLoadMore, { passive: true });
    if (entriesPanel) {
      entriesPanel.addEventListener("scroll", maybeLoadMore, { passive: true });
    }
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
        if (params.readStatus) searchParams.set("read_status", params.readStatus);
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
