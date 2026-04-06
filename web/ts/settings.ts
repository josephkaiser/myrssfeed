type Theme = "dark" | "light" | "system";
type StatusKind = "disabled" | "error" | "never" | "running" | "success";

interface SaveSettingsPayload {
  retention_days: string;
  theme: Theme;
  max_entries: string;
  pipeline_refresh_minutes: string;
  newsletter_enabled: string;
  newsletter_imap_host: string;
  newsletter_imap_port: string;
  newsletter_imap_username: string;
  newsletter_imap_password: string;
  newsletter_imap_folder: string;
  newsletter_poll_minutes: string;
}

interface JsonResponse {
  detail?: string;
  last_error?: string;
  last_status?: string;
  message?: string;
  minutes_since_last_success?: number;
  running?: boolean;
  status?: string;
}

interface StatusState {
  running?: boolean;
  last_status?: StatusKind;
  minutes_since_last_success?: number | null;
  last_error?: string;
}

function getElement<T extends HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

function requireInput(id: string): HTMLInputElement {
  const element = getElement<HTMLInputElement>(id);
  if (!element) {
    throw new Error(`Missing required input #${id}`);
  }
  return element;
}

function requireSelect(id: string): HTMLSelectElement {
  const element = getElement<HTMLSelectElement>(id);
  if (!element) {
    throw new Error(`Missing required select #${id}`);
  }
  return element;
}

function clampInt(rawValue: string | null | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number.parseInt(rawValue ?? "", 10);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, parsed));
}

function readStoredTheme(): Theme {
  const stored = localStorage.getItem("theme");
  return stored === "dark" || stored === "light" || stored === "system" ? stored : "system";
}

function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "light") {
    root.setAttribute("data-theme", "light");
  } else if (theme === "dark") {
    root.setAttribute("data-theme", "dark");
  } else {
    root.removeAttribute("data-theme");
  }
}

function refreshToggleUI(theme: Theme): void {
  document.querySelectorAll<HTMLButtonElement>("#theme-toggle button").forEach((button) => {
    button.classList.toggle("active", button.dataset.themeVal === theme);
  });
}

function setTheme(theme: Theme): void {
  localStorage.setItem("theme", theme);
  applyTheme(theme);
  refreshToggleUI(theme);
}

(function initThemeToggle(): void {
  refreshToggleUI(readStoredTheme());
})();

function getFilterAggressiveness(): number {
  return clampInt(localStorage.getItem("filter_aggressiveness"), 1, 0, 3);
}

function describeAggressiveness(level: number): string {
  switch (level) {
    case 0:
      return "Very gentle";
    case 1:
      return "Balanced";
    case 2:
      return "Firm";
    case 3:
      return "Aggressive";
    default:
      return "Balanced";
  }
}

(function initFilterAggressiveness(): void {
  const slider = getElement<HTMLInputElement>("filter_aggressiveness");
  const label = getElement<HTMLElement>("filter_aggressiveness_label");
  if (!slider || !label) {
    return;
  }

  const level = getFilterAggressiveness();
  slider.value = String(level);
  label.textContent = describeAggressiveness(level);

  slider.addEventListener("input", () => {
    const nextLevel = clampInt(slider.value, 1, 0, 3);
    localStorage.setItem("filter_aggressiveness", String(nextLevel));
    label.textContent = describeAggressiveness(nextLevel);
  });
})();

function toast(message: string, ok = true): void {
  const element = getElement<HTMLElement>("toast");
  if (!element) {
    return;
  }

  element.textContent = message;
  element.style.borderColor = ok ? "var(--accent)" : "var(--danger)";
  element.classList.add("show");
  window.setTimeout(() => {
    element.classList.remove("show");
  }, 2800);
}

function getPipelineRefreshMinutes(): number {
  const input = getElement<HTMLInputElement>("pipeline_refresh_minutes");
  return clampInt(input?.value, 15, 5, 240);
}

function describePipelineRefreshMinutes(minutes: number): string {
  const value = Math.min(240, Math.max(5, minutes));
  return `${value} min`;
}

function updatePipelineRefreshDial(): void {
  const input = getElement<HTMLInputElement>("pipeline_refresh_minutes");
  const label = getElement<HTMLElement>("pipeline_refresh_minutes_value");
  if (!input || !label) {
    return;
  }

  const minutes = getPipelineRefreshMinutes();
  input.value = String(minutes);
  label.textContent = describePipelineRefreshMinutes(minutes);
}

async function readJson(response: Response): Promise<JsonResponse> {
  return (await response.json().catch(() => ({}))) as JsonResponse;
}

async function saveSettings(): Promise<void> {
  const retentionInput = requireInput("retention_days");
  const days = Number.parseInt(retentionInput.value, 10);

  if (Number.isNaN(days) || days < 0 || days > 3650) {
    toast("Retention must be 0–3650 days.", false);
    retentionInput.focus();
    return;
  }

  const maxEntriesInput = requireInput("max_entries");
  const maxEntriesValue = Number.parseInt(maxEntriesInput.value, 10);
  if (Number.isNaN(maxEntriesValue) || maxEntriesValue < 50 || maxEntriesValue > 20000) {
    toast("Maximum articles must be between 50 and 20000.", false);
    maxEntriesInput.focus();
    return;
  }

  const newsletterEnabledSelect = requireSelect("newsletter_enabled");
  const newsletterHostInput = requireInput("newsletter_imap_host");
  const newsletterPortInput = requireInput("newsletter_imap_port");
  const newsletterUserInput = requireInput("newsletter_imap_username");
  const newsletterPassInput = requireInput("newsletter_imap_password");
  const newsletterFolderInput = requireInput("newsletter_imap_folder");
  const newsletterPollInput = requireInput("newsletter_poll_minutes");

  const newsletterPortValue = Number.parseInt(newsletterPortInput.value, 10);
  if (Number.isNaN(newsletterPortValue) || newsletterPortValue < 1 || newsletterPortValue > 65535) {
    toast("Newsletter IMAP port must be between 1 and 65535.", false);
    newsletterPortInput.focus();
    return;
  }

  const newsletterPollValue = Number.parseInt(newsletterPollInput.value, 10);
  if (Number.isNaN(newsletterPollValue) || newsletterPollValue < 5 || newsletterPollValue > 1440) {
    toast("Newsletter poll interval must be between 5 and 1440 minutes.", false);
    newsletterPollInput.focus();
    return;
  }

  if (maxEntriesValue > 5000) {
    toast(
      "Large article lists may be slow on lower-end devices. Make sure this machine has enough disk space and a fast drive.",
      true,
    );
  }

  const payload: SaveSettingsPayload = {
    retention_days: String(days),
    theme: readStoredTheme(),
    max_entries: String(maxEntriesValue),
    pipeline_refresh_minutes: String(getPipelineRefreshMinutes()),
    newsletter_enabled: newsletterEnabledSelect.value,
    newsletter_imap_host: newsletterHostInput.value.trim(),
    newsletter_imap_port: String(newsletterPortValue),
    newsletter_imap_username: newsletterUserInput.value.trim(),
    newsletter_imap_password: newsletterPassInput.value,
    newsletter_imap_folder: newsletterFolderInput.value.trim() || "INBOX",
    newsletter_poll_minutes: String(newsletterPollValue),
  };

  const response = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (response.ok) {
    const statusElement = getElement<HTMLElement>("save-status");
    if (statusElement) {
      statusElement.classList.add("show");
      window.setTimeout(() => {
        statusElement.classList.remove("show");
      }, 2500);
    }
    window.setTimeout(() => {
      void fetchNewsletterStatus();
    }, 1000);
    return;
  }

  const data = await readJson(response);
  toast(data.detail || "Could not save settings.", false);
}

function updateRefreshStatusUI(state: StatusState): void {
  const dot = getElement<HTMLElement>("refresh-status-dot");
  const text = getElement<HTMLElement>("refresh-status-text");
  if (!dot || !text) {
    return;
  }

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
        const minutes = state.minutes_since_last_success;
        text.textContent = minutes === 0 ? "Now" : `${minutes}m ago`;
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

async function fetchRefreshStatus(): Promise<void> {
  try {
    const response = await fetch("/api/refresh/status");
    if (!response.ok) {
      return;
    }

    const data = await readJson(response);
    const state: StatusState = {
      running: Boolean(data.running),
      last_status: (data.last_status as StatusKind | undefined) || "never",
      minutes_since_last_success:
        typeof data.minutes_since_last_success === "number" ? data.minutes_since_last_success : null,
    };
    updateRefreshStatusUI(state);
    updatePipelineStatusUI(state);
  } catch {
    // Silently ignore; status light is best-effort only.
  }
}

function updateNewsletterStatusUI(state: StatusState): void {
  const dot = getElement<HTMLElement>("newsletter-status-dot");
  const text = getElement<HTMLElement>("newsletter-status-text");
  if (!dot || !text) {
    return;
  }

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
        const minutes = state.minutes_since_last_success;
        text.textContent = minutes === 0 ? "Just now" : `${minutes} min ago`;
      } else {
        text.textContent = "Last sync completed";
      }
      break;
    case "error":
      dot.classList.add("error");
      text.textContent = "Last sync failed";
      if (state.last_error) {
        text.title = state.last_error;
      }
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

async function fetchNewsletterStatus(): Promise<void> {
  try {
    const response = await fetch("/api/newsletters/status");
    if (!response.ok) {
      return;
    }

    const data = await readJson(response);
    updateNewsletterStatusUI({
      running: Boolean(data.running),
      last_status: (data.last_status as StatusKind | undefined) || "never",
      minutes_since_last_success:
        typeof data.minutes_since_last_success === "number" ? data.minutes_since_last_success : null,
      last_error: data.last_error || "",
    });
  } catch {
    // Best-effort only.
  }
}

async function refreshNow(): Promise<void> {
  const button = getElement<HTMLButtonElement>("refresh-now-btn");
  if (!button) {
    return;
  }

  button.disabled = true;
  const originalText = button.textContent;
  button.textContent = "Refreshing...";

  try {
    const response = await fetch("/api/refresh", { method: "POST" });
    const data = await readJson(response);
    if (response.ok) {
      toast(data.message || "Refresh started.");
      updateRefreshStatusUI({ running: true, last_status: "running" });
    } else {
      toast(data.detail || "Could not start refresh.", false);
    }
  } catch {
    toast("Network error starting refresh.", false);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
    window.setTimeout(() => {
      void fetchRefreshStatus();
    }, 2000);
  }
}

(function initStatusPolling(): void {
  if (getElement("refresh-status-dot")) {
    void fetchRefreshStatus();
    window.setInterval(() => {
      void fetchRefreshStatus();
    }, 8000);
  }

  if (getElement("newsletter-status-dot")) {
    void fetchNewsletterStatus();
    window.setInterval(() => {
      void fetchNewsletterStatus();
    }, 8000);
  }
})();

async function newsletterSyncNow(): Promise<void> {
  const button = getElement<HTMLButtonElement>("newsletter-sync-btn");
  if (!button) {
    return;
  }

  button.disabled = true;
  const originalText = button.textContent;
  button.textContent = "Syncing...";

  try {
    const response = await fetch("/api/newsletters/sync", { method: "POST" });
    const data = await readJson(response);
    if (response.ok) {
      toast(data.message || "Newsletter sync started.");
      updateNewsletterStatusUI({ running: true, last_status: "running" });
    } else {
      toast(data.detail || "Could not start newsletter sync.", false);
    }
  } catch {
    toast("Network error starting newsletter sync.", false);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
    window.setTimeout(() => {
      void fetchNewsletterStatus();
    }, 2000);
  }
}

function updatePipelineStatusUI(state: StatusState): void {
  const dot = getElement<HTMLElement>("pipeline-status-dot");
  const text = getElement<HTMLElement>("pipeline-status-text");
  if (!dot || !text) {
    return;
  }

  dot.className = "refresh-status-dot";

  switch (state.last_status) {
    case "success":
      dot.classList.add("success");
      if (typeof state.minutes_since_last_success === "number") {
        const minutes = state.minutes_since_last_success;
        text.textContent = minutes === 0 ? "Now" : `${minutes}m ago`;
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

function updateWordrankStatusUI(state: StatusState): void {
  const dot = getElement<HTMLElement>("wordrank-status-dot");
  const text = getElement<HTMLElement>("wordrank-status-text");
  if (!dot || !text) {
    return;
  }

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
        const minutes = state.minutes_since_last_success;
        text.textContent = minutes === 0 ? "Now" : `${minutes}m ago`;
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

async function fetchWordrankStatus(): Promise<void> {
  try {
    const response = await fetch("/api/wordrank/status");
    if (!response.ok) {
      return;
    }

    const data = await readJson(response);
    updateWordrankStatusUI({
      running: false,
      last_status: (data.last_status as StatusKind | undefined) || "never",
    });
  } catch {
    // best-effort only
  }
}

async function wordrankNow(): Promise<void> {
  const button = getElement<HTMLButtonElement>("wordrank-now-btn");
  if (!button) {
    return;
  }

  button.disabled = true;
  const originalText = button.textContent;
  button.textContent = "Running...";
  updateWordrankStatusUI({ running: true, last_status: "running" });

  try {
    const response = await fetch("/api/wordrank", { method: "POST" });
    const data = await readJson(response);
    if (response.ok && data.status === "success") {
      toast(data.message || "WordRank completed.");
      updateWordrankStatusUI({ running: false, last_status: "success" });
    } else {
      toast(data.message || data.detail || "WordRank failed.", false);
      updateWordrankStatusUI({ running: false, last_status: "error" });
    }
  } catch {
    toast("Network error running WordRank.", false);
    updateWordrankStatusUI({ running: false, last_status: "error" });
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

(function initPipelineControls(): void {
  const refreshInput = getElement<HTMLInputElement>("pipeline_refresh_minutes");
  if (refreshInput) {
    refreshInput.addEventListener("input", updatePipelineRefreshDial);
    updatePipelineRefreshDial();
  }

  if (getElement("wordrank-status-dot")) {
    void fetchWordrankStatus();
  }
})();

window.setTheme = setTheme;
window.saveSettings = saveSettings;
window.refreshNow = refreshNow;
window.newsletterSyncNow = newsletterSyncNow;
window.wordrankNow = wordrankNow;
