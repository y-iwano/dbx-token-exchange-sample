from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastmcp.client.transports import ClientTransport, StreamableHttpTransport
from fastmcp.server.dependencies import get_http_headers

from app.auth.token_exchange import DatabricksTokenExchanger, TokenExchangeError

logger = logging.getLogger(__name__)


class DatabricksTokenExchangeTransport(ClientTransport):
    """MCP client transport that exchanges the incoming Entra ID access token
    for a Databricks access token on every session establishment.

    Each MCP session creates a fresh ``StreamableHttpTransport`` targeting the
    configured Databricks Managed MCP endpoint, authenticated with the newly
    exchanged Databricks token.

    The Entra ID token is read from the current HTTP request context via
    ``get_http_headers``, which is populated by FastMCP when handling an
    inbound MCP request.
    """

    def __init__(self, url: str, exchanger: DatabricksTokenExchanger) -> None:
        self._url = url
        self._exchanger = exchanger

    @asynccontextmanager  # type: ignore[override]
    async def connect_session(self, **kwargs: Any) -> AsyncGenerator[Any, None]:
        incoming = get_http_headers(include={"authorization"})
        auth_header = incoming.get("authorization", "")

        # Strip "Bearer " prefix (case-insensitive)
        entra_token = auth_header
        for prefix in ("Bearer ", "bearer "):
            if auth_header.startswith(prefix):
                entra_token = auth_header[len(prefix):]
                break

        if not entra_token:
            raise TokenExchangeError("Missing Authorization header", status_code=401)

        logger.debug("Exchanging Entra ID token for Databricks token (target=%s)", self._url)
        db_token = await self._exchanger.exchange(entra_token)

        # Pass db_token via auth= (not headers=) so that BearerAuth sets the
        # Authorization header per-request, overriding the incoming Entra token
        # that StreamableHttpTransport would otherwise forward via get_http_headers().
        backend = StreamableHttpTransport(
            url=self._url,
            auth=db_token,
        )
        async with backend.connect_session(**kwargs) as session:
            yield session
