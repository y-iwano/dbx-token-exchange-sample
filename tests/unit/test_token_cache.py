import time

import pytest

from app.auth.token_cache import DatabricksTokenCache, InMemoryTokenCache


# ---------------------------------------------------------------------------
# Interface conformance
# ---------------------------------------------------------------------------


def test_in_memory_cache_is_subclass_of_interface():
    assert issubclass(InMemoryTokenCache, DatabricksTokenCache)


def test_in_memory_cache_instance_is_subclass_of_interface():
    assert isinstance(InMemoryTokenCache(), DatabricksTokenCache)


# ---------------------------------------------------------------------------
# InMemoryTokenCache behaviour
# ---------------------------------------------------------------------------


def test_get_unregistered_sub_returns_none():
    cache = InMemoryTokenCache()
    assert cache.get("unknown-sub") is None


async def test_get_returns_valid_token():
    cache = InMemoryTokenCache()
    await cache.set("user-sub", "dbx-token", time.time() + 3600)
    assert cache.get("user-sub") == "dbx-token"


async def test_get_expired_token_returns_none():
    cache = InMemoryTokenCache()
    await cache.set("user-sub", "dbx-token", time.time() - 1)
    assert cache.get("user-sub") is None


async def test_get_different_sub_returns_none():
    cache = InMemoryTokenCache()
    await cache.set("user-sub-a", "token-a", time.time() + 3600)
    assert cache.get("user-sub-b") is None


async def test_set_overwrites_existing_entry():
    cache = InMemoryTokenCache()
    expires_at = time.time() + 3600
    await cache.set("user-sub", "old-token", expires_at)
    await cache.set("user-sub", "new-token", expires_at)
    assert cache.get("user-sub") == "new-token"


async def test_set_overwrites_expired_entry():
    cache = InMemoryTokenCache()
    await cache.set("user-sub", "old-token", time.time() - 1)
    await cache.set("user-sub", "new-token", time.time() + 3600)
    assert cache.get("user-sub") == "new-token"


@pytest.mark.parametrize("sub", ["user-a", "user-b", "user-c"])
async def test_multiple_subs_are_independent(sub):
    cache = InMemoryTokenCache()
    await cache.set("user-a", "token-a", time.time() + 3600)
    await cache.set("user-b", "token-b", time.time() + 3600)
    await cache.set("user-c", "token-c", time.time() + 3600)
    assert cache.get(sub) == f"token-{sub[-1]}"
