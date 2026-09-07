from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the MCP server.

    Modal credentials intentionally use Modal's own environment variable names.
    The server never persists credential values in its registry.
    """

    model_config = SettingsConfigDict(env_prefix="MODAL_PLUGIN_", extra="ignore")

    default_environment: str = "dev"
    data_dir: Path = Path(".modal-plugin")
    transport: Literal["stdio", "streamable-http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir
