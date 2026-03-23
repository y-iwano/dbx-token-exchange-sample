# 設定・環境変数仕様

## 環境変数一覧

| 変数名 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `AZURE_TENANT_ID` | ✅ | — | Azure テナント ID。JWKS / issuer URL の構築に使用 |
| `AZURE_CLIENT_ID` | ✅ | — | プロキシサーバー用 App registration の Client ID。トークンの `aud` 検証に使用 |
| `DATABRICKS_HOST` | ✅ | — | Databricks ワークスペース URL（例: `https://<workspace>.azuredatabricks.net`）。trailing slash なし |
| `BASE_URL` | ✅ | — | このサーバーの**クライアントから見える公開 URL**。`RemoteAuthProvider` が OAuth メタデータの `protected_resource` として公開する。trailing slash なし |
| `PORT` | — | `3000` | uvicorn が **listen するポート**（内部） |
| `MCP_SERVERS` | ✅ | — | プロキシ対象の Databricks Managed MCP サーバー一覧（JSON 配列、後述） |
| `OAUTH_SCOPES` | — | — | MCP クライアントに公開する OAuth スコープ一覧（JSON 配列）（例: `["openid", "https://your-domain.com/mcp/access"]`） |
| `REQUIRED_SCOPES` | — | — | 受信トークンの `scp` クレームに必要なスコープ名（短縮形。Azure Portal「API の公開」で定義した名前と一致させること）。未設定時は `scp` 検証をスキップ（例: `["access"]`） |
| `IDENTIFIER_URI` | — | — | Entra ID App Registration の Application ID URI。OAuth メタデータのスコープ URI 生成に使用（例: `https://your-domain.com/mcp`） |
| `ENTRA_VERSION` | — | `"2"` | Entra ID のエンドポイントバージョン（`"1"` または `"2"`）。**トークン検証**（issuer / JWKS URI / audience）と **認可サーバーエンドポイント**（MCP クライアントに通知する URL）の両方を切り替える。v1: `sts.windows.net` issuer・`/v2.0` なしエンドポイント、v2: `login.microsoftonline.com/.../v2.0` issuer・`/v2.0` ありエンドポイント |

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

# OAuth scopes advertised to MCP clients (JSON array).
# Must match the App ID URI and scope defined in Azure Portal "Expose an API".
# OAUTH_SCOPES='["openid", "https://your-domain.com/mcp/access"]'

# Short-form scope names required in incoming token scp claims.
# Must match scope names defined in Azure Portal "Expose an API".
# If not set, scp validation is skipped.
# REQUIRED_SCOPES='["access"]'

# Application ID URI of the Entra App Registration.
# Set to BASE_URL/mcp to align with the resource parameter sent by MCP Inspector.
# IDENTIFIER_URI=https://your-domain.com/mcp

# Managed MCP servers to proxy
MCP_SERVERS='[{"name": "genie", "path": "/api/2.0/mcp/genie/<genie_space_id>"}, {"name": "sql", "path": "/api/2.0/mcp/sql"}]'
```

## `BASE_URL` と `PORT` の関係

`BASE_URL`（公開 URL）と `PORT`（uvicorn の listen ポート）は役割が異なるため、両方の設定が必要。

### 本番環境（CloudFront + EC2）

```
Internet ──HTTPS:443──► CloudFront ──HTTP:3000──► EC2 (uvicorn)
```

CloudFront が HTTPS:443 を終端するため、`BASE_URL` にポートを含める必要はない。

```bash
PORT=3000                           # uvicorn の listen ポート
BASE_URL=https://your-domain.com    # CloudFront の公開 URL（ポート不要）
```

### ローカル開発

CloudFront がないため、`BASE_URL` に `PORT` と同じポートを含めないと `protected_resource` の不一致エラーが発生する。

```bash
PORT=3100
BASE_URL=http://localhost:3100   # PORT と揃える（必須）
```

> MCP Inspector 等から接続した際に `Protected resource http://localhost/mcp does not match expected http://localhost:3100/mcp` のようなエラーが出た場合は、`BASE_URL` にポートが含まれていないことが原因。

---

## `OAUTH_SCOPES` の設定指針

`OAUTH_SCOPES` は MCP クライアント（MCP Inspector 等）が Entra ID に対してトークンを要求する際に使用するスコープ一覧。正しく設定しないと Entra ID から `AADSTS9010010` エラーが発生する。

### Entra ID が要求するスコープ形式

Entra ID v2.0 では `openid` が必須。リソーススコープは Entra ID App Registration で定義したスコープ URI の形式で指定する。

| App ID URI の形式 | スコープ例 |
|---|---|
| `https://your-domain.com/mcp` | `https://your-domain.com/mcp/access` |

### `resource` パラメーターとの整合性

MCP Inspector は保護リソースメタデータの `resource` フィールド（`BASE_URL/mcp` の値）を `resource` パラメーターとして Entra ID に送信する。Entra ID v2.0 は `resource` とスコープが**同じ App を指している**ことを要求する。

| 状況 | `resource` パラメーター | 必要な `OAUTH_SCOPES` |
|---|---|---|
| `BASE_URL=https://your-domain.com`（App ID URI が `https://your-domain.com`） | `https://your-domain.com/mcp` | `["openid", "https://your-domain.com/all-apis"]` |
| `BASE_URL=http://localhost:3100`（ローカル開発） | `http://localhost:3100/mcp`（Entra ID 未登録） | OAuth フロー非対応。Bearer Token を直接使用すること |

> **ローカル開発時の注意:** `BASE_URL` が `http://localhost:...` の場合、Entra ID は `resource=http://localhost:.../mcp` を認識しないため、MCP Inspector の OAuth フローは機能しない。代わりに `scripts/get_entra_token.py` でトークンを取得し、MCP Inspector の Authorization ヘッダーに直接貼り付けること。

---

## セキュリティ注意事項

- `.env` は `.gitignore` に追加し、リポジトリにコミットしない
- EC2 上では `chmod 600 .env` でオーナーのみ読み取り可にする
- 本番環境では AWS Secrets Manager や Parameter Store への移行を検討する

## Azure Portal 設定（プロキシサーバー用 App registration）

| 設定項目 | 値 |
|---|---|
| `accessTokenAcceptedVersion` (Manifest) | `2`（`ENTRA_VERSION=2` の場合）/ `null` または `1`（`ENTRA_VERSION=1` の場合） |
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
