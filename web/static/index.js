  // ── Nav drawer (overlay only on mobile; desktop uses sidebar) ─────
  const navOverlay = document.getElementById("nav-overlay");
  const NAV_OPEN_KEY = "nav-open";
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

  // ── Pull to refresh ────────────────────────────────────────────
  (function() {
    const panel = document.getElementById("entries-panel");
    const indicator = document.getElementById("ptr-indicator");
    if (!panel || !indicator) return;
    const textEl = indicator.querySelector(".ptr-text");
    let startY = 0;
    let pulling = false;
    const threshold = 80;

    panel.addEventListener("touchstart", (e) => {
      if (panel.scrollTop <= 0) {
        startY = e.touches[0].clientY;
        pulling = true;
      }
    }, { passive: true });

    panel.addEventListener("touchmove", (e) => {
      if (!pulling) return;
      const dy = e.touches[0].clientY - startY;
      if (dy > 10) {
        indicator.classList.add("pulling");
        textEl.textContent = dy > threshold ? "Release to refresh" : "Pull to refresh";
      }
    }, { passive: true });

    panel.addEventListener("touchend", async (e) => {
      if (!pulling) return;
      const dy = (e.changedTouches[0] || {}).clientY - startY;
      pulling = false;
      if (dy > threshold) {
        indicator.classList.remove("pulling");
        indicator.classList.add("refreshing");
        textEl.innerHTML = '<span class="ptr-spinner"></span> Refreshing...';
        try {
          const res = await fetch("/api/refresh", { method: "POST" });
          if (res.ok) {
            textEl.innerHTML = '<span class="ptr-spinner"></span> Loading...';
            setTimeout(() => location.reload(), 1500);
            return;
          }
        } catch (_) {}
        textEl.textContent = "Refresh failed";
        setTimeout(() => {
          indicator.classList.remove("refreshing");
        }, 2000);
      } else {
        indicator.classList.remove("pulling");
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

  document.querySelectorAll(".tag[style]").forEach((tag) => {
    const feedColor = tag.style.getPropertyValue("--feed-color").trim();
    const color = feedColor || _feedColor(tag.textContent.trim());
    if (color) {
      tag.style.setProperty("--feed-color", color);
      tag.style.background = color + "22";
      tag.style.color = color;
      tag.style.borderColor = color + "55";
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

  function stripTags(s) {
    const tmp = document.createElement("div");
    tmp.innerHTML = s;
    return tmp.textContent || tmp.innerText || "";
  }

  // ── Live search ──────────────────────────────────────────────────
  const searchInput    = document.getElementById("search-input");
  const searchDropdown = document.getElementById("search-dropdown");
  let _searchTimer     = null;
  let _lastQuery       = "";

  searchInput.addEventListener("input", () => {
    clearTimeout(_searchTimer);
    const q = searchInput.value.trim();
    if (!q) { _closeDropdown(); return; }
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
  });

  function _closeDropdown() {
    searchDropdown.style.display = "none";
  }

  async function _doLiveSearch(q) {
    _lastQuery = q;
    try {
      const res = await fetch("/api/search?q=" + encodeURIComponent(q) + "&limit=8");
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
      a.href = e.link || "#";
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
