# Databricks Token Exchange MCP Proxy

Entra ID で認証済みの MCP クライアント（ChatGPT / Claude Desktop など）が、[Databricks Managed MCP](https://docs.databricks.com/aws/ja/generative-ai/mcp/managed-mcp) のツールを利用できるようにする MCP プロキシサーバー。

クライアントが提示した Entra ID Bearer トークンを受け取り、[OAuth Token Exchange (RFC 8693)](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-federation-exchange) で Databricks アクセストークンに交換してからバックエンドに転送する。

```
MCP Client ──[Entra ID Token]──► MCP Proxy ──[Databricks Token]──► Databricks Managed MCP
```

## 前提条件

- Python 3.11+（[uv](https://docs.astral.sh/uv/) でインストール）
- Azure テナントへのアクセス（App Registration を作成できる権限）
- Databricks ワークスペース（Managed MCP が有効化済み）
- Databricks Account Console へのアクセス（federation ポリシー設定）

---

## セットアップ手順

### 1. Entra ID — プロキシサーバー用 App Registration の作成

Azure Portal → **Microsoft Entra ID** → **アプリの登録** → **新規登録**


| 項目              | 設定値                       |
| --------------- | ------------------------- |
| 名前              | 任意（例: `mcp-proxy-server`） |
| サポートされるアカウントの種類 | この組織ディレクトリのみ              |
| リダイレクト URI      | 不要（設定しない）                 |


#### 1-1. API の公開（スコープの定義）

**「API の公開」** タブ → **「スコープの追加」**


| 項目              | 設定値                                        |
| --------------- | ------------------------------------------ |
| アプリケーション ID URI | `api://<Application (client) ID>`（自動生成される） |
| スコープ名           | `access`                                   |
| 同意できるユーザー       | 管理者とユーザー                                   |


#### 1-2. トークンバージョンを v2.0 に設定（必須）

**「マニフェスト」** タブ → JSON を編集

```json
"requestedAccessTokenVersion": 2
```

> これを設定しないと v1.0 トークン（issuer: `sts.windows.net`）が発行され、プロキシの JWT 検証が失敗する。

#### 1-3. オプションクレームの追加（`email` クレームが必要な場合）

**「トークン構成」** タブ → **「オプションクレームの追加」** → **「アクセス」** を選択 → `email` にチェック

> Databricks の federation ポリシーでユーザーを `email` クレームで識別する場合に必要。

#### 1-4. 確認事項

設定後に以下の値を控えておく:


| 値                 | 場所                                                |
| ----------------- | ------------------------------------------------- |
| `AZURE_TENANT_ID` | Azure Portal → Entra ID → 概要 → テナント ID            |
| `AZURE_CLIENT_ID` | 作成した App Registration → 概要 → アプリケーション (クライアント) ID |


---

### 2. Entra ID — MCP クライアントアプリの App Registration（オプション）

ChatGPT / Claude Desktop などが OAuth フローを自前で実行する場合、クライアントアプリ用に別の App Registration を作成する。

- **API のアクセス許可** → **「アクセス許可の追加」** → **「自分の API」** → 手順 1 で作成した App を選択 → `access` スコープにチェック
- リダイレクト URI はクライアントアプリの要件に合わせて設定

> テスト用途であれば Device Code Flow が手軽。詳細は[「テスト用トークンの取得」](#テスト用トークンの取得)を参照。

---

### 3. Databricks — Account-wide Federation ポリシーの設定

Account Console → **Security** → **Authentication** → **Federation policies** → **「Create policy」**


| 項目            | 設定値                                                                               |
| ------------- | --------------------------------------------------------------------------------- |
| Issuer        | `https://login.microsoftonline.com/<AZURE_TENANT_ID>/v2.0`                        |
| Audiences     | Entra ID トークンの `aud` クレームの値（例: `api://<AZURE_CLIENT_ID>` または `<AZURE_CLIENT_ID>`） |
| Subject claim | `email`（または `sub`）                                                                |


> **Audience の確認方法:** `scripts/get_entra_token.py` でトークンを取得し、[jwt.ms](https://jwt.ms) でデコードして `aud` クレームの値を確認する。

---

### 4. ローカルセットアップ

```bash
# リポジトリのクローン
git clone https://github.com/y-iwano/dbx-token-exchange-sample.git
cd dbx-token-exchange-sample

# 依存関係のインストール
uv sync

# 環境変数ファイルの作成
cp .env.example .env
```

`.env` を編集して各値を設定:

```bash
# Entra ID
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# Databricks
DATABRICKS_HOST=https://<workspace>.azuredatabricks.net

# Server（ローカル開発時は http://localhost:3000 も可）
BASE_URL=http://localhost:3000
PORT=3000

# プロキシ対象の Databricks Managed MCP サーバー一覧
# name: ツール名前空間プレフィックス（例: "sql" → ツール名 "sql_*"）
# path: Databricks API パス
MCP_SERVERS='[{"name": "sql", "path": "/api/2.0/mcp/sql"}]'
```

#### `MCP_SERVERS` で指定できるパスパターン


| 種別                      | パス                                                           |
| ----------------------- | ------------------------------------------------------------ |
| Genie Space             | `/api/2.0/mcp/genie/{genie_space_id}`                        |
| Databricks SQL          | `/api/2.0/mcp/sql`                                           |
| Vector Search           | `/api/2.0/mcp/vector-search/{catalog}/{schema}/{index_name}` |
| Unity Catalog Functions | `/api/2.0/mcp/functions/{catalog}/{schema}`                  |


---

### 5. サーバーの起動

```bash
uv run python -m app.main
```

起動後、`http://localhost:3000/mcp` が MCP エンドポイントとして利用可能になる。

---

## テスト用トークンの取得

MCP クライアントや integration テストのために Entra ID アクセストークンが必要な場合、Device Code Flow でブラウザ不要で取得できる。

**事前準備（初回のみ）:** Azure Portal → 手順 1 の App Registration → **「認証」** → **「パブリック クライアント フローを許可する」** → **ON** に設定

```bash
uv run python scripts/get_entra_token.py
```

画面に表示された URL（`https://microsoft.com/devicelogin`）を開き、コードを入力するとトークンが取得され `.env` の `ENTRA_ACCESS_TOKEN` に書き込まれる。トークンの有効期限は約 1 時間。

---

## テストの実行

```bash
# unit テスト（外部サービス不要）
uv run pytest tests/unit/

# integration テスト（.env に実際の認証情報が必要）
INTEGRATION_TESTS=true uv run pytest tests/integration/

# 全テスト
INTEGRATION_TESTS=true uv run pytest

# カバレッジなし
uv run pytest --no-cov
```

カバレッジレポートは `htmlcov/index.html` に出力される。

---

## 開発コマンド

```bash
uv run pylint src/app   # lint チェック
```

---

## 環境変数リファレンス


| 変数名               | 必須  | デフォルト  | 説明                                                       |
| ----------------- | --- | ------ | -------------------------------------------------------- |
| `AZURE_TENANT_ID` | ✅   | —      | Azure テナント ID                                            |
| `AZURE_CLIENT_ID` | ✅   | —      | プロキシサーバー用 App Registration の Client ID                   |
| `DATABRICKS_HOST` | ✅   | —      | Databricks ワークスペース URL（`https://` から始まること）               |
| `BASE_URL`        | ✅   | —      | このサーバーの公開 URL（`https://`、またはローカル開発時は `http://localhost`） |
| `PORT`            | —   | `3000` | Listen ポート                                               |
| `MCP_SERVERS`     | ✅   | —      | プロキシ対象サーバー一覧（JSON 配列）                                    |


`.env` に余分な変数があっても無視される（`extra="ignore"`）。

---

## (参考) AWS へのテストデプロイ（AWS EC2 + CloudFront）

詳細は [docs/design/01_architecture.md](docs/design/01_architecture.md) を参照。概要:

1. EC2（プライベートサブネット）にデプロイし、port 3000 で起動
2. CloudFront の VPC Origin で HTTPS 終端 → EC2 への HTTP:3000 転送
3. systemd でプロセス管理:

```bash
# /etc/systemd/system/mcp-proxy.service の EnvironmentFile に .env を指定
sudo systemctl enable mcp-proxy
sudo systemctl start mcp-proxy
```

---

## 詳細設計


| ドキュメント                                                               | 内容                   |
| -------------------------------------------------------------------- | -------------------- |
| [docs/design/01_architecture.md](docs/design/01_architecture.md)     | システム全体アーキテクチャ・デプロイ構成 |
| [docs/design/02_auth_flow.md](docs/design/02_auth_flow.md)           | 認証・トークン交換フロー（シーケンス図） |
| [docs/design/03_components.md](docs/design/03_components.md)         | コンポーネント詳細設計          |
| [docs/design/04_api.md](docs/design/04_api.md)                       | エンドポイント仕様            |
| [docs/design/05_config.md](docs/design/05_config.md)                 | 設定・環境変数仕様            |
| [docs/design/06_error_handling.md](docs/design/06_error_handling.md) | エラーハンドリング方針          |
| [docs/design/07_testing.md](docs/design/07_testing.md)               | テスト設計                |


