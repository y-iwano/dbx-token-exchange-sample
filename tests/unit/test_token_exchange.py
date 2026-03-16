from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.auth.token_exchange import DatabricksTokenExchanger, TokenExchangeError

TOKEN_URL = "https://test.azuredatabricks.net/oidc/v1/token"


@pytest.fixture
async def exchanger(settings):
    async with httpx.AsyncClient() as client:
        yield DatabricksTokenExchanger(settings, client)


async def test_exchange_success(exchanger, respx_mock):
    respx_mock.post(TOKEN_URL).respond(
        200, json={"access_token": "dbx-token", "token_type": "Bearer"}
    )
    token = await exchanger.exchange("entra-token")
    assert token == "dbx-token"


async def test_exchange_400_no_retry(exchanger, respx_mock):
    respx_mock.post(TOKEN_URL).respond(400, json={"error": "invalid_grant"})
    with pytest.raises(TokenExchangeError) as exc_info:
        await exchanger.exchange("bad-token")
    assert exc_info.value.status_code == 400
    assert respx_mock.calls.call_count == 1


async def test_exchange_401_no_retry(exchanger, respx_mock):
    respx_mock.post(TOKEN_URL).respond(401, json={"error": "unauthorized"})
    with pytest.raises(TokenExchangeError) as exc_info:
        await exchanger.exchange("bad-token")
    assert exc_info.value.status_code == 401
    assert respx_mock.calls.call_count == 1


async def test_exchange_500_retry_then_success(exchanger, respx_mock):
    route = respx_mock.post(TOKEN_URL)
    route.side_effect = [
        httpx.Response(500, json={"error": "server_error"}),
        httpx.Response(200, json={"access_token": "dbx-token", "token_type": "Bearer"}),
    ]
    with patch("asyncio.sleep", AsyncMock()):
        token = await exchanger.exchange("entra-token")
    assert token == "dbx-token"
    assert respx_mock.calls.call_count == 2


async def test_exchange_500_all_retries_exhausted(exchanger, respx_mock):
    respx_mock.post(TOKEN_URL).respond(500, json={"error": "server_error"})
    with patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(TokenExchangeError):
            await exchanger.exchange("entra-token")
    assert respx_mock.calls.call_count == 3


async def test_exchange_network_error(exchanger, respx_mock):
    respx_mock.post(TOKEN_URL).mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    with patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(TokenExchangeError):
            await exchanger.exchange("entra-token")
    assert respx_mock.calls.call_count == 3


async def test_exchange_missing_access_token(exchanger, respx_mock):
    respx_mock.post(TOKEN_URL).respond(200, json={"token_type": "Bearer"})
    with pytest.raises(TokenExchangeError):
        await exchanger.exchange("entra-token")


async def test_exchange_501_no_retry(exchanger, respx_mock):
    respx_mock.post(TOKEN_URL).respond(501, json={"error": "not_implemented"})
    with pytest.raises(TokenExchangeError) as exc_info:
        await exchanger.exchange("entra-token")
    assert exc_info.value.status_code == 501
    assert respx_mock.calls.call_count == 1


@pytest.mark.parametrize("status", [502, 503, 504])
async def test_exchange_retriable_5xx_retries(status, exchanger, respx_mock):
    route = respx_mock.post(TOKEN_URL)
    route.side_effect = [
        httpx.Response(status, json={"error": "server_error"}),
        httpx.Response(200, json={"access_token": "dbx-token", "token_type": "Bearer"}),
    ]
    with patch("asyncio.sleep", AsyncMock()):
        token = await exchanger.exchange("entra-token")
    assert token == "dbx-token"
    assert respx_mock.calls.call_count == 2


async def test_exchange_503_respects_retry_after(exchanger, respx_mock):
    route = respx_mock.post(TOKEN_URL)
    route.side_effect = [
        httpx.Response(503, headers={"Retry-After": "5"}, json={"error": "unavailable"}),
        httpx.Response(200, json={"access_token": "dbx-token", "token_type": "Bearer"}),
    ]
    mock_sleep = AsyncMock()
    with patch("asyncio.sleep", mock_sleep):
        token = await exchanger.exchange("entra-token")
    assert token == "dbx-token"
    mock_sleep.assert_awaited_once_with(5.0)
