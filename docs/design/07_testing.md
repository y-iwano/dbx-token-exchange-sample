# テスト設計

## 方針

- `pytest` を使用
- **unit テスト:** モックを使用。外部依存（Entra ID / Databricks）なしで実行可能
- **integration テスト:** 実サービスへの疎通テスト。`INTEGRATION_TESTS=true` 環境変数でのみ実行

## ディレクトリ構成

```
tests/
  unit/
    test_config.py           # 設定バリデーションテスト
    test_token_exchange.py   # DatabricksTokenExchanger のモックテスト
    test_transport.py        # DatabricksTokenExchangeTransport のモックテスト
    test_entra_v1.py         # create_verifier_v1 の単体テスト
  integration/
    conftest.py              # integration テスト専用フィクスチャ
    test_auth_flow.py        # Entra ID → Databricks token exchange の疎通テスト
    test_mcp_proxy.py        # Databricks Managed MCP への転送テスト
    test_entra_v1.py         # v1 verifier の疎通テスト
  conftest.py                # 共通フィクスチャ（Settings, valid_env）
```

---

## Unit テスト

### `test_config.py`

| テストケース | 検証内容 |
|---|---|
| 全必須環境変数が揃っている場合 | `Settings` が正常に生成される |
| 必須環境変数が欠けている場合 | `ValidationError` が raise される |
| `PORT` 未設定の場合 | デフォルト値 `3000` が使用される |
| `databricks_host` に trailing slash がある場合 | 自動除去される |
| `MCP_SERVERS` に `name` が不正な文字を含む場合 | `ValidationError` が raise される |
| `MCP_SERVERS` に `path` が `/` で始まらない場合 | `ValidationError` が raise される |
| `MCP_SERVERS` が空配列の場合 | `Settings` が正常に生成される（警告のみ） |

### `test_token_exchange.py`

`respx`（httpx モックライブラリ）で Databricks OAuth エンドポイントへの HTTP リクエストを差し替える。

| テストケース | 検証内容 |
|---|---|
| token exchange 成功（200） | `access_token` が正しく返る |
| 400 エラー（`invalid_grant`） | `TokenExchangeError` が raise される。リトライなし |
| 401 エラー | `TokenExchangeError` が raise される。リトライなし |
| 500 エラー（1 回後に成功） | リトライ後に `access_token` が返る |
| 500 エラー（3 回連続） | 最大リトライ後に `TokenExchangeError` が raise される |
| ネットワークエラー | リトライ後に `TokenExchangeError` が raise される |
| レスポンスに `access_token` がない | `TokenExchangeError` が raise される |
| 501 エラー | リトライなしで即座に `TokenExchangeError` が raise される（`call_count == 1`） |
| 502 / 503 / 504 エラー（1 回後に成功） | リトライ後に `access_token` が返る |
| 503 + `Retry-After: 5` ヘッダー | `asyncio.sleep(5.0)` が呼ばれる（指数バックオフより優先） |

### `test_transport.py`

`DatabricksTokenExchangeTransport.connect_session` のテスト。
`get_http_headers` と `DatabricksTokenExchanger.exchange` をモックして
トークン取得・トランスポート生成フローを検証する。

| テストケース | 検証内容 |
|---|---|
| 正常フロー | Entra トークンが取得され、交換後の Databricks トークンが `StreamableHttpTransport` の Authorization ヘッダーにセットされる |
| Authorization ヘッダーなし | `TokenExchangeError(status_code=401)` が raise される |
| `Bearer ` プレフィックスの除去 | 大文字・小文字どちらの `bearer ` も正しく除去される |
| `exchange()` が 400 / 401 の `TokenExchangeError` を raise した場合 | `HTTPException(502)` に変換される |
| `exchange()` が 500 / 503 / なし の `TokenExchangeError` を raise した場合 | `HTTPException(503)` に変換される |

### `test_entra_v1.py`

`create_verifier_v1` が返す `AzureJWTVerifier` のプロパティを検証する。
外部への HTTP リクエストは不要。

| テストケース | 検証内容 |
|---|---|
| `issuer` が `sts.windows.net` | v1 issuer が正しくセットされている |
| `jwks_uri` に `/v2.0/` が含まれない | v1 JWKS エンドポイントが使われている |
| `audience` に `identifier_uri` が含まれる | v1 audience が正しくセットされている |
| `audience` に `azure_client_id`（GUID）が含まれない | v1 では GUID を audience に含めない |
| カスタム `IDENTIFIER_URI` 設定時 | `audience` がカスタム URI のみになる |
| `REQUIRED_SCOPES` が設定されている場合 | verifier に `required_scopes` が引き継がれる |
| `REQUIRED_SCOPES` が未設定の場合 | `required_scopes` が空になる（`None` ではない） |
| v1 と v2 の `issuer` 比較 | v1 が `sts.windows.net`、v2 が `login.microsoftonline.com` |
| v1 と v2 の `jwks_uri` 比較 | v1 に `/v2.0/` なし、v2 にあり |
| v1 と v2 の `audience` 比較 | v1 は GUID を含まず、v2 は含む |

---

## Integration テスト

実際の Entra ID / Databricks への疎通が必要。ローカルの `.env` を読み込んで実行する。

### 事前準備: Entra ID アクセストークンの取得

`ENTRA_ACCESS_TOKEN` を `.env` に設定する必要がある。`scripts/get_entra_token.py` を使うと Device Code Flow で取得して `.env` に自動書き込みできる。

```bash
# v2 トークン（デフォルト） → ENTRA_ACCESS_TOKEN に保存
uv run python scripts/get_entra_token.py

# v1 トークン → ENTRA_ACCESS_TOKEN_V1 に保存
uv run python scripts/get_entra_token.py --version 1
```

v1 トークンを取得するには、App Registration のマニフェストで `"requestedAccessTokenVersion": null` または `1` に設定しておく必要がある。

v1 app の App ID URI が v2 と異なる場合は `.env` に `TEST_IDENTIFIER_URI_V1` を設定すること。

**前提（初回のみ）:** Azure Portal → App Registration → Authentication → **「Allow public client flows」を ON** にすること。

```python
import pytest, os

pytestmark = pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "true",
    reason="Set INTEGRATION_TESTS=true to run"
)
```

### `conftest.py`（integration 専用フィクスチャ）

| フィクスチャ | 内容 |
|---|---|
| `int_settings` | `.env` から実際の `Settings` を読み込む |
| `entra_token` | `ENTRA_ACCESS_TOKEN`（v2）を読み込む。未設定時は skip |
| `entra_token_v1` | `ENTRA_ACCESS_TOKEN_V1`（v1）を読み込む。未設定時は skip |
| `identifier_uri_v1` | `TEST_IDENTIFIER_URI_V1` を読み込む。未設定時は `identifier_uri` にフォールバック |
| `proxy_url` | v2 verifier でプロキシサーバーを起動し、URL を返す |
| `proxy_url_v1` | v1 verifier でプロキシサーバーを起動し、URL を返す |

### `test_auth_flow.py`

| テストケース | 検証内容 |
|---|---|
| v2 Entra ID トークンで token exchange が成功する | Databricks アクセストークンが返る |
| 無効なトークンで token exchange が失敗する | `TokenExchangeError` が raise される（`status_code` が 400 または 401） |
| v1 Entra ID トークンで token exchange が成功する | Databricks アクセストークンが返る |

### `test_entra_v1.py`（integration）

| テストケース | 検証内容 |
|---|---|
| v1 トークンが v1 verifier に受理される | `verify_token()` が `None` 以外を返す |
| 不正なトークンが v1 verifier に拒否される | `verify_token()` が `None` を返す |
| v2 トークンが v1 verifier に拒否される | issuer / audience 不一致により `None` が返る |

### `test_mcp_proxy.py`

| テストケース | 検証内容 |
|---|---|
| 無効な Bearer トークンで 401 になる | 認証エラーが返る |
| v2 トークンで tools/list が取得できる | 設定した `name` がプレフィックスのツールが返る |
| 複数バックエンド設定時、全サーバーのツールが取得できる | 各 `name_*` ツールが混在して返る |
| v1 トークンが v2 プロキシに拒否される | 401 が返る |
| v1 トークンで tools/list が取得できる（v1 プロキシ） | 設定した `name` がプレフィックスのツールが返る |
| v2 トークンが v1 プロキシに拒否される | 401 が返る |

---

## 実行方法

```bash
# unit テストのみ
uv run pytest tests/unit/

# integration テスト（.env 設定必要）
INTEGRATION_TESTS=true uv run pytest tests/integration/

# 全テスト
INTEGRATION_TESTS=true uv run pytest
```

## CI 設定（方針）

- PR / push 時に unit テストを自動実行
- Integration テストは手動トリガーまたは別ジョブで実行（credentials が必要なため）
- GitHub Actions を使用する場合、`ENTRA_ACCESS_TOKEN` 等は Secrets で管理
