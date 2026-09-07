from __future__ import annotations

from pathlib import Path
from typing import Literal

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
    credential_key: SecretStr | None = None
    account_link_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    modal_oauth_client_id: str | None = None
    modal_oauth_client_secret: SecretStr | None = None

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
            "Set MODAL_PLUGIN_PUBLIC_BASE_URL before creating account links on a remote server"
        )
