# コンポーネント詳細設計

## モジュール構成

```
src/
  app/
    main.py               # FastMCP サーバーエントリーポイント
    config.py             # pydantic-settings による環境変数管理
    auth/
      __init__.py
      entra.py            # Entra ID トークン検証（AzureJWTVerifier 設定）
      token_exchange.py   # Databricks トークン交換ロジック
    proxy/
      __init__.py
      transport.py        # カスタム MCP クライアントトランスポート
```

---

## `config.py` — 設定管理

`pydantic-settings` の `BaseSettings` を継承。環境変数と `.env` ファイルから自動ロード。

```python
class ManagedMCPServerConfig(BaseModel):
    name: str   # ツール名前空間プレフィックス（例: "genie" → ツール名 "genie_*"）
    path: str   # Databricks API パス（例: "/api/2.0/mcp/genie/<id>"）

class Settings(BaseSettings):
    # Entra ID
    azure_tenant_id: str
    azure_client_id: str

    # Databricks
    databricks_host: str          # trailing slash なし

    # Server
    base_url: str                 # trailing slash なし
    port: int = 3000

    # プロキシ対象の Databricks Managed MCP サーバー一覧（JSON 配列）
    mcp_servers: list[ManagedMCPServerConfig]

    # MCP クライアントに公開する OAuth スコープ一覧（JSON 配列）
    # 未設定時は ["openid", "api://<azure_client_id>/access"] を自動生成
    oauth_scopes: list[str] = []

    # 受信トークンの scp クレームに必要なスコープ名（短縮形・Azure Portal 定義と一致）
    # 未設定時は scp クレームの検証をスキップ
    required_scopes: list[str] | None = None

    # Entra ID App Registration の Application ID URI
    # 未設定時は api://<azure_client_id>
    identifier_uri: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
```

### バリデーション

- `databricks_host`: `https://` から始まること
- `base_url`: `https://` から始まること（ローカル開発時は `http://localhost` / `http://127.0.0.1` も可）
- `port`: 1–65535 の範囲
- `ManagedMCPServerConfig.name`: 小文字英数字・ハイフン・アンダースコアのみ
- `ManagedMCPServerConfig.path`: `/` から始まること

---

## `auth/entra.py` — Entra ID 検証

`AzureJWTVerifier` を Entra ID 向けに設定して返す。

```python
def create_verifier(settings: Settings) -> AzureJWTVerifier:
    return AzureJWTVerifier(
        client_id=settings.azure_client_id,
        tenant_id=settings.azure_tenant_id,
        required_scopes=settings.required_scopes,
        identifier_uri=settings.identifier_uri,
    )
```

**責務:**
- `AzureJWTVerifier` インスタンスの生成のみ
- 実際のトークン検証（署名・issuer・audience・expiry・scp）は FastMCP ライブラリが実施
- JWKS URI・issuer・audience は `AzureJWTVerifier` が `azure_tenant_id` / `azure_client_id` から自動設定
- `scopes_supported` プロパティが `identifier_uri` + `required_scopes` から完全形スコープ URI を自動生成

---

## `auth/token_exchange.py` — Databricks トークン交換

### クラス: `DatabricksTokenExchanger`

```python
class DatabricksTokenExchanger:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient): ...

    async def exchange(self, entra_token: str) -> str:
        """
        Entra ID アクセストークンを Databricks アクセストークンに交換する。
        Returns: Databricks access token
        Raises: TokenExchangeError
        """
```

### 処理詳細

1. `POST {DATABRICKS_HOST}/oidc/v1/token` に RFC 8693 形式でリクエスト
2. レスポンスの `access_token` を返す
3. HTTP エラー時はリトライ（後述）

### リトライ方針

| 条件 | 動作 |
|---|---|
| 5xx / ネットワークエラー | 指数バックオフ（1s, 2s, 4s）で最大 3 回リトライ |
| 400 / 401 | リトライなし。即座に `TokenExchangeError` を raise |

### 例外定義

```python
class TokenExchangeError(Exception):
    def __init__(self, message: str, status_code: int | None = None): ...
```

---

## `proxy/transport.py` — カスタム MCP クライアントトランスポート

### クラス: `DatabricksTokenExchangeTransport`

`ClientTransport` を継承し、MCP セッション確立のたびにトークン交換を行う。

```python
class DatabricksTokenExchangeTransport(ClientTransport):
    def __init__(self, url: str, exchanger: DatabricksTokenExchanger): ...

    @asynccontextmanager
    async def connect_session(self, **kwargs) -> AsyncGenerator:
        """
        1. 受信リクエストの Authorization ヘッダーから Entra ID トークンを取得
           （fastmcp.server.dependencies.get_http_headers 経由）
        2. DatabricksTokenExchanger でトークン交換
        3. 交換済み Databricks トークンを Authorization ヘッダーにセットした
           StreamableHttpTransport を生成してセッションを確立
        """
```

**設計ポイント:**
- セッションごとに新しい `StreamableHttpTransport` を生成するため、トークンの競合が発生しない
- `get_http_headers(include={"authorization"})` が FastMCP のリクエストコンテキストから
  受信 Entra ID トークンを読み取る（FastMCP の context var 機構を利用）
- `DatabricksMCPClient`（旧設計）を廃止し、FastMCP の `create_proxy` に委譲することで
  ツール一覧取得・呼び出し転送を自前実装不要にした

---

## `main.py` — サーバーエントリーポイント

```python
def build_app(settings: Settings) -> FastMCP:
    verifier = create_verifier(settings)
    auth = RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[f"https://login.microsoftonline.com/{tenant_id}/v2.0"],
        base_url=settings.base_url,
        scopes_supported=settings.oauth_scopes,  # OAUTH_SCOPES 環境変数から取得
    )
    exchanger = DatabricksTokenExchanger(settings, httpx.AsyncClient())

    main = FastMCP("DBX Token Exchange Proxy", auth=auth, lifespan=lifespan)

    for server_config in settings.mcp_servers:
        url = f"{settings.databricks_host}{server_config.path}"
        transport = DatabricksTokenExchangeTransport(url, exchanger)
        base_client = ProxyClient(transport)          # roots/sampling/elicitation 転送対応
        provider = ProxyProvider(base_client.new)     # リクエストごとに fresh client を生成
        main.add_provider(provider, namespace=server_config.name)  # ツール名: {name}_{tool}

    return main
```

### 起動

```bash
uv run python -m app.main
```

Uvicorn で port `settings.port` を Listen。

### 複数 Managed MCP サーバーの統合構造

`FastMCP.add_provider(provider, namespace=name)`（FastMCP 3.0.0+）により、
各バックエンドのツールが名前空間プレフィックス付きで単一の `/mcp` エンドポイントに統合される。

| `MCP_SERVERS` 設定 | 公開されるツール例 |
|---|---|
| `name=genie` | `genie_ask_question`, `genie_get_spaces`, ... |
| `name=sql` | `sql_execute_query`, `sql_list_warehouses`, ... |
| `name=vector_search` | `vector_search_query`, ... |

MCP クライアントは単一 URL `{BASE_URL}/mcp` に接続するだけで、
設定したすべての Managed MCP サーバーのツールを利用できる。

---

## 依存関係

```
fastmcp>=3.0.0      # MCP フレームワーク（AzureJWTVerifier, RemoteAuthProvider, ProxyProvider, add_provider namespace 対応）
httpx               # 非同期 HTTP クライアント（トークン交換リクエスト）
pydantic-settings   # 環境変数管理
```

### 注記: `create_proxy` ではなく `ProxyProvider + add_provider` を採用した理由

FastMCP でリモート MCP サーバーをプロキシする方法として `create_proxy` と `ProxyProvider + add_provider` の 2 通りがある。本プロジェクトでは後者を採用する。

**`create_proxy` の動作**

```python
proxy = create_proxy(transport, name=server_config.name)  # FastMCPProxy を生成
main.mount(proxy, namespace=server_config.name)           # FastMCP として mount
```

`create_proxy` は内部で `ProxyProvider` を `add_provider` した `FastMCPProxy`（`FastMCP` のサブクラス）を生成する。これを `mount` するとサーバー層が二重になる（メインサーバー → FastMCPProxy → ProxyProvider）。

**`ProxyProvider + add_provider` の動作**

```python
base_client = ProxyClient(transport)
provider = ProxyProvider(base_client.new)
main.add_provider(provider, namespace=server_config.name)
```

`ProxyProvider` を直接メインサーバーに登録する。中間の `FastMCPProxy` オブジェクトが不要になり、サーバー層が 1 段階（メインサーバー → ProxyProvider）になる。

**採用理由**

| 観点 | `create_proxy + mount` | `ProxyProvider + add_provider` |
|---|---|---|
| サーバー層の数 | 2（FastMCPProxy を経由） | 1（直接 Provider 登録） |
| `namespace` の扱い | `mount` の引数として後付け | `add_provider` の引数として一体化（FastMCP 3.0.0+ 推奨） |
| roots / sampling / elicitation 転送 | `create_proxy` の内部実装に依存 | `ProxyClient` が明示的に処理 |
| FastMCP 推奨パターン | 旧来の便利 API | `proxy.py` ドキュメントコメントで明示された正規パターン |

FastMCP 3.0.0 の `proxy.py` ドキュメントコメントでは以下のように明示されている:

```python
mcp.add_provider(proxy)
# Can also add with namespace
mcp.add_provider(proxy.with_namespace("remote"))
```

`add_provider(namespace=)` は FastMCP 3.0.0 で追加された機能であり、`mount(namespace=)` の `namespace` パラメータも同バージョンで追加（旧 `prefix` パラメータを置き換え）。本プロジェクトでは `fastmcp>=3.0.0` を必須とし、推奨パターンを採用する。

---

### 注記: Databricks SDK の非採用について

Databricks SDK（`databricks-sdk`）にも `ClientCredentials` / `DatabricksOidcTokenSource` 等の
トークン交換実装があるが、以下の理由で採用しない:

- SDK は内部で `requests`（同期）を使用しており、`httpx` 非同期と混在する
- `DatabricksOidcTokenSource` は GitHub Actions 等の CI/CD OIDC シナリオ向け設計であり、Entra ID アクセストークンをそのまま `subject_token` として渡す本ユースケースに適合しない
- `databricks-sdk` 全体を依存に追加するには機能が過剰

`DatabricksTokenExchanger` の実装は SDK の `ClientCredentials` / `DatabricksOidcTokenSource` を
参考にしつつ、`httpx.AsyncClient` でシンプルに実装する。
