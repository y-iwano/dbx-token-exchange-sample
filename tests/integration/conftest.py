import asyncio
import os
import socket

import pytest
import uvicorn
from dotenv import load_dotenv

from app.config import Settings
from app.main import build_app

load_dotenv()


@pytest.fixture
def int_settings():
    """Load Settings from the real .env file."""
    return Settings()


@pytest.fixture
def entra_token():
    """Entra ID access token for integration tests.

    Obtain a token via Azure CLI or MSAL and set ENTRA_ACCESS_TOKEN in .env.
    Example (Azure CLI):
        az account get-access-token --resource <AZURE_CLIENT_ID> --query accessToken -o tsv
    """
    token = os.getenv("ENTRA_ACCESS_TOKEN")
    if not token:
        pytest.skip("Set ENTRA_ACCESS_TOKEN in .env or environment to run this test")
    return token


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
async def proxy_url(int_settings):
    """Start the proxy server on a free port and yield its base URL."""
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
