import os

import httpx
import pytest

from app.auth.token_exchange import DatabricksTokenExchanger, TokenExchangeError

pytestmark = pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "true",
    reason="Set INTEGRATION_TESTS=true to run",
)


async def test_token_exchange_with_valid_entra_token(int_settings, entra_token):
    """Valid Entra ID access token is exchanged for a Databricks access token."""
    async with httpx.AsyncClient() as client:
        exchanger = DatabricksTokenExchanger(int_settings, client)
        db_token = await exchanger.exchange(entra_token)

    assert isinstance(db_token, str)
    assert len(db_token) > 0


async def test_token_exchange_with_invalid_token(int_settings):
    """A malformed token is rejected by Databricks with 400 or 401."""
    async with httpx.AsyncClient() as client:
        exchanger = DatabricksTokenExchanger(int_settings, client)
        with pytest.raises(TokenExchangeError) as exc_info:
            await exchanger.exchange("this-is-not-a-valid-jwt")

    assert exc_info.value.status_code in (400, 401)
