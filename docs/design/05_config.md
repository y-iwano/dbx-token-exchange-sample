# 設定・環境変数仕様

## 環境変数一覧

| 変数名 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `AZURE_TENANT_ID` | ✅ | — | Azure テナント ID。JWKS / issuer URL の構築に使用 |
| `AZURE_CLIENT_ID` | ✅ | — | プロキシサーバー用 App registration の Client ID。トークンの `aud` 検証に使用 |
| `DATABRICKS_HOST` | ✅ | — | Databricks ワークスペース URL（例: `https://<workspace>.azuredatabricks.net`）。trailing slash なし |
| `BASE_URL` | ✅ | — | このサーバーの公開 URL（例: `https://your-domain.com`）。`RemoteAuthProvider` のメタデータ endpoint 公開に使用。trailing slash なし |
| `PORT` | — | `3000` | Listen ポート |
| `MCP_SERVERS` | ✅ | — | プロキシ対象の Databricks Managed MCP サーバー一覧（JSON 配列、後述） |

## `MCP_SERVERS` 仕様

JSON 配列形式。各要素は以下のフィールドを持つ:

| フィールド | 型 | 説明 |
|---|---|---|
| `name` | string | ツール名前空間プレフィックス。小文字英数字・`-`・`_` のみ使用可 |
| `path` | string | Databricks Managed MCP の API パス。`/` から始まること |

```json
MCP_SERVERS='[
  {"name": "genie",  "path": "/api/2.0/mcp/genie/<genie_space_id>"},
  {"name": "sql",    "path": "/api/2.0/mcp/sql"},
  {"name": "vs",     "path": "/api/2.0/mcp/vector-search/<catalog>/<schema>/<index>"},
  {"name": "funcs",  "path": "/api/2.0/mcp/functions/<catalog>/<schema>"}
]'
```

`name` は MCP クライアントが見るツール名のプレフィックスになる（例: `name=genie` → ツール名 `genie_ask_question` 等）。

## `.env.example`

```bash
# Entra ID
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# Databricks
DATABRICKS_HOST=https://<workspace>.azuredatabricks.net

# Server
BASE_URL=https://your-domain.com
PORT=3000

# Managed MCP servers to proxy
MCP_SERVERS='[{"name": "genie", "path": "/api/2.0/mcp/genie/<genie_space_id>"}, {"name": "sql", "path": "/api/2.0/mcp/sql"}]'
```

## セキュリティ注意事項

- `.env` は `.gitignore` に追加し、リポジトリにコミットしない
- EC2 上では `chmod 600 .env` でオーナーのみ読み取り可にする
- 本番環境では AWS Secrets Manager や Parameter Store への移行を検討する

## Azure Portal 設定（プロキシサーバー用 App registration）

| 設定項目 | 値 |
|---|---|
| `requestedAccessTokenVersion` (Manifest) | `2`（必須。v2.0 トークンを発行するため） |
| API の公開 / スコープ | `access`（任意の名前）を定義 |
| リダイレクト URI | 不要（サーバーが OAuth フローを持たないため） |
| クライアントシークレット | 不要（サーバーは検証のみ行うため） |

## Databricks federation ポリシー設定

Account-wide federation を使用するため、Databricks OAuth アプリの Client ID / Client Secret は不要。

| 設定項目 | 値 |
|---|---|
| Federation 種別 | Account-wide（ワークスペース単位で全ユーザーに適用） |
| Grant type | Token Exchange (RFC 8693) |
| `scope` | `all-apis`（リクエスト時に固定） |
| Federation 設定 | Entra ID の issuer / audience を Account Console で登録 |
