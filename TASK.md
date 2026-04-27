# TASK

## Done

- [x] Initial implementation (MVP)
  - [x] Backend: FastAPI + 4 API endpoints (gdp-gap, fund-demand, rates, prediction)
  - [x] Frontend: React + TypeScript + Vite + Recharts ダッシュボード
  - [x] Docker Compose 統合
  - [x] IS-LM予測モデル実装
  - [x] デプロイ・動作確認完了
- [x] GDPギャップ推計の4系統切替（内閣府公表 / 平均概念HP / 最大概念CBO生産関数 / 在野試算高橋方式）
- [x] 必要財政支出の符号付き化（プラスギャップ時は引き締め方向）
- [x] 「真の潜在GDP」モードの厳密化（CBO methodology）
- [x] 在野試算系統の高橋洋一氏方式アルゴリズム実装（ピーク・トゥ・ピーク線形トレンド）
- [x] CPI指標を世界標準のコアコア（生鮮食品・エネルギー除く）に変更
- [x] インフレ率パネル併置 + 「ギャップ × インフレ率」4象限マトリクス
- [x] PolicyMatrix の判定閾値を系統別に切替（最大概念は完全雇用基準ギャップ）
- [x] 全パネルの表示期間を GDPギャップ実績期間に統一
- [x] 実データ取得（内閣府GDP、日銀統計）のモックからの切り替え（GDPデフレータ・賃金・実質GDPを FRED 経由で実データ化、CPIコアコアは e-Stat 連携が TODO）
- [x] CPIコアコアの実データ取得（e-Stat API → 総務省統計局CSV → モック の三段フォールバック; ESTAT_APP_ID 設定で実データ反映）
- [x] BOJ 資金循環統計（flow of funds）の実データ取得（BOJ 時系列データ検索サイト ZIP → BOJ 公表ページ Excel(現在404) → e-Stat API → モック の四段フォールバック; A 経路で家計/非金融法人/一般政府の純貸出/純借入を実取得）
- [x] ユーザーが任意の財政支出額を入力してシナリオシミュレーション（API: `?fiscal_spending_trillion=` クエリ; UI: 数値入力＋スライダー＋「自動」ボタン, debounce 500ms; 静的モードでは disabled）
- [x] FRED API key 設定による実データ取得（README に Setup 手順を記載、`.env.example` に `FRED_API_KEY=` 確認、未設定時は起動時に 1 回だけ警告ログを出してモックフォールバック、`/api/v1/health/data-sources` で各シリーズの取得成否を確認可能）
- [x] VARなど統計的回帰モデルへの拡張（OLS-VAR と AR(1) ベンチマークを追加; `/api/v1/prediction?engine=is_lm|var|ar1` で切替、+1兆円財政ショックの IRF 返却、フロントに予測モデル切替セレクタ、静的JSON `prediction-<method>-<engine>.json` 対応）
- [x] Recharts chunk分割（vite `manualChunks` で recharts を独立 chunk 化、initial JS を 567kB→30kB に削減、ビルドサイズ警告解消; `chunkSizeWarningLimit: 700` で recharts 自体の警告を抑制）
- [x] reverse-proxy への統合（reverse-proxy 統合は完了済（`~/workspace/reverse-proxy/nginx/nginx.conf` に `/japan-economic-dashboard/api/` ルーティング、`japan-economic-dashboard-net` 経由で upstream `japan-economic-dashboard-api:8000` に到達）。外部 URL `https://reisun.asuscomm.com/japan-economic-dashboard/api/v1/*` で health / gdp-gap / inflation / prediction が HTTP 200 応答を実機確認。CORS は FastAPI 側で `https://reisun.github.io` を許可済。本番デプロイ構成と nginx 抜粋を README.md に追記。）

## Backlog
