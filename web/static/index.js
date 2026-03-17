  // ── Nav drawer (overlay only on mobile; desktop uses sidebar) ─────
  const navOverlay = document.getElementById("nav-overlay");
  const NAV_OPEN_KEY = "nav-open";
  const RANDOM_SEED_KEY = "myrssfeed_random_seed";
  const MOBILE_MAX = 640;

  function isMobileViewport() {
    return typeof window !== "undefined" && window.innerWidth <= MOBILE_MAX;
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

  function toggleNavFeeds() {
    const btn = document.getElementById("nav-feeds-toggle");
    const list = document.getElementById("nav-feeds-list");
    btn.classList.toggle("open");
    list.classList.toggle("open");
  }

  function _getCookie(name) {
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = document.cookie.match(new RegExp("(?:^|; )" + escaped + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function _setCookie(name, value) {
    document.cookie = `${encodeURIComponent(name)}=${encodeURIComponent(value)}; Path=/; Max-Age=31536000; SameSite=Lax`;
  }

  function _getRandomSeed() {
    const raw = _getCookie(RANDOM_SEED_KEY);
    return /^\d+$/.test(raw) ? raw : "";
  }

  function _hasRandomSeed() {
    return !!_getRandomSeed();
  }

  function _generateRandomSeed() {
    try {
      const buf = new Uint32Array(1);
      window.crypto.getRandomValues(buf);
      return String(buf[0] >>> 0);
    } catch (_) {
      return String(Date.now() ^ Math.floor(Math.random() * 0xffffffff));
    }
  }

  function _syncRandomButtonState(enabled) {
    const btn = document.getElementById("header-random-btn");
    if (!btn) return;
    btn.classList.toggle("active", enabled);
    btn.setAttribute("aria-pressed", enabled ? "true" : "false");
    btn.title = enabled ? "Re-randomize article order" : "Randomize article order";
  }

  function headerToggleRandom() {
    _setCookie(RANDOM_SEED_KEY, _generateRandomSeed());
    _syncRandomButtonState(true);
    window.location.reload();
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
        if (textEl) textEl.textContent = "Job in progress";
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
        let label = "No runs yet";
        const mins = typeof state.minutes_since_last_success === "number"
          ? state.minutes_since_last_success
          : null;
        if (opts.kind === "refresh" || opts.kind === "scrape") {
          if (last === "success") {
            if (mins !== null) {
              label = mins === 0 ? "Just now" : `${mins} min ago`;
            } else {
              label = "Last job completed";
            }
          } else if (last === "error") {
            label = "Last job failed";
          }
        } else if (opts.kind === "wordrank") {
          if (last === "success") {
            if (mins !== null) {
              label = mins === 0 ? "Last run just now" : `Last run ${mins} min ago`;
            } else {
              label = "Last run completed";
            }
          } else if (last === "error") {
            label = "Last run failed";
          } else if (!last || last === "idle" || last === "never") {
            label = "Idle";
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

  async function _fetchHeaderScrapeStatus() {
    const dotId = "header-scrape-status-dot";
    if (!document.getElementById(dotId)) return;
    try {
      const res = await fetch("/api/scrape/status");
      if (!res.ok) return;
      const data = await res.json().catch(() => ({}));
      _updateHeaderDot(dotId, {
        running: !!data.running,
        last_status: data.last_status || "never",
        minutes_since_last_success: typeof data.minutes_since_last_success === "number"
          ? data.minutes_since_last_success
          : null,
      }, { kind: "scrape", textId: "header-scrape-status-text" });
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

  async function headerScrapeNow() {
    const btn = document.getElementById("header-scrape-btn");
    if (!btn) return;
    if (btn.disabled) return;
    btn.disabled = true;
    try {
      const res = await fetch("/api/scrape", { method: "POST" });
      if (res.ok) {
        const data = await res.json().catch(() => ({}));
        toast(data.message || "Scrape started.");
        _updateHeaderDot(
          "header-scrape-status-dot",
          { running: true, last_status: "running" },
          { kind: "scrape", textId: "header-scrape-status-text" },
        );
        setTimeout(_fetchHeaderScrapeStatus, 2000);
      } else {
        const data = await res.json().catch(() => ({}));
        toast(data.detail || "Could not start scrape.", false);
      }
    } catch (_) {
      toast("Network error starting scrape.", false);
    } finally {
      btn.disabled = false;
    }
  }
  window.headerScrapeNow = headerScrapeNow;

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
    if (document.getElementById("header-scrape-status-dot")) {
      _fetchHeaderScrapeStatus();
      setInterval(_fetchHeaderScrapeStatus, 8000);
    }
    if (document.getElementById("header-wordrank-status-dot")) {
      _fetchHeaderWordrankStatus();
    }
  })();

  (function initHeaderRandomState() {
    if (!document.getElementById("header-random-btn")) return;
    _syncRandomButtonState(_hasRandomSeed());
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
    _entryFilterEnabled = params.has("quality_level");
    const btn = document.getElementById("header-filter-btn");
    if (btn) {
      btn.classList.toggle("active", _entryFilterEnabled);
      btn.setAttribute("aria-pressed", _entryFilterEnabled ? "true" : "false");
    }
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

  // ── Toast ───────────────────────────────────────────────────────
  function toast(msg, ok = true) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.style.borderColor = ok ? "var(--accent)" : "var(--danger)";
    el.classList.add("show");
    setTimeout(() => el.classList.remove("show"), 2800);
  }

  // ── Feed label colors ────────────────────────────────────────────
  function _feedColor(feedTitle) {
    if (!feedTitle) return null;
    const parts = feedTitle.split(/\s*[|\-]\s*/);
    const category = (parts[parts.length - 1] || feedTitle).toLowerCase().trim();
    const source   = (parts[0] || feedTitle).toLowerCase().trim();
    let catHash = 0;
    for (const ch of category) catHash = (catHash * 31 + ch.charCodeAt(0)) & 0xfffffff;
    let srcHash = 0;
    for (const ch of source) srcHash = (srcHash * 31 + ch.charCodeAt(0)) & 0xfffffff;
    const hue  = catHash % 360;
    const sat  = 55 + (srcHash % 25);
    const lite = 58 + (srcHash % 12);
    return `hsl(${hue},${sat}%,${lite}%)`;
  }

  document.querySelectorAll(".tag.entry-source-tag[style]").forEach((tag) => {
    const feedColor = tag.style.getPropertyValue("--feed-color").trim();
    const color = feedColor || _feedColor(tag.textContent.trim());
    if (color) {
      tag.style.setProperty("--feed-color", color);
    }
  });

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

  function formatAssessmentLabel(label) {
    if (!label) return "";
    return String(label).replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
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

    function getCurrentFilters() {
      const params = new URLSearchParams(window.location.search || "");
      const q = params.get("q") || "";
      const scope = params.get("scope") || "my";
      const feedId = params.get("feed_id") || "";
      const qualityLevel = params.get("quality_level") || "";
      const days = params.get("days") || "";
      return { q, scope, feedId, qualityLevel, days };
    }

    async function loadMoreEntries() {
      if (isLoadingMore || allLoaded) return;
      const existing = entriesPanel.querySelectorAll(".entry-card").length;
      if (!existing && INITIAL_CARDS === 0) {
        // No entries at all; nothing to page through.
        allLoaded = true;
        return;
      }

      isLoadingMore = true;
      const { q, scope, feedId, qualityLevel, days } = getCurrentFilters();
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(existing));
      if (q) params.set("q", q);
      params.set("scope", scope);
      if (scope === "my" && feedId) params.set("feed_id", feedId);
      if (qualityLevel) params.set("quality_level", qualityLevel);
      if (days) params.set("days", days);

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
      link.href = "/article/" + encodeURIComponent(e.id);
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
      const sourceColor = feedInfo.color || _feedColor(e.feed_title || "");
      if (sourceColor) {
        tag.style.setProperty("--feed-color", sourceColor);
      }
      tag.textContent = e.feed_title || "Unknown";

      const assessmentLabel = document.createElement("span");
      assessmentLabel.className = "tag entry-assessment-tag";
      if (e.assessment_label_color) {
        assessmentLabel.style.setProperty("--assessment-color", e.assessment_label_color);
      }
      assessmentLabel.textContent = formatAssessmentLabel(e.assessment_label);

      const date = document.createElement("span");
      date.className = "entry-date";
      date.textContent = e.published ? String(e.published).slice(0, 10) : "";

      meta.appendChild(favicon);
      meta.appendChild(tag);
      if (e.assessment_label) {
        meta.appendChild(assessmentLabel);
      }
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
      original.href = e.link || ("/article/" + encodeURIComponent(e.id));
      original.target = "_blank";
      original.rel = "noopener noreferrer";
      original.textContent = e.link ? "Open original" : "Open article";
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
  let _searchTimer     = null;
  let _lastQuery       = "";

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
      const q = searchInput.value.trim();
      if (!q) {
        _closeDropdown(true);
        const params = new URLSearchParams(window.location.search || "");
        if (params.has("q")) {
          _returnToFeed();
        }
        return;
      }
      _searchTimer = setTimeout(() => _doLiveSearch(q), 220);
    });

    searchInput.addEventListener("keydown", (e) => {
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

    async function _doLiveSearch(q) {
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
        if (q !== searchInput.value.trim()) return;
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
        a.href = e.link || ("/article/" + encodeURIComponent(e.id));
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        const date = e.published ? e.published.slice(0, 10) : "";
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
      _doLiveSearch(searchInput.value.trim());
    }
  }
