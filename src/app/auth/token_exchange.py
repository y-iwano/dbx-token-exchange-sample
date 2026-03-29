from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

import httpx

from app.auth.token_cache import DatabricksTokenCache
from app.config import Settings

logger = logging.getLogger(__name__)

_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
_SUBJECT_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:jwt"  # nosec B105

# Retry config: up to 3 attempts with exponential backoff (1 s, 2 s, 4 s)
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0

# Only transient 5xx errors are retried. Permanent errors (501, 505, …) are
# not expected from an OIDC token endpoint but are raised immediately if seen.
_RETRIABLE_5XX = {500, 502, 503, 504}


class TokenExchangeError(Exception):  # pylint: disable=too-few-public-methods
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DatabricksTokenExchanger:  # pylint: disable=too-few-public-methods
    """Exchanges an Entra ID access token for a Databricks access token via RFC 8693.

    Successful exchanges are cached by the ``sub`` claim of the Entra ID JWT.
    Subsequent calls for the same user return the cached token until it expires.
    """

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient,
        cache: DatabricksTokenCache,
    ) -> None:
        self._settings = settings
        self._http_client = http_client
        self._cache = cache
        self._token_url = f"{settings.databricks_host}/oidc/v1/token"

    async def exchange(self, entra_token: str) -> str:
        """Exchange *entra_token* for a Databricks access token.

        The ``sub`` claim is extracted from the Entra ID JWT (without re-verification,
        as FastMCP has already validated the signature) and used as the cache key.

        Returns:
            Databricks access token string.

        Raises:
            TokenExchangeError: If the sub claim is missing, authentication fails,
                or all retries are exhausted.
        """
        sub = _extract_sub(entra_token)
        if sub is None:
            raise TokenExchangeError(
                "Unable to extract sub claim from Entra ID token",
                status_code=401,
            )

        cached = self._cache.get(sub)
        if cached is not None:
            logger.debug("Token cache hit")
            return cached

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
                logger.error("Token exchange rejected: %s (status=%d)", error, resp.status_code)
                raise TokenExchangeError(
                    f"Token exchange failed: {error}",
                    status_code=resp.status_code,
                )

            if resp.status_code in _RETRIABLE_5XX:
                last_exc = TokenExchangeError(
                    f"Token exchange server error (status={resp.status_code})",
                    status_code=resp.status_code,
                )
                logger.error(
                    "Token exchange server error %d (attempt %d/%d)",
                    resp.status_code,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else _BACKOFF_BASE * (2**attempt)
                await asyncio.sleep(wait)
                continue

            if resp.status_code >= 500:
                # Non-retriable 5xx (e.g. 501 Not Implemented, 505 HTTP Version Not Supported)
                error = _extract_error(resp)
                logger.error(
                    "Token exchange non-retriable error %d: %s", resp.status_code, error
                )
                raise TokenExchangeError(
                    f"Token exchange failed (non-retriable): {error}",
                    status_code=resp.status_code,
                )

            try:
                resp.raise_for_status()
                body = resp.json()
                token: str = body["access_token"]
                expires_at = (
                    time.time()
                    + body.get("expires_in", 3600)
                    - self._settings.dbx_token_cache_ttl_buffer
                )
                await self._cache.set(sub, token, expires_at)
                logger.debug("Token exchange succeeded")
                return token
            except (KeyError, ValueError) as exc:
                raise TokenExchangeError(f"Unexpected token exchange response: {exc}") from exc

        raise last_exc or TokenExchangeError("Token exchange failed after retries")


def _extract_sub(entra_token: str) -> str | None:
    """Extract the ``sub`` claim from a JWT payload without signature verification.

    The token has already been verified by FastMCP's ``AzureJWTVerifier``.
    Only the Base64url-encoded payload segment is decoded here.

    Returns ``None`` if the token is malformed or the claim is absent/empty.
    """
    try:
        parts = entra_token.split(".")
        if len(parts) != 3:
            return None
        # Restore base64url padding
        rem = len(parts[1]) % 4
        padded = parts[1] + "=" * (4 - rem if rem else 0)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        sub = payload.get("sub")
        return sub if isinstance(sub, str) and sub else None
    except Exception:  # pylint: disable=broad-except
        return None


def _extract_error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return body.get("error_description") or body.get("error") or resp.text
    except ValueError:
        return resp.text
