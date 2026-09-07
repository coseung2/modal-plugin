from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SAFE_NAME_PATTERN = r"^[A-Za-z0-9._-]{1,64}$"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PipelineSpec(BaseModel):
    """A registered generation pipeline backed by one deployed Modal Function."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=SAFE_NAME_PATTERN)
    app_name: str = Field(min_length=1, max_length=128)
    function_name: str = Field(min_length=1, max_length=128)
    environment: str = Field(default="dev", min_length=1, max_length=64)
    gpu: str | None = Field(default=None, max_length=64)
    default_args: list[Any] = Field(default_factory=list)
    default_kwargs: dict[str, Any] = Field(default_factory=dict)
    model_bindings: dict[str, str] = Field(default_factory=dict)
    tags: dict[str, str] = Field(default_factory=dict)
    revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("model_bindings")
    @classmethod
    def validate_model_binding_keys(cls, value: dict[str, str]) -> dict[str, str]:
        for key, path in value.items():
            if not key.strip() or not path.strip():
                raise ValueError("model_bindings keys and values must be non-empty")
        return value


class PipelinePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_name: str | None = Field(default=None, min_length=1, max_length=128)
    function_name: str | None = Field(default=None, min_length=1, max_length=128)
    environment: str | None = Field(default=None, min_length=1, max_length=64)
    gpu: str | None = Field(default=None, max_length=64)
    default_args: list[Any] | None = None
    default_kwargs: dict[str, Any] | None = None
    model_bindings: dict[str, str] | None = None
    tags: dict[str, str] | None = None


class ModelArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=SAFE_NAME_PATTERN)
    version: str = Field(min_length=1, max_length=128)
    volume_name: str = Field(min_length=1, max_length=64)
    remote_path: str = Field(min_length=1, max_length=1024)
    source: str | None = Field(default=None, max_length=2048)
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(min_length=1)
    pipeline_name: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    gpu: str | None = None
    status: Literal["spawned", "completed", "failed", "cancelled", "unknown"] = "spawned"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    result_preview: Any | None = None
    error: str | None = None
