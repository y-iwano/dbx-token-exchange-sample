import pytest

from app.config import Settings


@pytest.fixture
def valid_env(monkeypatch):
    """Set all required environment variables for Settings.

    Does not set PORT so that pydantic's default (3000) applies.
    """
    monkeypatch.setenv("AZURE_TENANT_ID", "test-tenant-id")
    monkeypatch.setenv("AZURE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("DATABRICKS_HOST", "https://test.azuredatabricks.net")
    monkeypatch.setenv("BASE_URL", "https://proxy.example.com")
    monkeypatch.setenv("MCP_SERVERS", '[{"name": "sql", "path": "/api/2.0/mcp/sql"}]')
    monkeypatch.delenv("PORT", raising=False)


@pytest.fixture
def settings(valid_env) -> Settings:
    return Settings(_env_file=None)
