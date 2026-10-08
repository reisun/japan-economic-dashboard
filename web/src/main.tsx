import { loadRuntimeConfig } from "./runtime-config";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/index.css";

async function start(): Promise<void> {
  const root = document.getElementById("root")!;
  try {
    await loadRuntimeConfig();
    ReactDOM.createRoot(root).render(
      <React.StrictMode>
        <App />
      </React.StrictMode>
    );
  } catch (error) {
    root.setAttribute("role", "alert");
    root.textContent = `API 設定を読み込めません。${error instanceof Error ? error.message : String(error)}。Tunnel 起動・Pages 再デプロイ後に再読み込みしてください。`;
  }
}
void start();
