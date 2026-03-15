from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
_SUBJECT_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:jwt"

# Retry config: up to 3 attempts with exponential backoff (1 s, 2 s, 4 s)
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0


class TokenExchangeError(Exception):  # pylint: disable=too-few-public-methods
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DatabricksTokenExchanger:  # pylint: disable=too-few-public-methods
    """Exchanges an Entra ID access token for a Databricks access token via RFC 8693."""

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http_client = http_client
        self._token_url = f"{settings.databricks_host}/oidc/v1/token"

    async def exchange(self, entra_token: str) -> str:
        """Exchange *entra_token* for a Databricks access token.

        Returns:
            Databricks access token string.

        Raises:
            TokenExchangeError: On authentication failure or exhausted retries.
        """
        data = {
            "grant_type": _GRANT_TYPE,
            "subject_token": entra_token,
            "subject_token_type": _SUBJECT_TOKEN_TYPE,
            "scope": "all-apis",
        }

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await self._http_client.post(self._token_url, data=data)
            except httpx.RequestError as exc:
                last_exc = TokenExchangeError(f"Network error during token exchange: {exc}")
                logger.warning(
                    "Token exchange network error (attempt %d/%d)", attempt + 1, _MAX_RETRIES
                )
                await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
                continue

            if resp.status_code in (400, 401):
                # Client-side errors — no retry
                error = _extract_error(resp)
                logger.warning("Token exchange rejected: %s (status=%d)", error, resp.status_code)
                raise TokenExchangeError(
                    f"Token exchange failed: {error}",
                    status_code=resp.status_code,
                )

            if resp.status_code >= 500:
                last_exc = TokenExchangeError(
                    f"Token exchange server error (status={resp.status_code})",
                    status_code=resp.status_code,
                )
                logger.warning(
                    "Token exchange server error %d (attempt %d/%d)",
                    resp.status_code,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
                continue

            try:
                resp.raise_for_status()
                token: str = resp.json()["access_token"]
                logger.debug("Token exchange succeeded")
                return token
            except (KeyError, ValueError) as exc:
                raise TokenExchangeError(f"Unexpected token exchange response: {exc}") from exc

        raise last_exc or TokenExchangeError("Token exchange failed after retries")


def _extract_error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return body.get("error_description") or body.get("error") or resp.text
    except ValueError:
        return resp.text
