from __future__ import annotations

import re

from pydantic import BaseModel, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ManagedMCPServerConfig(BaseModel):
    name: str
    """URL-safe identifier used as tool namespace prefix (e.g. "genie" → tools named "genie_*")."""

    path: str
    """Databricks API path for this Managed MCP server.

    Examples:
        /api/2.0/mcp/genie/{genie_space_id}
        /api/2.0/mcp/sql
        /api/2.0/mcp/vector-search/{catalog}/{schema}/{index_name}
        /api/2.0/mcp/functions/{catalog}/{schema}
    """

    @field_validator("name")
    @classmethod
    def name_must_be_url_safe(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9_-]+", v):
            raise ValueError("name must be lowercase alphanumeric with hyphens/underscores only")
        return v

    @field_validator("path")
    @classmethod
    def path_must_start_with_slash(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("path must start with /")
        return v


class Settings(BaseSettings):
    # Entra ID
    azure_tenant_id: str
    azure_client_id: str

    # Databricks
    databricks_host: str

    # Server
    base_url: str
    port: int = 3000

    # Managed MCP servers to proxy (parsed from JSON)
    mcp_servers: list[ManagedMCPServerConfig]

    # OAuth scopes advertised in the protected resource metadata.
    # If not set, defaults to ["openid", "api://<azure_client_id>/access"].
    oauth_scopes: list[str] = []

    # Short-form scope names (as defined in Azure Portal "Expose an API") that
    # incoming tokens must contain in their ``scp`` claim.
    # If not set, scp validation is skipped.
    required_scopes: list[str] | None = None

    # Application ID URI of the Entra App Registration (used to prefix scopes
    # in OAuth metadata). Defaults to api://<azure_client_id>.
    identifier_uri: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("databricks_host")
    @classmethod
    def host_must_be_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("must start with https://")
        return v.rstrip("/")

    @field_validator("base_url")
    @classmethod
    def base_url_must_be_http_or_https(cls, v: str) -> str:
        # Allow http:// for local development (localhost / 127.0.0.1)
        if v.startswith("https://"):
            return v.rstrip("/")
        if re.match(r"http://(localhost|127\.0\.0\.1)(:\d+)?", v):
            return v.rstrip("/")
        raise ValueError("must start with https:// (or http://localhost for local dev)")


    @field_validator("port")
    @classmethod
    def port_in_range(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("port must be between 1 and 65535")
        return v

    @model_validator(mode="after")
    def set_defaults(self) -> "Settings":
        if not self.oauth_scopes:
            self.oauth_scopes = ["openid", f"api://{self.azure_client_id}/access"]
        if not self.identifier_uri:
            self.identifier_uri = f"api://{self.azure_client_id}"
        return self
