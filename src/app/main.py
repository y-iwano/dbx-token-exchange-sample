from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.providers.proxy import ProxyClient, ProxyProvider

from app.auth.entra import create_verifier
from app.auth.token_exchange import DatabricksTokenExchanger
from app.config import Settings
from app.proxy.transport import DatabricksTokenExchangeTransport

logger = logging.getLogger(__name__)


def build_app(settings: Settings) -> FastMCP:  # pylint: disable=redefined-outer-name
    """Build the FastMCP proxy application.

    For each entry in ``settings.mcp_servers``, a ``ProxyProvider`` is created
    (backed by a ``DatabricksTokenExchangeTransport``) and registered on the
    main server via ``add_provider(namespace=name)`` (FastMCP 3.0.0+).

    Result: a single ``/mcp`` endpoint that exposes all configured Databricks
    Managed MCP servers with their tools namespaced as ``{name}_{tool}``.
    """
    verifier = create_verifier(settings)
    auth = RemoteAuthProvider(
        token_verifier=verifier,
        # Tell MCP clients where to obtain Entra ID tokens
        authorization_servers=[
            f"https://login.microsoftonline.com/{settings.azure_tenant_id}/v2.0"
        ],
        base_url=settings.base_url,
    )

    http_client = httpx.AsyncClient()

    @asynccontextmanager
    async def lifespan(_app: FastMCP):
        yield
        await http_client.aclose()

    exchanger = DatabricksTokenExchanger(settings, http_client)

    main = FastMCP("DBX Token Exchange Proxy", auth=auth, lifespan=lifespan)

    if not settings.mcp_servers:
        logger.warning("No MCP_SERVERS configured — proxy has no backends")

    for server_config in settings.mcp_servers:
        url = f"{settings.databricks_host}{server_config.path}"
        transport = DatabricksTokenExchangeTransport(url, exchanger)
        # ProxyClient handles roots/sampling/elicitation forwarding.
        # base_client.new() creates a fresh client per request to avoid
        # request-context leakage across concurrent sessions.
        base_client = ProxyClient(transport)
        provider = ProxyProvider(base_client.new)
        main.add_provider(provider, namespace=server_config.name)
        logger.info("Added provider '%s' → %s", server_config.name, url)

    return main


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    app = build_app(settings)
    app.run(transport="streamable-http", port=settings.port)
