import pytest

from app.auth.entra_v1 import create_verifier_v1
from app.config import Settings


@pytest.fixture
def settings_with_identifier_uri(valid_env, monkeypatch) -> Settings:
    monkeypatch.setenv("IDENTIFIER_URI", "api://my-app-uri")
    return Settings(_env_file=None)


class TestCreateVerifierV1:
    def test_issuer_is_sts_windows_net(self, settings):
        verifier = create_verifier_v1(settings)
        assert verifier.issuer == f"https://sts.windows.net/{settings.azure_tenant_id}/"

    def test_jwks_uri_has_no_v2_segment(self, settings):
        verifier = create_verifier_v1(settings)
        assert verifier.jwks_uri == (
            f"https://login.microsoftonline.com/{settings.azure_tenant_id}/discovery/keys"
        )
        assert "v2.0" not in verifier.jwks_uri

    def test_audience_contains_only_identifier_uri(self, settings):
        verifier = create_verifier_v1(settings)
        # v1 tokens do NOT carry the app GUID as aud
        assert settings.azure_client_id not in verifier.audience
        assert settings.identifier_uri in verifier.audience

    def test_audience_does_not_contain_app_guid(self, settings):
        verifier = create_verifier_v1(settings)
        assert settings.azure_client_id not in verifier.audience

    def test_audience_with_custom_identifier_uri(self, settings_with_identifier_uri):
        s = settings_with_identifier_uri
        verifier = create_verifier_v1(s)
        assert verifier.audience == ["api://my-app-uri"]
        assert s.azure_client_id not in verifier.audience

    def test_required_scopes_forwarded(self, valid_env, monkeypatch):
        monkeypatch.setenv("REQUIRED_SCOPES", '["access"]')
        s = Settings(_env_file=None)
        verifier = create_verifier_v1(s)
        assert verifier.required_scopes == ["access"]

    def test_required_scopes_empty_when_not_set(self, settings):
        # AzureJWTVerifier normalises None → [] internally
        verifier = create_verifier_v1(settings)
        assert not verifier.required_scopes

    def test_v1_issuer_differs_from_v2(self, settings):
        from app.auth.entra import create_verifier as create_verifier_v2

        v1 = create_verifier_v1(settings)
        v2 = create_verifier_v2(settings)
        assert v1.issuer != v2.issuer
        assert "sts.windows.net" in v1.issuer
        assert "login.microsoftonline.com" in v2.issuer

    def test_v1_jwks_differs_from_v2(self, settings):
        from app.auth.entra import create_verifier as create_verifier_v2

        v1 = create_verifier_v1(settings)
        v2 = create_verifier_v2(settings)
        assert v1.jwks_uri != v2.jwks_uri
        assert "v2.0" not in v1.jwks_uri
        assert "v2.0" in v2.jwks_uri

    def test_v1_audience_subset_of_v2(self, settings):
        """v1 audience is identifier_uri only; v2 also includes the app GUID."""
        from app.auth.entra import create_verifier as create_verifier_v2

        v1 = create_verifier_v1(settings)
        v2 = create_verifier_v2(settings)
        assert settings.azure_client_id not in v1.audience
        assert settings.azure_client_id in v2.audience
