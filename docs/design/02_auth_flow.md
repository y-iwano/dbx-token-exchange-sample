# 認証・トークン交換フロー

## 概要

本サーバーは OAuth Proxy パターン（サーバーが OAuth フローを持つ）は採用しない。クライアントが自前で取得した Entra ID Bearer トークンをサーバーが検証し、Databricks トークンに交換する。Dynamic Client Registration (DCR) は使用しない。

## シーケンス図

### 通常フロー（キャッシュなし）

```
MCP Client          MCP Proxy           Entra ID            Databricks OAuth    Databricks MCP
    │                   │                   │                       │                  │
    │ 1. MCP Request    │                   │                       │                  │
    │ Authorization:    │                   │                       │                  │
    │ Bearer <entra_token>                  │                       │                  │
    │──────────────────►│                   │                       │                  │
    │                   │ 2. JWKS 取得      │                       │                  │
    │                   │  (初回 or TTL切れ) │                       │                  │
    │                   │──────────────────►│                       │                  │
    │                   │◄──────────────────│                       │                  │
    │                   │ 3. JWT 検証       │                       │                  │
    │                   │  (署名/audience/  │                       │                  │
    │                   │   expiry)         │                       │                  │
    │                   │                   │                       │                  │
    │                   │ 4. Token Exchange (RFC 8693)              │                  │
    │                   │  grant_type=urn:ietf:params:oauth:        │                  │
    │                   │    grant-type:token-exchange              │                  │
    │                   │  subject_token=<entra_token>              │                  │
    │                   │  subject_token_type=urn:ietf:params:      │                  │
    │                   │    oauth:token-type:jwt                   │                  │
    │                   │  scope=all-apis                           │                  │
    │                   │──────────────────────────────────────────►│                  │
    │                   │◄──────────────────────────────────────────│                  │
    │                   │  access_token=<databricks_token>          │                  │
    │                   │                   │                       │                  │
    │                   │ 5. MCP リクエスト転送                       │                  │
    │                   │  Authorization: Bearer <databricks_token> │                  │
    │                   │────────────────────────────────────────────────────────────►│
    │                   │◄────────────────────────────────────────────────────────────│
    │                   │  MCP Response                             │                  │
    │◄──────────────────│                   │                       │                  │
```

## Entra ID トークン検証（AzureJWTVerifier）

FastMCP の `AzureJWTVerifier` を使用。サーバー自身は OAuth フローを持たない。

### 検証項目

| 項目 | 値 | 検証内容 |
|---|---|---|
| 署名 | RS256（Entra ID が署名） | JWKS から公開鍵を取得して検証 |
| `aud`（audience） | `AZURE_CLIENT_ID` または `api://{AZURE_CLIENT_ID}` | プロキシサーバー向けトークンであることを確認 |
| `exp`（expiry） | Unix timestamp | 有効期限内であることを確認 |
| `iss`（issuer） | `https://login.microsoftonline.com/{tenant_id}/v2.0` | 対象テナントから発行されたことを確認 |

### JWKS キャッシュ

`AzureJWTVerifier` は OIDC discovery endpoint から JWKS を自動取得・キャッシュする。キャッシュ TTL はライブラリデフォルト（通常 24 時間）に従う。

## Databricks Token Exchange（RFC 8693）

### リクエスト

```
POST {DATABRICKS_HOST}/oidc/v1/token
Content-Type: application/x-www-form-urlencoded

grant_type=urn:ietf:params:oauth:grant-type:token-exchange
&subject_token={entra_id_access_token}
&subject_token_type=urn:ietf:params:oauth:token-type:jwt
&scope=all-apis
```

### レスポンス（成功）

```json
{
  "access_token": "<databricks_access_token>",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

### エラーケース

| エラー | 原因 | プロキシの対応 |
|---|---|---|
| `invalid_grant` | Entra ID トークンが無効 / Databricks の federation 設定ミス | 401 を MCP エラーとして返す |
| ネットワークエラー | Databricks エンドポイント到達不可 | リトライ（指数バックオフ）後に 503 |

## クライアント側 Bearer トークン取得（参考）

サーバーは OAuth フローを持たないため、クライアントが自前でトークンを取得する。クライアントは **Authorization Code Flow** を使用してエンドユーザーの委任トークンを取得する（Client Credentials Flow は使用しない）。

### Authorization Code Flow（MSAL）

```python
from msal import PublicClientApplication

app = PublicClientApplication(
    client_id="<クライアントアプリの Client ID>",
    authority=f"https://login.microsoftonline.com/{AZURE_TENANT_ID}",
)

# インタラクティブ認証（ブラウザポップアップ）
result = app.acquire_token_interactive(
    scopes=[f"api://{AZURE_CLIENT_ID}/access", "email"]
)
entra_token = result["access_token"]
```

取得済みのトークンがキャッシュにある場合はサイレント取得を試み、期限切れ・未取得の場合のみ認証を行う:

```python
accounts = app.get_accounts()
if accounts:
    result = app.acquire_token_silent(
        scopes=[f"api://{AZURE_CLIENT_ID}/access", "email"],
        account=accounts[0],
    )
else:
    result = None

if not result:
    result = app.acquire_token_interactive(
        scopes=[f"api://{AZURE_CLIENT_ID}/access", "email"]
    )

entra_token = result["access_token"]
```

### 備考

- Authorization Code Flow はエンドユーザーが自らの Entra ID アカウントで認証するため、委任された権限（delegated permissions）でアクセス可能
- Claude や ChatGPT などの MCP クライアントが OAuth 認証フローをサポートしている場合はそちらの仕組みを利用すること
- `AZURE_CLIENT_ID` はプロキシサーバー用 Entra ID アプリの Client ID（トークンの `aud` クレームと一致させる）

## セキュリティ設計方針

- **DCR 禁止:** Dynamic Client Registration を使用しない。クライアントアプリは Entra ID で事前登録した固定 `client_id` / `client_secret` を使用する
- **トークンログ禁止:** Access Token（Entra・Databricks ともに）をログに出力しない
