import { useState, useEffect } from "react";
import type { ApiState } from "../types/api";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "/api/v1";

function buildUrl(path: string): string {
  // If the base URL already contains /api/v1, use it directly
  // Otherwise, treat it as a proxy path
  const base = API_BASE_URL.endsWith("/")
    ? API_BASE_URL.slice(0, -1)
    : API_BASE_URL;
  return `${base}${path}`;
}

export function useApi<T>(path: string): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    const controller = new AbortController();

    async function fetchData() {
      setState({ data: null, loading: true, error: null });
      try {
        const url = buildUrl(path);
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data: T = await response.json();
        setState({ data, loading: false, error: null });
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        const message =
          err instanceof Error ? err.message : "データの取得に失敗しました";
        setState({ data: null, loading: false, error: message });
      }
    }

    fetchData();

    return () => {
      controller.abort();
    };
  }, [path]);

  return state;
}
