from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.exceptions import HTTPException

from app.auth.token_exchange import TokenExchangeError
from app.proxy.transport import DatabricksTokenExchangeTransport


def make_mock_transport(session):
    """Return a mock StreamableHttpTransport whose connect_session yields *session*."""
    mock_instance = MagicMock()

    @asynccontextmanager
    async def mock_connect(**kwargs):
        yield session

    mock_instance.connect_session = mock_connect
    return mock_instance


async def test_connect_session_exchanges_token_and_sets_header():
    exchanger = AsyncMock()
    exchanger.exchange.return_value = "dbx-token"

    transport = DatabricksTokenExchangeTransport(
        url="https://host/api/2.0/mcp/sql",
        exchanger=exchanger,
    )

    mock_session = MagicMock()
    mock_transport_instance = make_mock_transport(mock_session)
    MockTransportClass = MagicMock(return_value=mock_transport_instance)

    with (
        patch(
            "app.proxy.transport.get_http_headers",
            return_value={"authorization": "Bearer entra-token"},
        ),
        patch("app.proxy.transport.StreamableHttpTransport", MockTransportClass),
    ):
        async with transport.connect_session() as session:
            assert session is mock_session

    exchanger.exchange.assert_awaited_once_with("entra-token")
    MockTransportClass.assert_called_once_with(
        url="https://host/api/2.0/mcp/sql",
        auth="dbx-token",
    )


async def test_missing_auth_header_raises():
    exchanger = AsyncMock()
    transport = DatabricksTokenExchangeTransport(
        url="https://host/api/2.0/mcp/sql",
        exchanger=exchanger,
    )

    with patch("app.proxy.transport.get_http_headers", return_value={}):
        with pytest.raises(TokenExchangeError) as exc_info:
            async with transport.connect_session():
                pass

    assert exc_info.value.status_code == 401
    exchanger.exchange.assert_not_awaited()


@pytest.mark.parametrize(
    "auth_header, expected_token",
    [
        ("Bearer my-entra-token", "my-entra-token"),
        ("bearer my-entra-token", "my-entra-token"),
    ],
)
async def test_bearer_prefix_stripping(auth_header, expected_token):
    exchanger = AsyncMock()
    exchanger.exchange.return_value = "dbx-token"

    transport = DatabricksTokenExchangeTransport(
        url="https://host/api/2.0/mcp/sql",
        exchanger=exchanger,
    )

    mock_transport_instance = make_mock_transport(MagicMock())
    MockTransportClass = MagicMock(return_value=mock_transport_instance)

    with (
        patch(
            "app.proxy.transport.get_http_headers",
            return_value={"authorization": auth_header},
        ),
        patch("app.proxy.transport.StreamableHttpTransport", MockTransportClass),
    ):
        async with transport.connect_session():
            pass

    exchanger.exchange.assert_awaited_once_with(expected_token)


@pytest.mark.parametrize(
    "token_status, expected_http_status",
    [
        (400, 502),
        (401, 502),
        (500, 503),
        (503, 503),
        (None, 503),  # network error (no status_code)
    ],
)
async def test_exchange_error_mapped_to_http_exception(token_status, expected_http_status):
    exchanger = AsyncMock()
    exchanger.exchange.side_effect = TokenExchangeError(
        "exchange failed", status_code=token_status
    )

    transport = DatabricksTokenExchangeTransport(
        url="https://host/api/2.0/mcp/sql",
        exchanger=exchanger,
    )

    with (
        patch(
            "app.proxy.transport.get_http_headers",
            return_value={"authorization": "Bearer entra-token"},
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        async with transport.connect_session():
            pass

    assert exc_info.value.status_code == expected_http_status
