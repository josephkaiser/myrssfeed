  // ── Hamburger menu ──────────────────────────────────────────────
  const hamburgerBtn  = document.getElementById("hamburger-btn");
  const hamburgerMenu = document.getElementById("hamburger-menu");

  function toggleMenu() {
    const open = hamburgerMenu.classList.toggle("open");
    hamburgerBtn.setAttribute("aria-expanded", open);
  }

  document.addEventListener("click", (e) => {
    if (!hamburgerBtn.contains(e.target) && !hamburgerMenu.contains(e.target)) {
      hamburgerMenu.classList.remove("open");
      hamburgerBtn.setAttribute("aria-expanded", "false");
    }
  });

  function openMyFeeds(e) {
    e.preventDefault();
    hamburgerMenu.classList.remove("open");
    hamburgerBtn.setAttribute("aria-expanded", "false");
    document.getElementById("sidebar").classList.toggle("open");
  }

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

  // Apply colors to all feed tags on load
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

  // ── Read / Like ──────────────────────────────────────────────────
  function markRead(entryId, linkEl) {
    const card = linkEl.closest(".entry-card");
    if (card && !card.classList.contains("read")) {
      card.classList.add("read");
      fetch(`/api/entries/${entryId}/read`, { method: "POST" }).catch(() => {});
    }
  }

  async function toggleLike(e, entryId, btn) {
    e.preventDefault();
    e.stopPropagation();
    const res = await fetch(`/api/entries/${entryId}/like`, { method: "POST" });
    if (res.ok) {
      const data = await res.json();
      btn.classList.toggle("liked", data.liked);
    }
  }

  // ── Feed actions ────────────────────────────────────────────────
  async function addFeed(e) {
    e.preventDefault();
    const url   = document.getElementById("new-url").value.trim();
    const title = document.getElementById("new-title").value.trim();
    const res = await fetch("/api/feeds", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, title: title || null }),
    });
    if (res.ok) {
      toast("Feed added — refresh to load articles.");
      setTimeout(() => location.reload(), 1200);
    } else {
      const data = await res.json().catch(() => ({}));
      toast(data.detail || "Could not add feed.", false);
    }
  }

  async function deleteFeed(e, id) {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm("Remove this feed and all its articles?")) return;
    const res = await fetch(`/api/feeds/${id}`, { method: "DELETE" });
    if (res.ok) {
      toast("Feed removed.");
      setTimeout(() => location.reload(), 900);
    } else {
      toast("Could not remove feed.", false);
    }
  }

  async function refreshFeeds() {
    toast("Fetching feeds…");
    const res = await fetch("/api/refresh", { method: "POST" });
    if (res.ok) {
      toast("Done! Reloading…");
      setTimeout(() => location.reload(), 1200);
    } else {
      toast("Refresh failed.", false);
    }
  }

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

  // Close dropdown when clicking outside
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
      // Ignore stale responses
      if (q !== searchInput.value.trim()) return;
      const data = await res.json();
      _renderDropdown(q, data);
    } catch (_) { /* silent — live search is best-effort */ }
  }

  function _renderDropdown(q, { suggestions, entries }) {
    if (!suggestions.length && !entries.length) {
      searchDropdown.innerHTML = '<div class="search-no-results">No results for "' + escHtml(q) + '"</div>';
      searchDropdown.style.display = "";
      return;
    }

    const frag = document.createDocumentFragment();

    // Word-completion chips
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

    // Matching article rows
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
