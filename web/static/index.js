  // ── Nav drawer (overlay only on mobile; desktop uses sidebar) ─────
  const navOverlay = document.getElementById("nav-overlay");
  const NAV_OPEN_KEY = "nav-open";
  const MOBILE_MAX = 640;
const ARTICLE_PATH_RE = /^\/article\/(\d+)\/?$/;
const ARTICLE_CONTEXT_KEYS = ["q", "feed_id", "quality_level", "days", "scope", "themes", "sort"];
const RANDOM_HISTORY_KEY = "myrssfeed_random_history";
const RANDOM_HISTORY_LIMIT = 120;
const RANDOM_RETRY_WINDOWS = [120, 40, 12, 0];

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

function _currentArticleId() {
  const match = (window.location.pathname || "").match(ARTICLE_PATH_RE);
  return match ? match[1] : "";
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

function _parseRandomHistory(raw) {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((value) => parseInt(value, 10))
      .filter((value) => Number.isInteger(value) && value > 0);
  } catch (_) {
    return [];
  }
}

function _loadRandomHistory() {
  return _parseRandomHistory(_safeSessionGet(RANDOM_HISTORY_KEY));
}

function _saveRandomHistory(history) {
  const next = Array.isArray(history) ? history.slice(-RANDOM_HISTORY_LIMIT) : [];
  _safeSessionSet(RANDOM_HISTORY_KEY, JSON.stringify(next));
}

function _rememberRandomArticle(entryId) {
  const id = parseInt(entryId, 10);
  if (!Number.isInteger(id) || id <= 0) return;
  const history = _loadRandomHistory().filter((value) => value !== id);
  history.push(id);
  _saveRandomHistory(history);
}

function _sessionRandomIds(extraIds = []) {
  const ids = [];
  const seen = new Set();
  const add = (value) => {
    const id = parseInt(value, 10);
    if (!Number.isInteger(id) || id <= 0 || seen.has(id)) return;
    seen.add(id);
    ids.push(id);
  };
  _loadRandomHistory().forEach(add);
  extraIds.forEach(add);
  return ids.slice(-RANDOM_HISTORY_LIMIT);
}

function _randomExclusionBatches(extraIds = []) {
  const full = _sessionRandomIds(extraIds);
  const batches = [];
  const seen = new Set();
  for (const windowSize of RANDOM_RETRY_WINDOWS) {
    const batch = windowSize > 0 ? full.slice(-windowSize) : [];
    const key = batch.join(",");
    if (seen.has(key)) continue;
    seen.add(key);
    batches.push(batch);
  }
  return batches;
}

async function _openRandomArticle({ excludeId = "", walk = null } = {}) {
  const currentId = _currentArticleId();
  const extraIds = [];
  if (excludeId) extraIds.push(excludeId);
  if (currentId) extraIds.push(currentId);
  const batches = _randomExclusionBatches(extraIds);

  for (const batch of batches) {
    const params = _articleContextParams();
    if (batch.length) {
      params.set("exclude_ids", batch.join(","));
    }
    if (walk && walk.anchorId) {
      params.set("walk_anchor_id", walk.anchorId);
    }
    if (walk && typeof walk.direction === "number" && !Number.isNaN(walk.direction)) {
      params.set("walk_direction", String(walk.direction));
    }
    if (walk && typeof walk.strength === "number" && !Number.isNaN(walk.strength)) {
      params.set("walk_strength", String(walk.strength));
    }

    try {
      const res = await fetch("/api/random-article?" + params.toString());
      if (!res.ok) {
        if (res.status === 404) {
          continue;
        }
        const data = await res.json().catch(() => ({}));
        toast(data.detail || "No random article found.", false);
        return;
      }
      const data = await res.json();
      _rememberRandomArticle(data.id);
      const target = data.article_url || _articleUrlForId(data.id);
      window.location.assign(target);
      return;
    } catch (_) {
      toast("Network error loading a random article.", false);
      return;
    }
  }

  toast("No random article found.", false);
}

async function _walkAndOpenArticle(direction) {
  const nav = typeof window !== "undefined" ? window.ARTICLE_NAV || null : null;
  if (nav) {
    const targetUrl = direction < 0 ? nav.prevUrl : nav.nextUrl;
    if (targetUrl) {
      window.location.assign(targetUrl);
    } else {
      toast(direction < 0 ? "This is the first article in the feed." : "This is the last article in the feed.");
    }
    return;
  }

  const entryId = _currentArticleId();
  if (!entryId) {
    await _openRandomArticle();
    return;
  }

  await _openRandomArticle({
    excludeId: entryId,
    walk: {
      anchorId: entryId,
      direction: direction < 0 ? -1 : 1,
      strength: 1,
    },
  });
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
          <button type="button" data-action="random">
            <span class="menu-icon">&#127922;</span><span>Random article</span>
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
          case "random":
            headerToggleRandom();
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

  async function headerToggleRandom() {
    await _openRandomArticle();
  }
  window.headerToggleRandom = headerToggleRandom;

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && navOverlay && navOverlay.classList.contains("open")) {
      closeNav();
    }
  });

  // ── Header quick-action status lights ─────────────────────────────
  function _updateHeaderDot(id, state, opts = {}) {
    const dot = document.getElementById(id);
    if (!dot) return;
    dot.className = "refresh-status-dot";
    if (state.running) {
      dot.classList.add("running");
      if (opts.textId) {
        const textEl = document.getElementById(opts.textId);
        if (textEl) textEl.textContent = "Running";
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
      setInterval(_fetchHeaderRefreshStatus, 8000);
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

 // ── Image lightbox ──────────────────────────────────────────────
 const lightbox    = document.getElementById("img-lightbox");
 const lightboxImg = document.getElementById("img-lightbox-img");

 function openLightbox(src) {
   if (!lightbox || !lightboxImg) return;
   lightboxImg.src = src;
   lightbox.classList.add("open");
   document.body.style.overflow = "hidden";
 }

 function closeLightbox() {
   if (!lightbox || !lightboxImg) return;
   lightbox.classList.remove("open");
   lightboxImg.src = "";
   document.body.style.overflow = "";
 }

 if (lightbox) {
   lightbox.addEventListener("click", (e) => {
     if (e.target === lightbox) closeLightbox();
   });
 }

 document.addEventListener("keydown", (e) => {
   if (e.key === "Escape" && lightbox && lightbox.classList.contains("open")) {
     closeLightbox();
   }
 });

 document.addEventListener("click", (e) => {
   if (e.target.classList && e.target.classList.contains("entry-thumb")) {
     openLightbox(e.target.src);
   }
 });

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

(function initRandomArticleHistory() {
  if (!document.body.classList.contains("article-page")) return;
  _rememberRandomArticle(_currentArticleId());
})();

(function initArticleSwipeNavigation() {
  if (!document.body.classList.contains("article-page")) return;
  const articleView = document.querySelector(".article-view");
  if (!articleView) return;

  let startX = 0;
  let startY = 0;
  let tracking = false;

  function reset() {
    tracking = false;
    startX = 0;
    startY = 0;
  }

  articleView.addEventListener("touchstart", (e) => {
    if (!e.touches || e.touches.length !== 1) return;
    const touch = e.touches[0];
    tracking = true;
    startX = touch.clientX;
    startY = touch.clientY;
  }, { passive: true });

  articleView.addEventListener("touchend", async (e) => {
    if (!tracking) return;
    const touch = e.changedTouches && e.changedTouches[0];
    if (!touch) {
      reset();
      return;
    }
    const dx = touch.clientX - startX;
    const dy = touch.clientY - startY;
    reset();
    if (Math.abs(dx) < 72) return;
    if (Math.abs(dx) < Math.abs(dy) * 1.25) return;
    await _walkAndOpenArticle(dx > 0 ? 1 : -1);
  }, { passive: true });

  articleView.addEventListener("touchcancel", reset, { passive: true });

  function isTypingTarget(target) {
    if (!target || !target.tagName) return false;
    const tag = target.tagName.toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable;
  }

  document.addEventListener("keydown", async (e) => {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
    if (isTypingTarget(e.target)) return;
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;

    e.preventDefault();
    await _walkAndOpenArticle(e.key === "ArrowRight" ? 1 : -1);
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
  function markRead(entryId, el) {
    const card = el.closest(".entry-card");
    if (card && !card.classList.contains("read")) {
      card.classList.add("read");
      fetch(`/api/entries/${entryId}/read`, { method: "POST" }).catch(() => {});
    }
  }

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
    const entriesPanel = document.getElementById("entries-panel");
    if (!entriesPanel) return; // Only on the main index page

    let isLoadingMore = false;
    let allLoaded = false;

    // Use the number of server-rendered cards as our page size heuristic.
    const INITIAL_CARDS = entriesPanel.querySelectorAll(".entry-card").length;
    const PAGE_SIZE = INITIAL_CARDS || 40;

    async function loadMoreEntries() {
      if (isLoadingMore || allLoaded) return;
      const existing = entriesPanel.querySelectorAll(".entry-card").length;
      if (!existing && INITIAL_CARDS === 0) {
        // No entries at all; nothing to page through.
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
      const frag = document.createDocumentFragment();
      for (const e of entries) {
        const card = buildEntryCard(e);
        frag.appendChild(card);
      }
      entriesPanel.appendChild(frag);
    }

    function buildEntryCard(e) {
      const card = document.createElement("article");
      const hasThumb = !!e.thumbnail_url;
      card.className = "entry-card" +
        (e.read ? " read" : "") +
        (hasThumb ? " has-thumb" : "");
      card.dataset.entryId = String(e.id);

      const link = document.createElement("a");
      link.href = _articleUrlForId(e.id);
      link.className = "entry-card-link";

      const headerRow = document.createElement("div");
      headerRow.className = "entry-header-row";
      const titleEl = document.createElement("div");
      titleEl.className = "entry-title";
      titleEl.textContent = e.title || "(no title)";
      headerRow.appendChild(titleEl);

      const meta = document.createElement("div");
      meta.className = "entry-meta";
      const feedInfo = (window.FEED_MAP && window.FEED_MAP[e.feed_id]) || {};
      const domain = e.feed_domain || feedInfo.domain;

      const favicon = document.createElement("img");
      favicon.className = "entry-favicon";
      if (domain) {
        favicon.src = "https://www.google.com/s2/favicons?domain=" +
          encodeURIComponent(domain) + "&sz=32";
      }
      favicon.width = 14;
      favicon.height = 14;
      favicon.loading = "lazy";
      favicon.alt = "";

      const tag = document.createElement("span");
      tag.className = "tag entry-source-tag";
      tag.textContent = e.feed_title || "Unknown";

      const date = document.createElement("time");
      date.className = "entry-date";
      date.textContent = _publishedDateText(e.published);
      if (e.published) {
        date.setAttribute("data-published", e.published);
        date.setAttribute("data-published-format", "date");
        date.dateTime = e.published;
      }

      meta.appendChild(favicon);
      meta.appendChild(tag);
      meta.appendChild(date);

      const body = document.createElement("div");
      body.className = "entry-body";

      const content = document.createElement("div");
      content.className = "entry-content";
      if (e.summary) {
        const summary = document.createElement("div");
        summary.className = "entry-summary";
        summary.textContent = stripTags(e.summary);
        content.appendChild(summary);
      }

      body.appendChild(content);

      if (hasThumb) {
        const img = document.createElement("img");
        img.className = "entry-thumb";
        img.src = e.thumbnail_url;
        img.alt = "";
        img.loading = "lazy";
        body.appendChild(img);
      }

      link.appendChild(headerRow);
      link.appendChild(meta);
      link.appendChild(body);

      const linkRow = document.createElement("div");
      linkRow.className = "entry-link-row";
      const original = document.createElement("a");
      original.href = e.link || _articleUrlForId(e.id);
      original.target = "_blank";
      original.rel = "noopener noreferrer";
      original.textContent = "Read full article";
      if (e.link) {
        original.addEventListener("click", (evt) => {
          try { markRead(e.id, evt.currentTarget); } catch (_) {}
        });
      }
      linkRow.appendChild(original);

      card.appendChild(link);
      card.appendChild(linkRow);

      return card;
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
