# エンドポイント・インターフェース仕様

## FastMCP が公開するエンドポイント

FastMCP（`RemoteAuthProvider` 使用時）は以下のエンドポイントを自動的に公開する。

### MCP エンドポイント


| パス     | メソッド       | 説明                                  |
| ------ | ---------- | ----------------------------------- |
| `/mcp` | GET / POST | MCP セッション。Streamable HTTP Transport |


### OAuth メタデータエンドポイント（RemoteAuthProvider が自動生成）


| パス                                        | メソッド | 説明                                                                      |
| ----------------------------------------- | ---- | ----------------------------------------------------------------------- |
| `/.well-known/oauth-authorization-server` | GET  | OAuth サーバーメタデータ（RFC 8414）。`authorization_servers` に Entra ID エンドポイントを含む |
| `/.well-known/openid-configuration`       | GET  | OIDC discovery（オプション）                                                   |


> `RemoteAuthProvider` は DCR エンドポイント (`/register`) を公開しない。本プロジェクトでは DCR を使用しないため、これが意図した動作である。

---

## `/mcp` — MCP エンドポイント

### リクエスト

```
Authorization: Bearer <Entra ID Access Token>
Content-Type: application/json
```

MCP プロトコルのメッセージ形式に従う（JSON-RPC 2.0 ベース）。

### 公開されるツール

`MCP_SERVERS` 環境変数に設定した各 Databricks Managed MCP サーバーのツールが、
`{name}_{tool_name}` 形式で単一の `/mcp` エンドポイントから提供される。


| `MCP_SERVERS` エントリ                                         | ツール名プレフィックス | バックエンド                  |
| ---------------------------------------------------------- | ----------- | ----------------------- |
| `{"name": "genie", "path": "/api/2.0/mcp/genie/<id>"}`     | `genie_`    | Genie Space             |
| `{"name": "sql", "path": "/api/2.0/mcp/sql"}`              | `sql_`      | Databricks SQL          |
| `{"name": "vs", "path": "/api/2.0/mcp/vector-search/..."}` | `vs_`       | Vector Search           |
| `{"name": "funcs", "path": "/api/2.0/mcp/functions/..."}`  | `funcs_`    | Unity Catalog Functions |


### 認証エラー時のレスポンス


| 状況                        | HTTP ステータス | レスポンスボディ                          |
| ------------------------- | ---------- | --------------------------------- |
| Authorization ヘッダーなし      | 401        | `WWW-Authenticate: Bearer` ヘッダー付き |
| トークン署名検証失敗                | 401        | MCP エラーレスポンス                      |
| トークン期限切れ                  | 401        | MCP エラーレスポンス                      |
| トークン交換失敗（Databricks 側エラー） | 502        | MCP エラーレスポンス                      |


### MCP エラーレスポンス形式

```json
{
  "jsonrpc": "2.0",
  "id": "<request_id>",
  "error": {
    "code": -32001,
    "message": "<エラーメッセージ>"
  }
}
```

---

## Databricks Managed MCP へのプロキシ仕様

### サポートする Managed MCP サーバー種別


| 種別                      | パス形式                                                         | 説明                                 |
| ----------------------- | ------------------------------------------------------------ | ---------------------------------- |
| Genie Space             | `/api/2.0/mcp/genie/{genie_space_id}`                        | 自然言語によるデータ分析                       |
| Databricks SQL          | `/api/2.0/mcp/sql`                                           | AI 生成 SQL の実行                      |
| Vector Search           | `/api/2.0/mcp/vector-search/{catalog}/{schema}/{index_name}` | ベクトル検索（Databricks 管理 Embedding 必須） |
| Unity Catalog Functions | `/api/2.0/mcp/functions/{catalog}/{schema}`                  | UC 関数の実行                           |


複数種別・複数インスタンスを `MCP_SERVERS` に列挙することで同時にプロキシ可能。

### バックエンドへのヘッダー変換

`DatabricksTokenExchangeTransport` が MCP セッション確立時に以下の変換を行う:


| 受信ヘッダー                                | バックエンドへの転送                                          |
| ------------------------------------- | --------------------------------------------------- |
| `Authorization: Bearer <entra_token>` | `Authorization: Bearer <databricks_token>`（トークン交換後） |
| その他のヘッダー                              | FastMCP が管理（MCP プロトコルヘッダー等）                         |


---

## ヘルスチェック（TBD）

プロセス管理（systemd）と CloudFront ヘルスチェックのために `/health` エンドポイントの追加を検討する。

```
GET /health
→ 200 OK  {"status": "ok"}
```

FastMCP のカスタムルートとして実装予定。