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

    const theme = localStorage.getItem("theme") || "system";

    const payload = {
      retention_days: String(days),
      theme,
    };

    const ollamaUrl = document.getElementById("ollama_url");
    if (ollamaUrl) payload.ollama_url = ollamaUrl.value.trim() || "http://localhost:11434";

    const ollamaModel = document.getElementById("ollama_model");
    if (ollamaModel) payload.ollama_model = ollamaModel.value.trim() || "phi3:mini";

    const digestMax = document.getElementById("digest_max_articles");
    if (digestMax) {
      const n = parseInt(digestMax.value, 10);
      payload.digest_max_articles = String(isNaN(n) ? 50 : Math.max(10, Math.min(500, n)));
    }

    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
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
