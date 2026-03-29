from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


class DatabricksTokenCache(ABC):
    """Interface for caching Databricks access tokens keyed by Entra ID ``sub`` claim."""

    @abstractmethod
    def get(self, sub: str) -> str | None:
        """Return the cached token if it has not expired, else ``None``."""

    @abstractmethod
    async def set(self, sub: str, token: str, expires_at: float) -> None:
        """Store *token* under *sub* with expiry *expires_at* (UNIX timestamp)."""


@dataclass
class _CachedToken:
    token: str
    expires_at: float  # UNIX timestamp


class InMemoryTokenCache(DatabricksTokenCache):
    """In-memory implementation of :class:`DatabricksTokenCache`.

    Tokens are stored in a plain dict protected by an :class:`asyncio.Lock`.
    Expired entries are not actively evicted; they become invisible on the next
    ``get`` call and are overwritten on the next ``set``.
    """

    def __init__(self) -> None:
        self._cache: dict[str, _CachedToken] = {}
        self._lock = asyncio.Lock()

    def get(self, sub: str) -> str | None:
        entry = self._cache.get(sub)
        if entry is None or time.time() >= entry.expires_at:
            return None
        return entry.token

    async def set(self, sub: str, token: str, expires_at: float) -> None:
        async with self._lock:
            self._cache[sub] = _CachedToken(token=token, expires_at=expires_at)
