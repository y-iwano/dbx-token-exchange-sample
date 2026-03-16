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
  integration/
    test_auth_flow.py        # Entra ID → Databricks token exchange の疎通テスト
    test_mcp_proxy.py        # Databricks Managed MCP への転送テスト
  conftest.py                # 共通フィクスチャ
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

```python
import respx, httpx, pytest
from app.auth.token_exchange import DatabricksTokenExchanger, TokenExchangeError

@pytest.fixture
def exchanger(settings):
    async with httpx.AsyncClient() as client:
        yield DatabricksTokenExchanger(settings, client)

@respx.mock
async def test_exchange_success(exchanger):
    respx.post("https://host/oidc/v1/token").respond(
        200, json={"access_token": "dbx-token", "token_type": "Bearer"}
    )
    token = await exchanger.exchange("entra-token")
    assert token == "dbx-token"

@respx.mock
async def test_exchange_400_no_retry(exchanger):
    respx.post("https://host/oidc/v1/token").respond(
        400, json={"error": "invalid_grant"}
    )
    with pytest.raises(TokenExchangeError) as exc:
        await exchanger.exchange("bad-token")
    assert exc.value.status_code == 400
    assert respx.calls.call_count == 1  # リトライなし
```

### `test_transport.py`

`DatabricksTokenExchangeTransport.connect_session` のテスト。
`get_http_headers` と `DatabricksTokenExchanger.exchange` をモックして
トークン取得・トランスポート生成フローを検証する。

| テストケース | 検証内容 |
|---|---|
| 正常フロー | Entra トークンが取得され、交換後の Databricks トークンが `StreamableHttpTransport` の Authorization ヘッダーにセットされる |
| Authorization ヘッダーなし | `TokenExchangeError` が raise される |
| `Bearer ` プレフィックスの除去 | 大文字・小文字どちらの `bearer ` も正しく除去される |
| `exchange()` が 400 / 401 の `TokenExchangeError` を raise した場合 | `HTTPException(502)` に変換される |
| `exchange()` が 500 / 503 / なし の `TokenExchangeError` を raise した場合 | `HTTPException(503)` に変換される |

```python
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from app.proxy.transport import DatabricksTokenExchangeTransport
from app.auth.token_exchange import TokenExchangeError

async def test_connect_session_sets_databricks_token(settings):
    exchanger = AsyncMock()
    exchanger.exchange.return_value = "dbx-token"

    transport = DatabricksTokenExchangeTransport(
        url="https://host/api/2.0/mcp/sql",
        exchanger=exchanger,
    )

    mock_session = MagicMock()

    with (
        patch("app.proxy.transport.get_http_headers",
              return_value={"authorization": "Bearer entra-token"}),
        patch("fastmcp.client.transports.StreamableHttpTransport.connect_session",
              return_value=async_context(mock_session)),
    ):
        async with transport.connect_session() as session:
            assert session is mock_session

    exchanger.exchange.assert_awaited_once_with("entra-token")

async def test_missing_auth_header_raises(settings):
    exchanger = AsyncMock()
    transport = DatabricksTokenExchangeTransport("https://host/api/2.0/mcp/sql", exchanger)

    with (
        patch("app.proxy.transport.get_http_headers", return_value={}),
        pytest.raises(TokenExchangeError),
    ):
        async with transport.connect_session():
            pass
```

---

## Integration テスト

実際の Entra ID / Databricks への疎通が必要。ローカルの `.env` を読み込んで実行する。

### 事前準備: Entra ID アクセストークンの取得

`ENTRA_ACCESS_TOKEN` を `.env` に設定する必要がある。`scripts/get_entra_token.py` を使うと Device Code Flow で取得して `.env` に自動書き込みできる。

```bash
uv run python scripts/get_entra_token.py
```

ブラウザで `https://microsoft.com/devicelogin` を開き、表示されたコードを入力するとトークンが取得され `.env` の `ENTRA_ACCESS_TOKEN` に書き込まれる。トークンの有効期限は約 1 時間。

**前提（初回のみ）:** Azure Portal → App Registration → Authentication → **「Allow public client flows」を ON** にすること。

```python
import pytest, os

pytestmark = pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "true",
    reason="Set INTEGRATION_TESTS=true to run"
)
```

### `test_auth_flow.py`

| テストケース | 検証内容 |
|---|---|
| MSAL Authorization Code Flow で取得した Entra ID トークンが token exchange に成功する | Databricks アクセストークンが返る |
| 無効なトークンで token exchange が失敗する | `TokenExchangeError` が raise される |

### `test_mcp_proxy.py`

| テストケース | 検証内容 |
|---|---|
| サーバー起動後、MCP クライアントで `tools/list` が取得できる | 設定した `name` がプレフィックスのツールが返る |
| 複数バックエンド設定時、全サーバーのツールが単一エンドポイントから取得できる | 各 `name_*` ツールが混在して返る |
| 無効な Bearer トークンで MCP リクエストが 401 になる | 認証エラーが返る |

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
