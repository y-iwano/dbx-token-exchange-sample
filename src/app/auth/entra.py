from fastmcp.server.auth.providers.jwt import JWTVerifier

from app.config import Settings


def create_verifier(settings: Settings) -> JWTVerifier:
    """Create a JWTVerifier configured to validate Entra ID access tokens."""
    return JWTVerifier(
        jwks_uri=(
            f"https://login.microsoftonline.com"
            f"/{settings.azure_tenant_id}/discovery/v2.0/keys"
        ),
        issuer=f"https://login.microsoftonline.com/{settings.azure_tenant_id}/v2.0",
        # Accept both bare Client ID and api:// URI forms
        audience=[
            settings.azure_client_id,
            f"api://{settings.azure_client_id}",
        ],
    )
