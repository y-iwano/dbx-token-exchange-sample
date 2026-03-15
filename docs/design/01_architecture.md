# システム全体アーキテクチャ

## 概要

DBX Token Exchange MCP Proxy は、MCP クライアント（ChatGPT / Claude Desktop 等）が Databricks Managed MCP を利用できるようにする中継サーバーである。クライアントは Entra ID で認証し、サーバーがそのトークンを Databricks OAuth トークンに交換してからプロキシする。

## システム構成図

```
┌──────────────────────────────────────────────────────────────────┐
│ Internet                                                         │
│                                                                  │
│  MCP Client (ChatGPT / Claude Desktop / カスタムクライアント)        │
│    │ Bearer: Entra ID Access Token                               │
│    │ HTTPS                                                       │
└────┼─────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────┐
│ AWS CloudFront (VPC Origin)         │
│  HTTPS → HTTP:3000                  │
└──────────────┬──────────────────────┘
               │ HTTP port 3000（VPC 内部）
               ▼
┌──────────────────────────────────────────────────────────────────┐
│ EC2 (プライベートサブネット)                                          │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ MCP Proxy Server (FastMCP, port 3000)                       │ │
│  │                                                             │ │
│  │  1. AzureJWTVerifier  ─── JWKS取得 ──► Entra ID            │ │
│  │       ↓ 検証済み                       (OIDC endpoint)     │ │
│  │  2. TokenExchanger    ─── token exchange ► Databricks OAuth │ │
│  │       ↓ Databricks Token                                    │ │
│  │  3. MCPClient         ─── MCP リクエスト ► Databricks       │ │
│  │                                          Managed MCP        │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

## デプロイ構成

| リソース | 詳細 |
|---|---|
| EC2 インスタンス | t3/t4 ファミリー、メモリ 2GB 以上、プライベートサブネット |
| CloudFront | VPC Origin 設定。HTTPS 終端。EC2 への転送は HTTP:3000 |
| セキュリティグループ | EC2 インバウンドは CloudFront からの port 3000 のみ許可 |
| アウトバウンド | NAT Gateway 経由で Entra ID / Databricks エンドポイントへ |

## 外部依存

| 外部サービス | 用途 | エンドポイント |
|---|---|---|
| Microsoft Entra ID | JWKS 取得・トークン検証 | `https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration` |
| Databricks OAuth | トークン交換 | `{DATABRICKS_HOST}/oidc/v1/token` |
| Databricks Managed MCP | MCP ツール実行 | `{DATABRICKS_HOST}/api/2.0/...` |

## セキュリティ境界

- クライアント → CloudFront: HTTPS のみ。証明書は CloudFront が管理
- CloudFront → EC2: VPC 内部 HTTP（CloudFront Origin Shield 使用を推奨）
- EC2 → 外部: NAT Gateway 経由のみ。直接インターネット接続なし
- `.env`（シークレット）: EC2 ローカルのみ。リポジトリには含めない

---

## EC2 初期セットアップ

```bash
# uv のインストール
curl -LsSf https://astral.sh/uv/install.sh | sh

# リポジトリのクローン
git clone https://github.com/y-iwano/dbx-token-exchange-sample.git
cd dbx-token-exchange-sample

# 依存関係のインストール
uv sync

# 環境変数の設定
cp .env.example .env
vi .env          # 各値を設定
chmod 600 .env   # オーナーのみ読み取り可
```

## プロセス管理（systemd）

```ini
# /etc/systemd/system/mcp-proxy.service
[Unit]
Description=DBX Token Exchange MCP Proxy
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/dbx-token-exchange-sample
EnvironmentFile=/home/ec2-user/dbx-token-exchange-sample/.env
ExecStart=/home/ec2-user/.local/bin/uv run python -m app.main
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable mcp-proxy
sudo systemctl start mcp-proxy
```

## デプロイ手順（手動）

```bash
# EC2 に SSH 接続後
cd dbx-token-exchange-sample
git pull origin main
uv sync                          # 依存関係の更新（変更があれば）
sudo systemctl restart mcp-proxy # プロセス再起動
sudo systemctl status mcp-proxy  # 起動確認
```
