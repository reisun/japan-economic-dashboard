# japan-economic-dashboard

日本のマクロ経済指標ダッシュボードを新規作成する。

## 技術スタック
- フロント: Vite + React + TypeScript（チャートライブラリ: Recharts or Chart.js）
- バックエンド: Python FastAPI
- Docker Compose で統合

## MVP機能

### 1. GDPギャップ表示
- 内閣府推計値の取得・表示（CSVまたはスクレイピング）
- 自前推計: 実質GDPと潜在GDP（HPフィルタ等）からギャップを算出・表示
- 時系列チャートで両方を並べて比較

### 2. 資金需要指標
- 日銀 資金循環統計から主要セクターの資金過不足を取得・可視化
- 日銀 貸出統計（銀行貸出残高等）を取得・可視化

### 3. 金利・為替の実績データ
- FRED API（米国金利、ドル円等）
- 日銀API（政策金利、国債利回り等）
- 2ソースからデータ取得し、時系列チャートで表示

### 4. 予測モデル（IS-LMベース）
- デフレギャップの大きさに応じた必要財政支出額を算出
- IS-LMモデルに基づき、その財政支出が金利・為替に与える影響を予測
- 実績データに予測線を重ねて表示

### 5. ダッシュボード画面
- 上記の指標をまとめて1画面で閲覧できるダッシュボード
- レスポンシブ対応

## Setup

### 1. 環境変数の設定

リポジトリ直下の `.env.example` をコピーして `.env` を作成する。

```bash
cp .env.example .env
```

以下のキーを設定する。`.env` は `.gitignore` 済みなのでコミットされない。

#### FRED API key（推奨）

US 金利 (DGS10, FEDFUNDS)、USD/JPY (DEXJPUS)、日本 10Y JGB / 短期金利
(IRLTLT01JPM156N / IRSTCI01JPM156N)、銀行貸出 (CRDQJPAPABIS)、
GDPデフレータ (NGDPDSAIXJPQ)、名目賃金 (LCEAMN01JPM659S)、
実質GDP (JPNRGDPEXP) を実データで取得するために必要。

1. https://fredaccount.stlouisfed.org/login/secure/ で無料アカウントを作成
2. https://fredaccount.stlouisfed.org/apikeys でキーを発行
3. `.env` の `FRED_API_KEY=your_key_here` の右辺を発行されたキーで置き換え

未設定でも API は 500 を返さず、各 FRED 系列はモック値にフォールバックする
（起動時に警告ログ 1 回 + 各リクエストで debug ログ）。

#### e-Stat appId（任意）

CPIコアコア（生鮮食品及びエネルギー除く総合）を実データで取得するために使う。
未設定時は総務省統計局 CSV → モックの順にフォールバック。

1. https://www.e-stat.go.jp/api/api-info/api-guide で無料登録
2. 発行された appId を `.env` の `ESTAT_APP_ID` に設定

### 2. 起動

```bash
docker compose build
docker compose up -d
```

API は http://localhost:8001 で待ち受ける。

### 3. データソース取得状況の確認

起動後、以下のエンドポイントで FRED / e-Stat 等の最終取得成否を確認できる。

```bash
curl http://localhost:8001/api/v1/health/data-sources
```

レスポンス例:

```json
{
  "configured": {"FRED_API_KEY": true, "ESTAT_APP_ID": false, "LOG_LEVEL": "INFO"},
  "sources": {
    "fred:DGS10": {"ok": true, "detail": "points=12", "last_checked": "2026-04-28T..."},
    "fred:JPNRGDPEXP": {"ok": true, "detail": "points=20", "last_checked": "..."}
  }
}
```

起動直後は `sources` が空。各 API エンドポイント（`/api/v1/rates` 等）に
1 回アクセスすると登録される。

`api/` のコンテナログにも各取得の成否（real / mock）が出るので、
`docker compose logs api -f` で運用監視可能。

## 注意

- `.env` および API key は **絶対にコミットしない**。
- モックフォールバックが効くため、キー未設定でも 500 にはならないが、
  本番環境では `health/data-sources` で `ok: true` になっていることを確認すること。

## 本番デプロイ構成

本番は次の三層構成で公開している。

```
[ブラウザ]
   │  https://reisun.github.io/japan-economic-dashboard/   (静的フロント)
   ▼
[GitHub Pages]  ── 静的アセット（Vite ビルド成果物）
   │  fetch: https://reisun.asuscomm.com/japan-economic-dashboard/api/v1/...
   ▼
[reverse-proxy (~/workspace/reverse-proxy)]  ── nginx（HTTPS 終端）
   │  proxy_pass: http://japan-economic-dashboard-api:8000/api/...
   ▼  (docker network: japan-economic-dashboard-net)
[このリポジトリの docker compose]  ── FastAPI (uvicorn :8000)
```

- フロントは GitHub Pages から配信され、ビルド時に
  `VITE_API_BASE_URL=https://reisun.asuscomm.com/japan-economic-dashboard/api/v1`
  を埋め込んで API を叩く。
- API 公開は `~/workspace/reverse-proxy/` の nginx が担当。
  外部 `/japan-economic-dashboard/api/` を内部 `/api/` にマップする。
- API 実体はこのリポジトリの `docker compose up -d` で起動するコンテナ
  （`japan-economic-dashboard-api` という network alias を持つ）。
- reverse-proxy 側の docker network `japan-economic-dashboard-net` を
  external として共有することで、reverse-proxy → API への
  HTTP 通信がホスト経由なしで成立する。

### reverse-proxy 側 nginx 設定の関連抜粋

`~/workspace/reverse-proxy/nginx/nginx.conf`:

```nginx
upstream japan_economic_dashboard_api {
    server japan-economic-dashboard-api:8000;
}

# japan-economic-dashboard: /japan-economic-dashboard/api/ を upstream にマップ
location /japan-economic-dashboard/api/ {
    proxy_pass http://japan_economic_dashboard_api/api/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

`~/workspace/reverse-proxy/docker-compose.yml`:

```yaml
networks:
  japan-economic-dashboard-net:
    external: true
    name: japan-economic-dashboard-net
```

CORS は FastAPI 側の `CORSMiddleware` が `https://reisun.github.io` を
許可しており、nginx 側で追加ヘッダを付ける必要はない
（ヘルスエンドポイント `/api/v1/health/data-sources` を含む全
`/api/v1/*` がそのまま透過される）。

### 動作確認コマンド

```bash
# health（reverse-proxy 経由）
curl -k https://reisun.asuscomm.com/japan-economic-dashboard/api/v1/health/data-sources

# 各エンドポイント
curl -k https://reisun.asuscomm.com/japan-economic-dashboard/api/v1/gdp-gap
curl -k https://reisun.asuscomm.com/japan-economic-dashboard/api/v1/inflation
curl -k https://reisun.asuscomm.com/japan-economic-dashboard/api/v1/prediction
```

### 運用メモ

- API コンテナを再起動・再ビルドしても、`japan-economic-dashboard-net`
  自体は維持されるので reverse-proxy の再起動は不要。
- ただし network を作り直した場合（例: `docker compose down` 後）、
  reverse-proxy 側で `docker compose restart nginx` または
  `docker compose exec nginx nginx -s reload` が必要になることがある。
