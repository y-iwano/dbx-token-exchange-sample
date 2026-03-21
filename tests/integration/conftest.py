import asyncio
import os
import socket

import httpx
import pytest
import uvicorn
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.providers.proxy import ProxyClient, ProxyProvider

from app.auth.entra_v1 import create_verifier_v1
from app.auth.token_exchange import DatabricksTokenExchanger
from app.config import Settings
from app.main import build_app
from app.proxy.transport import DatabricksTokenExchangeTransport

load_dotenv()


@pytest.fixture
def int_settings():
    """Load Settings from the real .env file."""
    return Settings()


@pytest.fixture
def entra_token():
    """Entra ID v2 access token for integration tests.

    Obtain a token via Azure CLI or MSAL and set ENTRA_ACCESS_TOKEN in .env.
    Example (Azure CLI):
        az account get-access-token --resource <AZURE_CLIENT_ID> --query accessToken -o tsv
    """
    token = os.getenv("ENTRA_ACCESS_TOKEN")
    if not token:
        pytest.skip("Set ENTRA_ACCESS_TOKEN in .env or environment to run this test")
    return token


@pytest.fixture
def entra_token_v1():
    """Entra ID v1 access token for integration tests.

    Obtain a token with:
        uv run python scripts/get_entra_token.py --version 1
    """
    token = os.getenv("ENTRA_ACCESS_TOKEN_V1")
    if not token:
        pytest.skip("Set ENTRA_ACCESS_TOKEN_V1 in .env to run this test")
    return token


@pytest.fixture
def identifier_uri_v1(int_settings) -> str:
    """Application ID URI for the v1 app registration.

    v1 app registrations may use a different App ID URI than the v2 app.
    Set TEST_IDENTIFIER_URI_V1 in .env if they differ; otherwise falls back to
    the v2 identifier_uri from Settings.
    """
    return os.getenv("TEST_IDENTIFIER_URI_V1") or int_settings.identifier_uri


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
async def proxy_url(int_settings):
    """Start the proxy server (v2 verifier) on a free port and yield its base URL."""
    port = _free_port()
    asgi_app = build_app(int_settings).http_app(transport="streamable-http")
    config = uvicorn.Config(asgi_app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


@pytest.fixture
async def proxy_url_v1(int_settings, identifier_uri_v1):
    """Start the proxy server with the v1 verifier on a free port and yield its base URL."""
    port = _free_port()

    verifier = create_verifier_v1(int_settings)
    # v1 app registrations may use a different App ID URI than v2.
    verifier.audience = [identifier_uri_v1]
    auth = RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[
            f"https://login.microsoftonline.com/{int_settings.azure_tenant_id}/v2.0"
        ],
        base_url=f"http://127.0.0.1:{port}",
        scopes_supported=int_settings.oauth_scopes,
    )

    http_client = httpx.AsyncClient()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app: FastMCP):
        yield
        await http_client.aclose()

    exchanger = DatabricksTokenExchanger(int_settings, http_client)
    main = FastMCP("DBX Token Exchange Proxy (v1)", auth=auth, lifespan=lifespan)

    for server_config in int_settings.mcp_servers:
        url = f"{int_settings.databricks_host}{server_config.path}"
        transport = DatabricksTokenExchangeTransport(url, exchanger)
        base_client = ProxyClient(transport)
        provider = ProxyProvider(base_client.new)
        main.add_provider(provider, namespace=server_config.name)

    asgi_app = main.http_app(transport="streamable-http")
    config = uvicorn.Config(asgi_app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task
