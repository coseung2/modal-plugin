import pytest

from modal_plugin.config import Settings


def test_remote_http_fails_closed_without_auth() -> None:
    settings = Settings(public_base_url="https://modal.example")
    with pytest.raises(RuntimeError, match="Refusing to start unauthenticated"):
        settings.validate_http_security()


def test_oidc_resource_and_transport_security() -> None:
    settings = Settings(
        public_base_url="https://modal.example",
        oauth_issuer_url="https://id.example/tenant/",
        oauth_jwks_url="https://id.example/.well-known/jwks.json",
        oauth_scopes="openid modal:manage",
    )
    assert settings.remote_auth_enabled() is True
    assert settings.mcp_resource_url() == "https://modal.example/mcp"
    assert settings.oauth_scope_list() == ["openid", "modal:manage"]
    settings.validate_http_security()

    security = settings.transport_security()
    assert security.allowed_hosts == ["modal.example"]
    assert security.allowed_origins == ["https://modal.example"]


def test_partial_oauth_configuration_is_rejected() -> None:
    settings = Settings(oauth_issuer_url="https://id.example")
    with pytest.raises(ValueError, match="Set both"):
        settings.remote_auth_enabled()


def test_insecure_http_requires_explicit_opt_in() -> None:
    Settings(allow_insecure_http=True).validate_http_security()
