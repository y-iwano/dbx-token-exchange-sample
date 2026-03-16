# エラーハンドリング方針

## 基本方針

- HTTP エラーは適切な MCP エラーレスポンス（JSON-RPC 2.0 形式）に変換する
- シークレット（トークン・パスワード等）はエラーメッセージに含めない
- エラーはログに記録する（`logging` モジュール使用）

## エラー分類と対応

### 認証エラー（クライアント起因）

| 状況 | HTTP | MCP エラーコード | ログレベル |
|---|---|---|---|
| `Authorization` ヘッダーなし | 401 | — | DEBUG |
| Entra ID トークン署名不正 | 401 | -32001 | WARNING |
| Entra ID トークン期限切れ | 401 | -32001 | INFO |
| Entra ID トークン audience 不一致 | 401 | -32001 | WARNING |

### サーバー内部エラー

| 状況 | HTTP | MCP エラーコード | ログレベル |
|---|---|---|---|
| Databricks token exchange 失敗（400/401） | 502 | -32002 | ERROR |
| Databricks token exchange 失敗（5xx） | 503 | -32003 | ERROR |
| Databricks MCP 転送エラー | 502 | -32002 | ERROR |
| 設定値不正（起動時） | — | — | CRITICAL（起動失敗） |

### リトライ

| 対象 | 条件 | リトライ回数 | バックオフ |
|---|---|---|---|
| Databricks token exchange | 500 / 502 / 503 / 504 / ネットワークエラー | 最大 3 回 | 指数バックオフ（1s, 2s, 4s）※1 |
| Databricks MCP 転送 | 5xx / ネットワークエラー | 最大 2 回 | 指数バックオフ（1s, 2s） |

※1 503 レスポンスに `Retry-After` ヘッダーが含まれる場合は、その値（秒）を優先して使用する。

**リトライしない条件:**

- 400 / 401: クライアント起因のエラー（再送しても結果は変わらない）
- 501 / 505 など一時的でない 5xx: OIDC エンドポイントの設定ミスや未対応プロトコルを示し、リトライで解消しない

## MCP エラーレスポンス形式

```json
{
  "jsonrpc": "2.0",
  "id": "<request_id>",
  "error": {
    "code": -32001,
    "message": "Authentication failed: token expired"
  }
}
```

### カスタムエラーコード定義

| コード | 意味 |
|---|---|
| -32001 | 認証エラー（Entra ID トークン検証失敗） |
| -32002 | 上流サービスエラー（Databricks 側の 4xx） |
| -32003 | 上流サービス一時エラー（Databricks 側の 5xx / タイムアウト） |

## ログ設計

### フォーマット

開発環境: テキスト形式

```
2026-01-01 00:00:00,000 [INFO] token_exchange: exchanged token for sub=<subject_id>
```

本番環境: JSON 形式（推奨）

```json
{"timestamp": "2026-01-01T00:00:00Z", "level": "INFO", "module": "token_exchange", "message": "exchanged token", "sub": "<subject_id>"}
```

### ログに含めてはいけない情報

- アクセストークン（Entra ID / Databricks ともに）
- Client Secret
- リクエストボディ全体（機密データを含む可能性があるため）

### ログに含める情報（例）

- リクエストの `sub`（ユーザー識別子、トークンのクレームから取得）
- レスポンスの HTTP ステータスコード
- エラーの種別とメッセージ（シークレットを除く）
- リトライ回数
