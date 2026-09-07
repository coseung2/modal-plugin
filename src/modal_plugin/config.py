from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the MCP server."""

    model_config = SettingsConfigDict(env_prefix="MODAL_PLUGIN_", extra="ignore")

    default_environment: str = "dev"
    data_dir: Path = Path(".modal-plugin")
    transport: Literal["stdio", "streamable-http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    public_base_url: str | None = None
    allow_insecure_http: bool = False

    credential_key: SecretStr | None = None
    account_link_ttl_seconds: int = Field(default=600, ge=60, le=3600)

    modal_oauth_client_id: str | None = None
    modal_oauth_client_secret: SecretStr | None = None

    oauth_issuer_url: str | None = None
    oauth_jwks_url: str | None = None
    oauth_scopes: str = "modal:manage"
    oauth_algorithms: str = "RS256"

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir

    def credential_key_value(self) -> str | None:
        return self.credential_key.get_secret_value() if self.credential_key else None

    def modal_oauth_client_secret_value(self) -> str | None:
        if self.modal_oauth_client_secret is None:
            return None
        return self.modal_oauth_client_secret.get_secret_value()

    def resolved_public_base_url(self) -> str:
        if self.public_base_url:
            return self.public_base_url.rstrip("/")
        if self.host in {"127.0.0.1", "localhost"}:
            return f"http://{self.host}:{self.port}"
        raise ValueError(
            "Set MODAL_PLUGIN_PUBLIC_BASE_URL before serving the MCP endpoint remotely"
        )

    def mcp_resource_url(self) -> str:
        return f"{self.resolved_public_base_url()}/mcp"

    def oauth_scope_list(self) -> list[str]:
        scopes = [item for item in self.oauth_scopes.replace(",", " ").split() if item]
        if not scopes:
            raise ValueError("MODAL_PLUGIN_OAUTH_SCOPES must contain at least one scope")
        return scopes

    def oauth_algorithm_list(self) -> list[str]:
        algorithms = [item for item in self.oauth_algorithms.replace(",", " ").split() if item]
        if not algorithms:
            raise ValueError("MODAL_PLUGIN_OAUTH_ALGORITHMS must contain at least one algorithm")
        return algorithms

    def remote_auth_enabled(self) -> bool:
        configured = bool(self.oauth_issuer_url or self.oauth_jwks_url)
        if not configured:
            return False
        if not self.oauth_issuer_url or not self.oauth_jwks_url:
            raise ValueError(
                "Set both MODAL_PLUGIN_OAUTH_ISSUER_URL and MODAL_PLUGIN_OAUTH_JWKS_URL"
            )
        self.oauth_scope_list()
        self.oauth_algorithm_list()
        self.mcp_resource_url()
        return True

    def validate_http_security(self) -> None:
        if self.remote_auth_enabled():
            return
        if not self.allow_insecure_http:
            raise RuntimeError(
                "Refusing to start unauthenticated HTTP MCP server. Configure OIDC/JWKS auth or "
                "set MODAL_PLUGIN_ALLOW_INSECURE_HTTP=true for local development only."
            )

    def transport_security(self) -> TransportSecuritySettings:
        base = urlparse(self.resolved_public_base_url())
        invalid_origin = (
            base.scheme not in {"http", "https"}
            or not base.hostname
            or base.username is not None
            or base.password is not None
        )
        if invalid_origin:
            raise ValueError("MODAL_PLUGIN_PUBLIC_BASE_URL must be an http(s) origin")
        origin = f"{base.scheme}://{base.netloc}"
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[base.netloc],
            allowed_origins=[origin],
        )
