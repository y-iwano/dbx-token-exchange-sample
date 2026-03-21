"""Integration tests for entra_v1.create_verifier_v1.

Requires a real Entra ID v1 access token.  Obtain one with:

    uv run python scripts/get_entra_token.py --version 1

then ensure ENTRA_ACCESS_TOKEN_V1 is set in .env.
"""

import os

import pytest

from app.auth.entra_v1 import create_verifier_v1

pytestmark = pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "true",
    reason="Set INTEGRATION_TESTS=true to run",
)


@pytest.fixture
def entra_token_v1():
    token = os.getenv("ENTRA_ACCESS_TOKEN_V1")
    if not token:
        pytest.skip("Set ENTRA_ACCESS_TOKEN_V1 in .env to run this test")
    return token


async def test_verify_token_v1_succeeds(int_settings, entra_token_v1, identifier_uri_v1):
    """A real Entra ID v1 token is accepted by create_verifier_v1."""
    verifier = create_verifier_v1(int_settings)
    verifier.audience = [identifier_uri_v1]
    result = await verifier.verify_token(entra_token_v1)
    assert result is not None


async def test_verify_token_v1_rejects_garbage(int_settings, identifier_uri_v1):
    """A malformed token is rejected by the v1 verifier."""
    verifier = create_verifier_v1(int_settings)
    verifier.audience = [identifier_uri_v1]
    result = await verifier.verify_token("this-is-not-a-jwt")
    assert result is None


async def test_verify_token_v2_rejected_by_v1_verifier(int_settings, identifier_uri_v1):
    """A v2 token should NOT be accepted by the v1 verifier (wrong issuer/audience)."""
    v2_token = os.getenv("ENTRA_ACCESS_TOKEN")
    if not v2_token:
        pytest.skip("Set ENTRA_ACCESS_TOKEN in .env to run this test")
    verifier = create_verifier_v1(int_settings)
    verifier.audience = [identifier_uri_v1]
    result = await verifier.verify_token(v2_token)
    assert result is None
