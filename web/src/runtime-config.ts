let apiBaseUrl = "";

export async function loadRuntimeConfig(): Promise<void> {
  if (import.meta.env.DEV) {
    apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8001/api/v1").replace(/\/$/, "");
    return;
  }
  const response = await fetch(`${import.meta.env.BASE_URL}config.json`, { cache: "no-store" });
  if (!response.ok) throw new Error(`config.json を取得できません (HTTP ${response.status})`);
  const config: unknown = await response.json();
  const value = typeof config === "object" && config !== null && "apiBaseUrl" in config
    ? (config as { apiBaseUrl: unknown }).apiBaseUrl : undefined;
  if (typeof value !== "string" || !value.trim()) throw new Error("config.json の apiBaseUrl が未設定です");
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash) {
    throw new Error("config.json の apiBaseUrl は HTTPS の API URL が必要です");
  }
  apiBaseUrl = value.trim().replace(/\/$/, "");
}

export function getApiBaseUrl(): string {
  if (!apiBaseUrl) throw new Error("API 設定の読み込みが完了していません");
  return apiBaseUrl;
}
