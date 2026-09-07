# ruff: noqa: I001
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import pydantic


SAFE_NAME_PATTERN = r"^[A-Za-z0-9._-]{1,64}$"
SAFE_OWNER_PATTERN = r"^(local|oauth-[a-f0-9]{32})$"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PipelineSpec(pydantic.BaseModel):
    """A registered generation pipeline backed by one deployed Modal Function."""

    model_config = pydantic.ConfigDict(extra="forbid")

    name: str = pydantic.Field(pattern=SAFE_NAME_PATTERN)
    owner_id: str = pydantic.Field(default="local", pattern=SAFE_OWNER_PATTERN)
    account_id: str = pydantic.Field(default="default", pattern=SAFE_NAME_PATTERN)
    app_name: str = pydantic.Field(min_length=1, max_length=128)
    function_name: str = pydantic.Field(min_length=1, max_length=128)
    environment: str = pydantic.Field(default="dev", min_length=1, max_length=64)
    gpu: str | None = pydantic.Field(default=None, max_length=64)
    default_args: list[Any] = pydantic.Field(default_factory=list)
    default_kwargs: dict[str, Any] = pydantic.Field(default_factory=dict)
    model_bindings: dict[str, str] = pydantic.Field(default_factory=dict)
    tags: dict[str, str] = pydantic.Field(default_factory=dict)
    revision: int = pydantic.Field(default=1, ge=1)
    created_at: datetime = pydantic.Field(default_factory=utc_now)
    updated_at: datetime = pydantic.Field(default_factory=utc_now)

    @pydantic.field_validator("model_bindings")
    @classmethod
    def validate_model_binding_keys(cls, value: dict[str, str]) -> dict[str, str]:
        for key, path in value.items():
            if not key.strip() or not path.strip():
                raise ValueError("model_bindings keys and values must be non-empty")
        return value


class PipelinePatch(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    account_id: str | None = pydantic.Field(default=None, pattern=SAFE_NAME_PATTERN)
    app_name: str | None = pydantic.Field(default=None, min_length=1, max_length=128)
    function_name: str | None = pydantic.Field(default=None, min_length=1, max_length=128)
    environment: str | None = pydantic.Field(default=None, min_length=1, max_length=64)
    gpu: str | None = pydantic.Field(default=None, max_length=64)
    default_args: list[Any] | None = None
    default_kwargs: dict[str, Any] | None = None
    model_bindings: dict[str, str] | None = None
    tags: dict[str, str] | None = None


class ModelArtifact(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    name: str = pydantic.Field(pattern=SAFE_NAME_PATTERN)
    version: str = pydantic.Field(min_length=1, max_length=128)
    owner_id: str = pydantic.Field(default="local", pattern=SAFE_OWNER_PATTERN)
    account_id: str = pydantic.Field(default="default", pattern=SAFE_NAME_PATTERN)
    volume_name: str = pydantic.Field(min_length=1, max_length=64)
    remote_path: str = pydantic.Field(min_length=1, max_length=1024)
    source: str | None = pydantic.Field(default=None, max_length=2048)
    sha256: str | None = pydantic.Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    metadata: dict[str, Any] = pydantic.Field(default_factory=dict)
    created_at: datetime = pydantic.Field(default_factory=utc_now)


class RunRecord(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    call_id: str = pydantic.Field(min_length=1)
    pipeline_name: str = pydantic.Field(min_length=1)
    owner_id: str = pydantic.Field(default="local", pattern=SAFE_OWNER_PATTERN)
    account_id: str = pydantic.Field(default="default", pattern=SAFE_NAME_PATTERN)
    environment: str = pydantic.Field(min_length=1)
    gpu: str | None = None
    status: Literal["spawned", "completed", "failed", "cancelled", "unknown"] = "spawned"
    created_at: datetime = pydantic.Field(default_factory=utc_now)
    updated_at: datetime = pydantic.Field(default_factory=utc_now)
    result_preview: Any | None = None
    error: str | None = None
