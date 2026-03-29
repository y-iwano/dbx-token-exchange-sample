import base64
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.auth.token_cache import DatabricksTokenCache, InMemoryTokenCache
from app.auth.token_exchange import DatabricksTokenExchanger, TokenExchangeError

TOKEN_URL = "https://test.azuredatabricks.net/oidc/v1/token"
_SUCCESS_RESPONSE = {"access_token": "dbx-token", "token_type": "Bearer", "expires_in": 3600}


def _make_jwt(sub: str = "test-user-sub") -> str:
    """Build a minimal JWT-shaped token with the given sub claim.

    The signature segment is a placeholder — FastMCP verifies the real token
    before exchange() is called, so unit tests only need a correctly-shaped JWT.
    """
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    payload_bytes = json.dumps({"sub": sub}).encode()
    payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


@pytest.fixture
async def exchanger(settings):
    async with httpx.AsyncClient() as client:
        yield DatabricksTokenExchanger(settings, client, InMemoryTokenCache())


# ---------------------------------------------------------------------------
# Basic token exchange (cache miss path)
# ---------------------------------------------------------------------------


async def test_exchange_success(exchanger, respx_mock):
    respx_mock.post(TOKEN_URL).respond(200, json=_SUCCESS_RESPONSE)
    token = await exchanger.exchange(_make_jwt())
    assert token == "dbx-token"


async def test_exchange_400_no_retry(exchanger, respx_mock):
    respx_mock.post(TOKEN_URL).respond(400, json={"error": "invalid_grant"})
    with pytest.raises(TokenExchangeError) as exc_info:
        await exchanger.exchange(_make_jwt())
    assert exc_info.value.status_code == 400
    assert respx_mock.calls.call_count == 1


async def test_exchange_401_no_retry(exchanger, respx_mock):
    respx_mock.post(TOKEN_URL).respond(401, json={"error": "unauthorized"})
    with pytest.raises(TokenExchangeError) as exc_info:
        await exchanger.exchange(_make_jwt())
    assert exc_info.value.status_code == 401
    assert respx_mock.calls.call_count == 1


async def test_exchange_500_retry_then_success(exchanger, respx_mock):
    route = respx_mock.post(TOKEN_URL)
    route.side_effect = [
        httpx.Response(500, json={"error": "server_error"}),
        httpx.Response(200, json=_SUCCESS_RESPONSE),
    ]
    with patch("asyncio.sleep", AsyncMock()):
        token = await exchanger.exchange(_make_jwt())
    assert token == "dbx-token"
    assert respx_mock.calls.call_count == 2


async def test_exchange_500_all_retries_exhausted(exchanger, respx_mock):
    respx_mock.post(TOKEN_URL).respond(500, json={"error": "server_error"})
    with patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(TokenExchangeError):
            await exchanger.exchange(_make_jwt())
    assert respx_mock.calls.call_count == 3


async def test_exchange_network_error(exchanger, respx_mock):
    respx_mock.post(TOKEN_URL).mock(side_effect=httpx.ConnectError("connection refused"))
    with patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(TokenExchangeError):
            await exchanger.exchange(_make_jwt())
    assert respx_mock.calls.call_count == 3


async def test_exchange_missing_access_token(exchanger, respx_mock):
    respx_mock.post(TOKEN_URL).respond(200, json={"token_type": "Bearer"})
    with pytest.raises(TokenExchangeError):
        await exchanger.exchange(_make_jwt())


async def test_exchange_501_no_retry(exchanger, respx_mock):
    respx_mock.post(TOKEN_URL).respond(501, json={"error": "not_implemented"})
    with pytest.raises(TokenExchangeError) as exc_info:
        await exchanger.exchange(_make_jwt())
    assert exc_info.value.status_code == 501
    assert respx_mock.calls.call_count == 1


@pytest.mark.parametrize("status", [502, 503, 504])
async def test_exchange_retriable_5xx_retries(status, exchanger, respx_mock):
    route = respx_mock.post(TOKEN_URL)
    route.side_effect = [
        httpx.Response(status, json={"error": "server_error"}),
        httpx.Response(200, json=_SUCCESS_RESPONSE),
    ]
    with patch("asyncio.sleep", AsyncMock()):
        token = await exchanger.exchange(_make_jwt())
    assert token == "dbx-token"
    assert respx_mock.calls.call_count == 2


async def test_exchange_503_respects_retry_after(exchanger, respx_mock):
    route = respx_mock.post(TOKEN_URL)
    route.side_effect = [
        httpx.Response(503, headers={"Retry-After": "5"}, json={"error": "unavailable"}),
        httpx.Response(200, json=_SUCCESS_RESPONSE),
    ]
    mock_sleep = AsyncMock()
    with patch("asyncio.sleep", mock_sleep):
        token = await exchanger.exchange(_make_jwt())
    assert token == "dbx-token"
    mock_sleep.assert_awaited_once_with(5.0)


# ---------------------------------------------------------------------------
# sub extraction
# ---------------------------------------------------------------------------


async def test_exchange_missing_sub_raises_error(settings, respx_mock):
    jwt_no_sub = (
        base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
        + "."
        + base64.urlsafe_b64encode(b'{"iss":"test"}').rstrip(b"=").decode()
        + ".fakesig"
    )
    async with httpx.AsyncClient() as client:
        ex = DatabricksTokenExchanger(settings, client, InMemoryTokenCache())
    with pytest.raises(TokenExchangeError):
        await ex.exchange(jwt_no_sub)
    assert respx_mock.calls.call_count == 0


async def test_exchange_non_jwt_string_raises_error(settings, respx_mock):
    async with httpx.AsyncClient() as client:
        ex = DatabricksTokenExchanger(settings, client, InMemoryTokenCache())
    with pytest.raises(TokenExchangeError):
        await ex.exchange("not-a-jwt")
    assert respx_mock.calls.call_count == 0


# ---------------------------------------------------------------------------
# Caching behaviour
# ---------------------------------------------------------------------------


async def test_exchange_returns_cached_token(settings, respx_mock):
    """Cache hit: no HTTP request should be issued."""
    cache = InMemoryTokenCache()
    await cache.set("user-123", "cached-dbx-token", time.time() + 3600)

    async with httpx.AsyncClient() as client:
        ex = DatabricksTokenExchanger(settings, client, cache)
    token = await ex.exchange(_make_jwt("user-123"))

    assert token == "cached-dbx-token"
    assert respx_mock.calls.call_count == 0


async def test_exchange_after_cache_expiry_hits_endpoint(settings, respx_mock):
    """Expired cache entry causes a fresh HTTP exchange."""
    cache = InMemoryTokenCache()
    await cache.set("user-123", "old-token", time.time() - 1)

    respx_mock.post(TOKEN_URL).respond(200, json=_SUCCESS_RESPONSE)

    async with httpx.AsyncClient() as client:
        ex = DatabricksTokenExchanger(settings, client, cache)
        token = await ex.exchange(_make_jwt("user-123"))

    assert token == "dbx-token"
    assert respx_mock.calls.call_count == 1


async def test_exchange_different_subs_cached_independently(settings, respx_mock):
    """Each user's token is cached under their own sub key."""
    cache = InMemoryTokenCache()
    # user-a is already cached
    await cache.set("user-a", "token-a", time.time() + 3600)

    # user-b triggers HTTP exchange
    respx_mock.post(TOKEN_URL).respond(200, json=_SUCCESS_RESPONSE)

    async with httpx.AsyncClient() as client:
        ex = DatabricksTokenExchanger(settings, client, cache)

        token_a = await ex.exchange(_make_jwt("user-a"))
        assert token_a == "token-a"
        assert respx_mock.calls.call_count == 0

        token_b = await ex.exchange(_make_jwt("user-b"))
        assert token_b == "dbx-token"
        assert respx_mock.calls.call_count == 1


async def test_exchange_stores_token_in_cache_after_exchange(settings, respx_mock):
    """After a successful exchange the token must be retrievable from the cache."""
    cache = InMemoryTokenCache()
    respx_mock.post(TOKEN_URL).respond(200, json=_SUCCESS_RESPONSE)

    async with httpx.AsyncClient() as client:
        ex = DatabricksTokenExchanger(settings, client, cache)
        await ex.exchange(_make_jwt("user-123"))

    assert cache.get("user-123") == "dbx-token"


async def test_exchange_uses_cache_interface(settings, respx_mock):
    """exchange() interacts with the cache through the DatabricksTokenCache interface."""
    mock_cache = MagicMock(spec=DatabricksTokenCache)
    mock_cache.get.return_value = None  # cache miss
    mock_cache.set = AsyncMock()

    respx_mock.post(TOKEN_URL).respond(200, json=_SUCCESS_RESPONSE)

    async with httpx.AsyncClient() as client:
        ex = DatabricksTokenExchanger(settings, client, mock_cache)
        token = await ex.exchange(_make_jwt("user-123"))

    assert token == "dbx-token"
    mock_cache.get.assert_called_once_with("user-123")
    set_args = mock_cache.set.call_args.args
    assert set_args[0] == "user-123"  # sub
    assert set_args[1] == "dbx-token"  # token


async def test_exchange_second_call_uses_cache(settings, respx_mock):
    """Two consecutive calls with the same JWT produce exactly one HTTP request."""
    cache = InMemoryTokenCache()
    respx_mock.post(TOKEN_URL).respond(200, json=_SUCCESS_RESPONSE)

    async with httpx.AsyncClient() as client:
        ex = DatabricksTokenExchanger(settings, client, cache)
        jwt = _make_jwt("user-123")

        token1 = await ex.exchange(jwt)
        token2 = await ex.exchange(jwt)

    assert token1 == token2 == "dbx-token"
    assert respx_mock.calls.call_count == 1  # HTTP called only once


async def test_exchange_cache_hit_does_not_call_set(settings, respx_mock):
    """On a cache hit, set() must not be called and no HTTP request must be made."""
    mock_cache = MagicMock(spec=DatabricksTokenCache)
    mock_cache.get.return_value = "cached-dbx-token"  # cache hit
    mock_cache.set = AsyncMock()

    async with httpx.AsyncClient() as client:
        ex = DatabricksTokenExchanger(settings, client, mock_cache)
        token = await ex.exchange(_make_jwt("user-123"))

    assert token == "cached-dbx-token"
    mock_cache.set.assert_not_awaited()
    assert respx_mock.calls.call_count == 0


async def test_exchange_expires_at_uses_expires_in_and_ttl_buffer(settings, respx_mock):
    """expires_at stored in cache equals time.time() + expires_in - ttl_buffer."""
    mock_cache = MagicMock(spec=DatabricksTokenCache)
    mock_cache.get.return_value = None
    mock_cache.set = AsyncMock()

    frozen_now = 1_000_000.0
    response = {"access_token": "dbx-token", "token_type": "Bearer", "expires_in": 3600}
    respx_mock.post(TOKEN_URL).respond(200, json=response)

    with patch("app.auth.token_exchange.time") as mock_time:
        mock_time.time.return_value = frozen_now
        async with httpx.AsyncClient() as client:
            ex = DatabricksTokenExchanger(settings, client, mock_cache)
            await ex.exchange(_make_jwt("user-123"))

    _, _, expires_at = mock_cache.set.call_args.args
    expected = frozen_now + 3600 - settings.dbx_token_cache_ttl_buffer
    assert expires_at == expected
