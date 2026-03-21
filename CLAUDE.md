# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

Databricks の [Managed MCP](https://docs.databricks.com/aws/ja/generative-ai/mcp/managed-mcp) に [Token exchange](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-federation-exchange) を利用してアクセスするための MCP プロキシサーバー。

**ユースケース:** ChatGPT や Claude などが、Entra ID で認証済みの MCP Proxy を経由して Databricks の Managed MCP ツールを利用できるようにする。

**前提条件:**
- Entra ID にアプリ登録済み（プロキシサーバー用・MCP クライアントアプリ用それぞれ）
- Databricks ワークスペースで Managed MCP が有効化済み
- Databricks に OAuth アプリケーション登録済み（token exchange 用）

詳細設計は [docs/design/](docs/design/README.md) を参照。

## Security Policy

**DCR（Dynamic Client Registration）は使用しない。**
DCR はセキュリティリスクがあるため、サーバー・クライアント双方で使用しない。すべての MCP クライアントアプリケーションは Entra ID で事前登録した固定の Client ID / Client Secret を使用すること。

## Key Conventions

- **コードスタイル:** 型ヒント必須。`dataclass` / `pydantic` を積極利用
- **設定:** すべて環境変数で管理（ハードコード禁止）。詳細は [docs/design/05_config.md](docs/design/05_config.md)
- **エラーハンドリング:** HTTP エラーは適切な MCP エラーレスポンスに変換。トークン期限切れは自動リトライ
- **ログ:** Python 標準 `logging` モジュール使用。本番では JSON 形式出力を推奨。トークン・シークレットはログに出力しない
- **パッケージマネージャー:** `uv` を使用（`pip` は使わない）

## Development Setup

```bash
uv venv && source .venv/bin/activate
uv sync
cp .env.example .env   # .env を編集して各値を設定

uv run python -m app.main         # 開発サーバー起動
uv run pytest                     # unit テストのみ（カバレッジレポート付き）
uv run pytest tests/integration/  # integration テスト（.env 設定必要）
uv run pytest --no-cov            # カバレッジなしでテスト実行
uv run pylint src/app             # lint チェック
uv run bandit -r src/app          # セキュリティ静的解析
uv run pip-audit                  # 依存パッケージの脆弱性スキャン
uv run detect-secrets scan --exclude-files '\.env$' > .secrets.baseline  # シークレットベースライン更新
```

カバレッジレポートは `htmlcov/index.html` に出力される。

## Security Checks

| ツール | 目的 | 実行タイミング |
|---|---|---|
| `bandit` | Python コードの静的セキュリティ解析 | 開発時・CI |
| `pip-audit` | 依存パッケージの既知脆弱性スキャン | 開発時・CI |
| `detect-secrets` | シークレットの誤コミット防止 | pre-commit フック |
| `pre-commit` | コミット前の自動チェック実行基盤 | commit 時 |

pre-commit フックは `uv run pre-commit install` で有効化済み。`.secrets.baseline` はコミット対象に含める。
