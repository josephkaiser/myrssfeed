  // ── Hamburger ───────────────────────────────────────────────────
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

  // ── Toast ───────────────────────────────────────────────────────
  function toast(msg, ok = true) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.style.borderColor = ok ? "var(--accent)" : "var(--danger)";
    el.classList.add("show");
    setTimeout(() => el.classList.remove("show"), 2800);
  }

  // ── Save settings ───────────────────────────────────────────────
  async function saveSettings() {
    const retentionInput = document.getElementById("retention_days");
    const days = parseInt(retentionInput.value, 10);

    if (isNaN(days) || days < 0 || days > 3650) {
      toast("Retention must be 0–3650 days.", false);
      retentionInput.focus();
      return;
    }

    const clustersInput = document.getElementById("num_topic_clusters");
    const clusters = parseInt(clustersInput.value, 10);

    if (isNaN(clusters) || clusters < 2 || clusters > 100) {
      toast("Topic clusters must be 2–100.", false);
      clustersInput.focus();
      return;
    }

    const theme = localStorage.getItem("theme") || "system";

    const ollamaUrl   = document.getElementById("ollama_url").value.trim();
    const ollamaModel = document.getElementById("ollama_model").value.trim();

    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        retention_days: String(days),
        num_topic_clusters: String(clusters),
        theme,
        ollama_url:   ollamaUrl   || "http://localhost:11434",
        ollama_model: ollamaModel || "llama3.2:1b",
      }),
    });

    if (res.ok) {
      const statusEl = document.getElementById("save-status");
      statusEl.classList.add("show");
      setTimeout(() => statusEl.classList.remove("show"), 2500);
    } else {
      const data = await res.json().catch(() => ({}));
      toast(data.detail || "Could not save settings.", false);
    }
  }

  // ── Re-cluster with progress polling ────────────────────────────
  let _reclusterPollTimer = null;
  let _reclusterActive = false;

  function _setProgress(pct, step) {
    const wrap = document.getElementById("recluster-progress-wrap");
    const bar  = document.getElementById("recluster-bar");
    const pctLbl  = document.getElementById("recluster-pct-label");
    const stepLbl = document.getElementById("recluster-step-label");
    wrap.style.display = "";
    bar.style.width    = pct + "%";
    pctLbl.textContent = pct + "%";
    stepLbl.textContent = step || "—";
  }

  function _hideProgress() {
    document.getElementById("recluster-progress-wrap").style.display = "none";
    document.getElementById("recluster-bar").style.width = "0%";
  }

  function _resetBtn() {
    const btn = document.getElementById("recluster-btn");
    btn.disabled = false;
    btn.textContent = "Re-cluster topics";
  }

  async function _pollStatus() {
    try {
      const res  = await fetch("/api/recluster/status");
      if (!res.ok) {
        if (_reclusterActive) _reclusterPollTimer = setTimeout(_pollStatus, 2000);
        return;
      }
      const data = await res.json();

      if (data.status === "none" || !data.status) {
        if (_reclusterActive) _reclusterPollTimer = setTimeout(_pollStatus, 2000);
        return;
      }

      _setProgress(data.progress || 0, data.step || "Working…");

      if (data.status === "running") {
        _reclusterPollTimer = setTimeout(_pollStatus, 1500);
        return;
      }

      // done or error — stop polling and restore UI
      _reclusterActive = false;
      _resetBtn();

      if (data.status === "done") {
        _setProgress(100, "Done");
        toast("Topics re-clustered successfully.");
        setTimeout(_hideProgress, 3000);
      } else {
        _hideProgress();
        const errMsg = data.error_log
          ? "Re-clustering failed: " + data.error_log.trim().split("\n").pop()
          : "Re-clustering failed.";
        toast(errMsg, false);
        console.error("Clustering error log:\n", data.error_log || "(none)");
      }
    } catch (_) {
      if (_reclusterActive) _reclusterPollTimer = setTimeout(_pollStatus, 2000);
    }
  }

  // ── ollama status check ─────────────────────────────────────────
  function _setOllamaStatusBadge(text, state) {
    const badge = document.getElementById("ollama-status-badge");
    badge.textContent = text;
    badge.className = "ollama-status-badge" + (state ? " " + state : "");
  }

  async function checkOllamaStatus() {
    const btn = document.getElementById("ollama-check-btn");
    btn.disabled = true;
    _setOllamaStatusBadge("Checking…", "");
    try {
      const res  = await fetch("/api/ollama/status");
      const data = await res.json();
      if (!data.reachable) {
        _setOllamaStatusBadge("Unreachable", "error");
        toast("ollama not reachable: " + (data.error || "unknown error"), false);
      } else if (!data.model_available) {
        _setOllamaStatusBadge("Model missing", "warn");
        toast(`ollama is up but "${data.model}" has not been pulled yet.`, false);
      } else {
        _setOllamaStatusBadge("Ready", "ok");
        toast(`ollama OK — "${data.model}" is available.`);
      }
    } catch (_) {
      _setOllamaStatusBadge("Error", "error");
      toast("Could not reach the server.", false);
    }
    btn.disabled = false;
  }

  // ── ollama model pull ────────────────────────────────────────────
  let _pullPollTimer = null;
  let _pullActive    = false;

  function _setPullProgress(pct, step) {
    const wrap    = document.getElementById("ollama-pull-progress-wrap");
    const bar     = document.getElementById("ollama-pull-bar");
    const pctLbl  = document.getElementById("ollama-pull-pct");
    const stepLbl = document.getElementById("ollama-pull-step");
    wrap.style.display  = "";
    bar.style.width     = pct + "%";
    pctLbl.textContent  = pct + "%";
    stepLbl.textContent = step || "—";
  }

  function _hidePullProgress() {
    document.getElementById("ollama-pull-progress-wrap").style.display = "none";
    document.getElementById("ollama-pull-bar").style.width = "0%";
  }

  function _resetPullBtn() {
    const btn = document.getElementById("ollama-pull-btn");
    btn.disabled    = false;
    btn.textContent = "Pull / Reset";
  }

  async function _pollPullStatus() {
    try {
      const res = await fetch("/api/ollama/pull/status");
      if (!res.ok) {
        if (_pullActive) _pullPollTimer = setTimeout(_pollPullStatus, 2000);
        return;
      }
      const data = await res.json();

      if (data.status === "idle") {
        if (_pullActive) _pullPollTimer = setTimeout(_pollPullStatus, 1000);
        return;
      }

      _setPullProgress(data.pct || 0, data.step || "Working…");

      if (data.status === "pulling") {
        _pullPollTimer = setTimeout(_pollPullStatus, 1000);
        return;
      }

      // done or error — stop polling
      _pullActive = false;
      _resetPullBtn();

      if (data.status === "done") {
        _setPullProgress(100, "Done");
        _setOllamaStatusBadge("Ready", "ok");
        toast("Model pulled successfully.");
        setTimeout(_hidePullProgress, 3000);
      } else {
        _hidePullProgress();
        _setOllamaStatusBadge("Pull failed", "error");
        toast("Model pull failed: " + (data.error || "unknown error"), false);
      }
    } catch (_) {
      if (_pullActive) _pullPollTimer = setTimeout(_pollPullStatus, 2000);
    }
  }

  async function pullModel() {
    const btn = document.getElementById("ollama-pull-btn");
    btn.disabled    = true;
    btn.textContent = "Pulling…";
    _setOllamaStatusBadge("Pulling…", "");
    _setPullProgress(0, "Starting…");

    let res;
    try {
      res = await fetch("/api/ollama/pull", { method: "POST" });
    } catch (_) {
      _resetPullBtn();
      _hidePullProgress();
      _setOllamaStatusBadge("Error", "error");
      toast("Could not start model pull.", false);
      return;
    }

    if (!res.ok) {
      _resetPullBtn();
      _hidePullProgress();
      const rawText = await res.text().catch(() => "");
      let msg = "Model pull failed to start.";
      try { msg = JSON.parse(rawText).detail || msg; } catch (_) {}
      _setOllamaStatusBadge("Error", "error");
      toast(msg, false);
      return;
    }

    _pullActive    = true;
    _pullPollTimer = setTimeout(_pollPullStatus, 800);
  }

  async function recluster() {
    const btn = document.getElementById("recluster-btn");
    btn.disabled = true;
    btn.textContent = "Clustering…";
    _setProgress(0, "Starting…");

    let res;
    try {
      res = await fetch("/api/recluster", { method: "POST" });
    } catch (networkErr) {
      _resetBtn();
      _hideProgress();
      toast("Could not start re-clustering.", false);
      console.error("Clustering fetch error:", networkErr);
      return;
    }

    if (!res.ok) {
      _resetBtn();
      _hideProgress();
      const rawText = await res.text().catch(() => "");
      let msg = "Re-clustering failed to start.";
      try { msg = JSON.parse(rawText).detail || msg; } catch (_) {}
      toast(msg, false);
      return;
    }

    // Server accepted (202) — the child process is now running.
    // Keep polling until it reports done or error.
    _reclusterActive = true;
    _reclusterPollTimer = setTimeout(_pollStatus, 800);
  }
