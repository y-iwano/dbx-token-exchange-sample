import pytest
from pydantic import ValidationError

from app.config import ManagedMCPServerConfig, Settings


class TestManagedMCPServerConfig:
    def test_valid(self):
        cfg = ManagedMCPServerConfig(name="genie", path="/api/2.0/mcp/genie/abc123")
        assert cfg.name == "genie"
        assert cfg.path == "/api/2.0/mcp/genie/abc123"

    def test_name_with_space_invalid(self):
        with pytest.raises(ValidationError):
            ManagedMCPServerConfig(name="genie sql", path="/api/2.0/mcp/sql")

    def test_name_uppercase_invalid(self):
        with pytest.raises(ValidationError):
            ManagedMCPServerConfig(name="Genie", path="/api/2.0/mcp/sql")

    def test_name_special_chars_invalid(self):
        with pytest.raises(ValidationError):
            ManagedMCPServerConfig(name="genie!", path="/api/2.0/mcp/sql")

    def test_name_hyphens_and_underscores_valid(self):
        cfg = ManagedMCPServerConfig(name="vector-search_v2", path="/api/2.0/mcp/sql")
        assert cfg.name == "vector-search_v2"

    def test_path_no_leading_slash_invalid(self):
        with pytest.raises(ValidationError):
            ManagedMCPServerConfig(name="sql", path="api/2.0/mcp/sql")


class TestSettings:
    def test_valid_settings(self, settings):
        assert settings.azure_tenant_id == "test-tenant-id"
        assert settings.azure_client_id == "test-client-id"
        assert settings.databricks_host == "https://test.azuredatabricks.net"
        assert settings.base_url == "https://proxy.example.com"
        assert len(settings.mcp_servers) == 1
        assert settings.mcp_servers[0].name == "sql"

    def test_default_port(self, settings):
        assert settings.port == 3000

    def test_missing_required_var_raises(self, valid_env, monkeypatch):
        monkeypatch.delenv("AZURE_TENANT_ID")
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_trailing_slash_removed_from_host(self, valid_env, monkeypatch):
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.azuredatabricks.net/")
        s = Settings()
        assert s.databricks_host == "https://test.azuredatabricks.net"

    def test_trailing_slash_removed_from_base_url(self, valid_env, monkeypatch):
        monkeypatch.setenv("BASE_URL", "https://proxy.example.com/")
        s = Settings()
        assert s.base_url == "https://proxy.example.com"

    def test_host_without_https_invalid(self, valid_env, monkeypatch):
        monkeypatch.setenv("DATABRICKS_HOST", "http://test.azuredatabricks.net")
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_base_url_localhost_http_valid(self, valid_env, monkeypatch):
        monkeypatch.setenv("BASE_URL", "http://localhost:3000")
        s = Settings(_env_file=None)
        assert s.base_url == "http://localhost:3000"

    def test_base_url_non_localhost_http_invalid(self, valid_env, monkeypatch):
        monkeypatch.setenv("BASE_URL", "http://proxy.example.com")
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_mcp_servers_invalid_name(self, valid_env, monkeypatch):
        monkeypatch.setenv("MCP_SERVERS", '[{"name": "Bad Name!", "path": "/api/2.0/mcp/sql"}]')
        with pytest.raises(ValidationError):
            Settings()

    def test_mcp_servers_path_no_slash(self, valid_env, monkeypatch):
        monkeypatch.setenv("MCP_SERVERS", '[{"name": "sql", "path": "api/2.0/mcp/sql"}]')
        with pytest.raises(ValidationError):
            Settings()

    def test_mcp_servers_empty_list(self, valid_env, monkeypatch):
        monkeypatch.setenv("MCP_SERVERS", "[]")
        s = Settings()
        assert s.mcp_servers == []

    def test_oauth_scopes_default(self, settings):
        assert settings.oauth_scopes == ["openid", "api://test-client-id/access"]

    def test_oauth_scopes_explicit(self, valid_env, monkeypatch):
        monkeypatch.setenv("OAUTH_SCOPES", '["openid", "api://custom-id/access", "email"]')
        s = Settings(_env_file=None)
        assert s.oauth_scopes == ["openid", "api://custom-id/access", "email"]

    def test_mcp_servers_multiple(self, valid_env, monkeypatch):
        monkeypatch.setenv(
            "MCP_SERVERS",
            '[{"name": "genie", "path": "/api/2.0/mcp/genie/abc"},'
            ' {"name": "sql", "path": "/api/2.0/mcp/sql"}]',
        )
        s = Settings()
        assert len(s.mcp_servers) == 2
        assert s.mcp_servers[0].name == "genie"
        assert s.mcp_servers[1].name == "sql"
