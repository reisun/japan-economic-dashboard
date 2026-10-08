# Cloudflare Quick Tunnel と GitHub Pages

ブラウザ → GitHub Pages (静的フロント) → Cloudflare Quick Tunnel → Compose `api:8000`。
API は Compose の専用ネットワーク内で公開し、共有リバプロへの接続は不要。
共通起動・URL 更新手順は `../reverse-proxy/README.md` に記載する。
`python3 ../reverse-proxy/scripts/quick-tunnels.py start japan-economic-dashboard` で起動・設定更新する。
ランチャーは変数更新と同時に workflow の `api_base_url` 入力へ URL を渡し、
その配信の URL を固定する。
共通ランチャーが専用 tunnel override を指定するため、古い未追跡の
`docker-compose.override.yml` (共有ネットワーク用) は利用しない。

フロントは起動前に Pages の `config.json` を `cache: "no-store"` で取得する。
本番で取得・検証に失敗した場合は設定エラーを表示し、旧リバプロや localhost へ接続しない。
開発時は `VITE_API_BASE_URL` またはローカル API を使用する。

```json
{ "apiBaseUrl": "https://example-random.trycloudflare.com/api/v1" }
```

一時 URL はコミットしない。GitHub Repository Variable `QUICK_TUNNEL_URL` に
API ベース URL 全体 (末尾 `/api/v1`) を保存し、`deploy.yml` を実行する。
Pages workflow がビルド後の `dist/config.json` に値を書き込む。
未設定の場合も Pages は配信できるが、画面は API 未設定を明示する。
Tunnel を再作成すると URL が変わるため、変数更新と Pages 再デプロイが必要。
既に開いている画面は再デプロイ後に再読み込みする。

```bash
gh variable set QUICK_TUNNEL_URL --body "https://example-random.trycloudflare.com/api/v1" --repo reisun/japan-economic-dashboard
gh workflow run deploy.yml --repo reisun/japan-economic-dashboard --ref main
```

CORS は API が `https://reisun.github.io` を許可する。
Quick Tunnel の一時 URL を CORS の許可オリジンに追加する必要はない。
健康確認: `/api/v1/health/data-sources`。
