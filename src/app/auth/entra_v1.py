from fastmcp.server.auth.providers.azure import AzureJWTVerifier

from app.config import Settings


def create_verifier_v1(settings: Settings) -> AzureJWTVerifier:
    """Create an AzureJWTVerifier configured to validate Entra ID v1 access tokens.

    v1 tokens are issued by the v1 authorization endpoint and differ from v2 in three ways:

    - ``iss``: ``https://sts.windows.net/{tenant_id}/``
      (v2 uses ``https://login.microsoftonline.com/{tenant_id}/v2.0``)
    - ``aud``: identifier_uri only — the app GUID is NOT a valid audience in v1 tokens.
    - JWKS URI: ``/discovery/keys`` (no ``/v2.0/`` path segment).

    Use this when MCP clients obtain tokens via the v1 authorization endpoint, which
    is common for legacy Azure AD configurations or internal systems where the app
    registration's ``accessTokenAcceptedVersion`` is set to ``null`` or ``1``.
    """
    verifier = AzureJWTVerifier(
        client_id=settings.azure_client_id,
        tenant_id=settings.azure_tenant_id,
        required_scopes=settings.required_scopes,
        identifier_uri=settings.identifier_uri,
    )
    # Override issuer: v1 tokens are issued by sts.windows.net, not login.microsoftonline.com/v2.0.
    verifier.issuer = f"https://sts.windows.net/{settings.azure_tenant_id}/"

    # v1 tokens carry identifier_uri as aud; the app GUID is NOT included.
    verifier.audience = [settings.identifier_uri]

    # Override JWKS URI to use the v1 discovery endpoint (no /v2.0/ segment).
    verifier.jwks_uri = (
        f"https://login.microsoftonline.com/{settings.azure_tenant_id}/discovery/keys"
    )
    return verifier
