from fastmcp.server.auth.providers.azure import AzureJWTVerifier

from app.config import Settings


def create_verifier(settings: Settings) -> AzureJWTVerifier:
    """Create an AzureJWTVerifier configured to validate Entra ID access tokens.

    Uses AzureJWTVerifier which auto-configures JWKS URI, issuer, and audience
    from the app registration details.

    required_scopes validates that the incoming token's ``scp`` claim contains
    the expected scope name (short form, as defined in Azure Portal "Expose an API").

    The verifier accepts both the app GUID and the identifier URI as valid ``aud``
    values. When the app registration uses a custom identifier URI (e.g.
    ``http://localhost.yiwano-demo.net:3100/mcp``), Entra ID v2 access tokens
    carry that URI as ``aud`` rather than the app GUID, so both must be allowed.
    """
    verifier = AzureJWTVerifier(
        client_id=settings.azure_client_id,
        tenant_id=settings.azure_tenant_id,
        required_scopes=settings.required_scopes,
        identifier_uri=settings.identifier_uri,
    )
    # Accept both the app GUID and the identifier URI as valid audiences.
    verifier.audience = [settings.azure_client_id, settings.identifier_uri]
    return verifier
