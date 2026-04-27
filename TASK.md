# TASK

## Done

- [x] Initial implementation (MVP)
  - [x] Backend: FastAPI + 4 API endpoints (gdp-gap, fund-demand, rates, prediction)
  - [x] Frontend: React + TypeScript + Vite + Recharts ダッシュボード
  - [x] Docker Compose 統合
  - [x] IS-LM予測モデル実装
  - [x] デプロイ・動作確認完了

## Backlog

- [ ] 実データ取得（内閣府GDP、日銀統計）のモックからの切り替え
- [ ] FRED API key 設定による実データ取得
- [ ] VARなど統計的回帰モデルへの拡張
- [ ] ユーザーが任意の財政支出額を入力してシナリオシミュレーション
- [ ] Recharts chunk分割（dynamic import）
- [ ] reverse-proxy への統合
