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

## Backlog


- [ ] FRED API key 設定による実データ取得
- [ ] VARなど統計的回帰モデルへの拡張
- [ ] ユーザーが任意の財政支出額を入力してシナリオシミュレーション
- [ ] Recharts chunk分割（dynamic import）
- [ ] reverse-proxy への統合
