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

  // ── Panel helpers ────────────────────────────────────────────────
  const entriesPanel = document.getElementById("entries-panel");
  const topicsPanel  = document.getElementById("topics-panel");
  const digestPanel  = document.getElementById("digest-panel");
  const topicsTabBtn = document.getElementById("topics-tab-btn");
  const digestTabBtn = document.getElementById("digest-tab-btn");

  function _hideAllPanels() {
    entriesPanel.style.display = "none";
    topicsPanel.style.display  = "none";
    digestPanel.style.display  = "none";
    topicsTabBtn.classList.remove("active");
    digestTabBtn.classList.remove("active");
    document.getElementById("all-articles-link").classList.remove("active");
    hamburgerMenu.classList.remove("open");
    document.getElementById("sidebar").classList.remove("open");
  }

  // ── Topics view ─────────────────────────────────────────────────
  function openTopics() {
    _hideAllPanels();
    topicsPanel.style.display = "";
    topicsTabBtn.classList.add("active");
    loadTopicsGrid();
  }

  function closeTopics() {
    topicsPanel.style.display  = "none";
    entriesPanel.style.display = "";
    topicsTabBtn.classList.remove("active");
  }

  function showTopicsGrid() {
    document.getElementById("topics-grid-view").style.display   = "";
    document.getElementById("topics-detail-view").style.display = "none";
  }

  async function loadTopicsGrid() {
    const gridView    = document.getElementById("topics-grid-view");
    const detailView  = document.getElementById("topics-detail-view");
    gridView.style.display   = "";
    detailView.style.display = "none";

    const content = document.getElementById("topics-grid-content");
    content.innerHTML = '<div class="topics-empty"><div style="font-size:2rem">⏳</div><p>Loading topics…</p></div>';
    document.getElementById("topics-header-text").textContent = "Topics";

    let topics;
    try {
      const res = await fetch("/api/topics");
      if (!res.ok) throw new Error("HTTP " + res.status);
      topics = await res.json();
    } catch (err) {
      content.innerHTML = '<div class="topics-empty"><div style="font-size:2rem">⚠️</div><p>Could not load topics. Run a re-cluster first.</p></div>';
      return;
    }

    if (!topics.length) {
      // Check if a clustering job is currently running before giving up
      let jobStatus = null;
      try {
        const jr = await fetch("/api/recluster/status");
        if (jr.ok) jobStatus = await jr.json();
      } catch (_) {}

      if (jobStatus && jobStatus.status === "running") {
        const pct  = jobStatus.progress || 0;
        const step = jobStatus.step || "Working…";
        content.innerHTML =
          '<div class="topics-empty">' +
            '<div class="spinner" style="width:2rem;height:2rem;border-width:3px;margin:0 auto 0.75rem;"></div>' +
            '<p>Clustering in progress…</p>' +
            '<p style="margin-top:0.4rem;font-size:0.82rem;color:var(--muted);">' + escHtml(step) + ' · ' + pct + '%</p>' +
          '</div>';
        // Re-check every 2 s until done
        setTimeout(loadTopicsGrid, 2000);
      } else {
        content.innerHTML = '<div class="topics-empty"><div style="font-size:2rem">🗂</div><p>No topics yet. Use <strong>Re-cluster topics</strong> in Settings after refreshing feeds.</p></div>';
      }
      return;
    }

    document.getElementById("topics-header-text").textContent = topics.length + " topic" + (topics.length !== 1 ? "s" : "");

    const grid = document.createElement("div");
    grid.className = "topics-grid";

    topics.forEach((t) => {
      const card = document.createElement("div");
      card.className = "topic-card";
      card.innerHTML =
        '<div class="topic-card-label">' + escHtml(t.label || "Untitled") + '</div>' +
        '<div class="topic-card-count"><strong>' + t.article_count + '</strong> article' + (t.article_count !== 1 ? "s" : "") + '</div>';
      card.addEventListener("click", () => openTopicDetail(t));
      grid.appendChild(card);
    });

    content.innerHTML = "";
    content.appendChild(grid);
  }

  async function openTopicDetail(topic) {
    document.getElementById("topics-grid-view").style.display   = "none";
    const detailView = document.getElementById("topics-detail-view");
    detailView.style.display = "";
    document.getElementById("topics-detail-label").textContent  = topic.label || "Untitled";

    const content = document.getElementById("topics-detail-content");
    content.innerHTML = '<div class="topics-empty"><div style="font-size:2rem">⏳</div><p>Loading articles…</p></div>';

    let entries;
    try {
      const res = await fetch("/api/topics/" + topic.id + "/entries?limit=100");
      if (!res.ok) throw new Error("HTTP " + res.status);
      entries = await res.json();
    } catch (err) {
      content.innerHTML = '<div class="topics-empty"><p>Could not load articles.</p></div>';
      return;
    }

    if (!entries.length) {
      content.innerHTML = '<div class="topics-empty"><p>No articles in this topic.</p></div>';
      return;
    }

    const frag = document.createDocumentFragment();
    entries.forEach((e) => {
      const art = document.createElement("article");
      art.className = "entry-card";
      const date = e.published ? e.published.slice(0, 10) : "";
      art.innerHTML =
        '<div class="entry-meta">' +
          '<span class="tag">' + escHtml(e.feed_title || "Unknown") + '</span>' +
          (date ? '<span class="entry-date">' + date + '</span>' : '') +
        '</div>' +
        '<div class="entry-title"><a href="' + escHtml(e.link || "#") + '" target="_blank" rel="noopener noreferrer">' +
          escHtml(e.title || "(no title)") +
        '</a></div>' +
        (e.summary ? '<div class="entry-summary">' + escHtml(stripTags(e.summary)) + '</div>' : '');
      frag.appendChild(art);
    });
    content.innerHTML = "";
    content.appendChild(frag);
  }

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

  // ── Digest view ──────────────────────────────────────────────────
  let _currentDigestDate = null;

  function openDigest() {
    _hideAllPanels();
    digestPanel.style.display = "";
    digestTabBtn.classList.add("active");
    loadDigest();
  }

  async function loadDigest() {
    const content   = document.getElementById("digest-content");
    const dateLabel = document.getElementById("digest-date-label");
    const aiSlot    = document.getElementById("ai-summary-slot");

    content.innerHTML = '<div class="digest-empty"><div style="font-size:2rem">⏳</div><p>Building digest…</p></div>';
    aiSlot.innerHTML  = "";
    dateLabel.textContent = "";
    _currentDigestDate = null;

    let data;
    try {
      const res = await fetch("/api/digest");
      if (!res.ok) throw new Error("HTTP " + res.status);
      data = await res.json();
    } catch (err) {
      content.innerHTML = '<div class="digest-empty"><div style="font-size:2rem">⚠️</div><p>Could not load digest. Run a re-cluster first.</p></div>';
      return;
    }

    _currentDigestDate = data.date || null;
    dateLabel.textContent = data.date || "";
    document.getElementById("digest-header-text").textContent = "Today's Digest";

    if (!data.bullets || !data.bullets.length) {
      content.innerHTML = '<div class="digest-empty"><div style="font-size:2rem">📋</div><p>No articles published today yet.</p></div>';
      return;
    }

    // Render cluster-top-entry bullets
    const frag = document.createDocumentFragment();
    data.bullets.forEach((b) => {
      const div = document.createElement("div");
      div.className = "digest-bullet";
      const date = b.published ? b.published.slice(0, 10) : "";
      const extraBadge = b.extra_count > 0
        ? '<span class="digest-more">+' + b.extra_count + ' more</span>'
        : "";
      div.innerHTML =
        '<div class="digest-bullet-dot"></div>' +
        '<div class="digest-bullet-body">' +
          '<div class="digest-bullet-label">' + escHtml(b.label || "Topic") + '</div>' +
          '<a class="digest-bullet-headline" href="' + escHtml(b.link || "#") +
            '" target="_blank" rel="noopener noreferrer">' +
            escHtml(b.headline) +
          '</a>' +
          '<div class="digest-bullet-meta">' +
            (b.feed_title ? '<span>' + escHtml(b.feed_title) + '</span>' : '') +
            (date ? '<span>' + date + '</span>' : '') +
            extraBadge +
          '</div>' +
        '</div>';
      frag.appendChild(div);
    });
    content.innerHTML = "";
    content.appendChild(frag);

    // Try to load a cached AI summary; if none, show the Generate button
    loadAiSummary(false);
  }

  async function loadAiSummary(forceGenerate) {
    const slot = document.getElementById("ai-summary-slot");
    if (!_currentDigestDate) return;

    if (forceGenerate) {
      // Show spinner while waiting
      slot.innerHTML =
        '<div class="ai-summary-generate">' +
          '<div id="ai-generating-indicator">' +
            '<div class="spinner"></div>' +
            '<span>Generating AI summary with ollama… (may take ~30–90 s on a Pi)</span>' +
          '</div>' +
        '</div>';

      // Delete any stale cache first so we always get a fresh run
      await fetch("/api/digest/llm?date=" + encodeURIComponent(_currentDigestDate), { method: "DELETE" });
    }

    const method = forceGenerate ? "POST" : "POST"; // POST returns cached if available
    let data;
    try {
      const qs  = "?date=" + encodeURIComponent(_currentDigestDate);
      const res = await fetch("/api/digest/llm" + qs, { method: "POST" });
      if (res.status === 404 || res.status === 503) {
        // No clustered data yet or ollama not running — show the prompt button
        const err = await res.json().catch(() => ({}));
        _renderAiGenerateButton(err.detail || "ollama not reachable or no data for today.");
        return;
      }
      if (!res.ok) throw new Error("HTTP " + res.status);
      data = await res.json();
    } catch (err) {
      _renderAiGenerateButton("Could not reach the AI service.");
      return;
    }

    _renderAiSummary(data);
  }

  function _renderAiSummary(data) {
    const slot = document.getElementById("ai-summary-slot");
    const cachedNote = data.cached ? " · cached" : "";
    slot.innerHTML =
      '<div class="ai-summary-card">' +
        '<div class="ai-summary-header">' +
          '<span class="ai-summary-title">✨ AI Summary</span>' +
          '<span class="ai-summary-meta">' + escHtml(data.model || "") + cachedNote +
            ' · <a href="#" onclick="regenerateAiSummary(event)" style="color:var(--muted);font-size:0.72rem;">regenerate</a>' +
          '</span>' +
        '</div>' +
        '<div class="ai-summary-body">' + escHtml(data.summary || "") + '</div>' +
      '</div>';
  }

  function _renderAiGenerateButton(hint) {
    const slot = document.getElementById("ai-summary-slot");
    slot.innerHTML =
      '<div class="ai-summary-generate">' +
        '<p>✨ <strong>AI Digest</strong> — summarise today\'s stories with your local ollama model.' +
          (hint ? ' <em style="color:var(--muted);">' + escHtml(hint) + '</em>' : '') +
        '</p>' +
        '<button class="btn ghost" onclick="generateAiSummary()" style="flex-shrink:0;">Generate</button>' +
      '</div>';
  }

  function generateAiSummary() {
    loadAiSummary(true);
  }

  async function regenerateAiSummary(e) {
    e.preventDefault();
    if (!confirm("Regenerate the AI summary? This will call ollama again and may take a minute.")) return;
    loadAiSummary(true);
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
