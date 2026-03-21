from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastmcp import FastMCP
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.providers.proxy import ProxyClient, ProxyProvider
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from app.auth.entra import create_verifier
from app.auth.entra_v1 import create_verifier_v1
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
    if settings.entra_version == "1":
        verifier = create_verifier_v1(settings)
        # v1 authorization endpoint (no /v2.0 suffix)
        authorization_server = (
            f"https://login.microsoftonline.com/{settings.azure_tenant_id}"
        )
    else:
        verifier = create_verifier(settings)
        # v2 authorization endpoint
        authorization_server = (
            f"https://login.microsoftonline.com/{settings.azure_tenant_id}/v2.0"
        )

    auth = RemoteAuthProvider(
        token_verifier=verifier,
        # Tell MCP clients where to obtain Entra ID tokens
        authorization_servers=[authorization_server],
        base_url=settings.base_url,
        # Scopes advertised to MCP clients. Configured via OAUTH_SCOPES in .env.
        # Defaults to ["openid", "api://<azure_client_id>/access"] if not set.
        scopes_supported=settings.oauth_scopes,
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
    mcp = build_app(settings)
    asgi_app = mcp.http_app(
        transport="streamable-http",
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            )
        ],
    )
    uvicorn.run(asgi_app, host="0.0.0.0", port=settings.port)
