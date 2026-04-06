type SettingsTheme = "dark" | "light" | "system";

interface Window {
  setTheme: (theme: SettingsTheme) => void;
  saveSettings: () => Promise<void>;
  refreshNow: () => Promise<void>;
  newsletterSyncNow: () => Promise<void>;
  wordrankNow: () => Promise<void>;
}
