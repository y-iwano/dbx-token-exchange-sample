import os

import httpx
import pytest
from fastmcp import Client

pytestmark = pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "true",
    reason="Set INTEGRATION_TESTS=true to run",
)


async def test_invalid_token_returns_401(proxy_url):
    """Request with an invalid Bearer token is rejected with 401."""
    async with httpx.AsyncClient() as http:
        resp = await http.post(
            f"{proxy_url}/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers={
                "Authorization": "Bearer invalid-token",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
    assert resp.status_code == 401


async def test_tools_list_with_valid_token(proxy_url, entra_token, int_settings):
    """Valid Entra token returns tool list with configured namespace prefix."""
    async with Client(f"{proxy_url}/mcp", auth=entra_token) as client:
        tools = await client.list_tools()

    assert len(tools) > 0

    tool_names = [t.name for t in tools]
    configured_namespaces = [s.name for s in int_settings.mcp_servers]
    assert any(
        name.startswith(f"{ns}_")
        for name in tool_names
        for ns in configured_namespaces
    ), f"Expected tools with namespace prefix, got: {tool_names}"


async def test_tools_list_multiple_backends(proxy_url, entra_token, int_settings):
    """When multiple backends are configured, tools from all backends appear."""
    if len(int_settings.mcp_servers) < 2:
        pytest.skip("Requires at least 2 entries in MCP_SERVERS")

    async with Client(f"{proxy_url}/mcp", auth=entra_token) as client:
        tools = await client.list_tools()

    tool_names = [t.name for t in tools]
    for server_cfg in int_settings.mcp_servers:
        assert any(name.startswith(f"{server_cfg.name}_") for name in tool_names), (
            f"No tools with namespace '{server_cfg.name}' found. "
            f"Available tools: {tool_names}"
        )
