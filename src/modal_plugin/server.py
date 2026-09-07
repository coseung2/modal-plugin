from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from .config import Settings
from .modal_gateway import ModalGateway
from .models import ModelArtifact, PipelinePatch, PipelineSpec
from .policy import ActionPolicy
from .store import RegistryStore

settings = Settings()
store = RegistryStore(settings.ensure_data_dir())
gateway = ModalGateway()
policy = ActionPolicy()
mcp = MCPServer("modal-plugin")


@mcp.tool()
def modal_account_status() -> dict[str, Any]:
    """Verify Modal authentication and list the connected workspace environments."""
    return gateway.account_status()


@mcp.tool()
def list_pipelines() -> list[dict[str, Any]]:
    """List registered Modal generation pipelines."""
    return [item.model_dump(mode="json") for item in store.pipelines.list()]


@mcp.tool()
def get_pipeline(name: str) -> dict[str, Any]:
    """Get one registered pipeline by name."""
    item = store.pipelines.get(name)
    if item is None:
        raise KeyError(f"Pipeline {name!r} not found")
    return item.model_dump(mode="json")


@mcp.tool()
def create_pipeline(
    name: str,
    app_name: str,
    function_name: str,
    environment: str | None = None,
    gpu: str | None = None,
    default_args: list[Any] | None = None,
    default_kwargs: dict[str, Any] | None = None,
    model_bindings: dict[str, str] | None = None,
    tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Register a deployed Modal Function as a named generation pipeline."""
    spec = PipelineSpec(
        name=name,
        app_name=app_name,
        function_name=function_name,
        environment=environment or settings.default_environment,
        gpu=gpu,
        default_args=default_args or [],
        default_kwargs=default_kwargs or {},
        model_bindings=model_bindings or {},
        tags=tags or {},
    )
    return store.create_pipeline(spec).model_dump(mode="json")


@mcp.tool()
def update_pipeline(
    name: str,
    app_name: str | None = None,
    function_name: str | None = None,
    environment: str | None = None,
    gpu: str | None = None,
    default_args: list[Any] | None = None,
    default_kwargs: dict[str, Any] | None = None,
    model_bindings: dict[str, str] | None = None,
    tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Update a pipeline registry entry and increment its revision."""
    patch = PipelinePatch(
        app_name=app_name,
        function_name=function_name,
        environment=environment,
        gpu=gpu,
        default_args=default_args,
        default_kwargs=default_kwargs,
        model_bindings=model_bindings,
        tags=tags,
    )
    return store.update_pipeline(name, patch).model_dump(mode="json")


@mcp.tool()
def delete_pipeline(name: str, confirm: bool = False) -> dict[str, Any]:
    """Delete a pipeline registry entry. Requires explicit confirmation."""
    if not confirm:
        raise PermissionError("Re-run with confirm=true to delete the pipeline registry entry.")
    deleted = store.pipelines.delete(name)
    return {"deleted": deleted, "name": name}


@mcp.tool()
def run_pipeline(
    name: str,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    gpu: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Spawn a registered Modal pipeline. This may incur compute charges."""
    policy.check_run(confirm=confirm)
    pipeline = store.pipelines.get(name)
    if pipeline is None:
        raise KeyError(f"Pipeline {name!r} not found")
    record = gateway.spawn_pipeline(pipeline, args=args, kwargs=kwargs, gpu=gpu)
    store.runs.put(record, overwrite=True)
    return record.model_dump(mode="json")


@mcp.tool()
def get_run_status(call_id: str, include_result: bool = False) -> dict[str, Any]:
    """Poll a Modal FunctionCall. include_result=true performs a zero-timeout result poll."""
    record = store.runs.get(call_id)
    if record is None:
        raise KeyError(f"Run {call_id!r} not found in this registry")
    updated = gateway.get_run(record, include_result=include_result)
    store.runs.put(updated, overwrite=True)
    return updated.model_dump(mode="json")


@mcp.tool()
def get_run_logs(call_id: str, entries: int = 100) -> list[dict[str, Any]]:
    """Return the most recent logs for a Modal FunctionCall."""
    if entries < 1 or entries > 1000:
        raise ValueError("entries must be between 1 and 1000")
    return gateway.get_run_logs(call_id, entries=entries)


@mcp.tool()
def cancel_run(
    call_id: str,
    terminate_containers: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Cancel a Modal FunctionCall. Requires explicit confirmation."""
    policy.check_cancel(confirm=confirm)
    gateway.cancel_run(call_id, terminate_containers=terminate_containers)
    record = store.runs.get(call_id)
    if record is not None:
        cancelled = record.model_copy(update={"status": "cancelled"})
        store.runs.put(cancelled, overwrite=True)
    return {"cancelled": True, "call_id": call_id}


@mcp.tool()
def list_models() -> list[dict[str, Any]]:
    """List model artifacts registered by this MCP server."""
    return [item.model_dump(mode="json") for item in store.models.list()]


@mcp.tool()
def register_model(
    name: str,
    version: str,
    volume_name: str,
    remote_path: str,
    source: str | None = None,
    sha256: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register metadata for a model already present in Modal storage."""
    artifact = ModelArtifact(
        name=name,
        version=version,
        volume_name=volume_name,
        remote_path=remote_path,
        source=source,
        sha256=sha256,
        metadata=metadata or {},
    )
    return store.models.put(artifact, overwrite=True).model_dump(mode="json")


@mcp.tool()
def upload_model_file(
    name: str,
    version: str,
    local_path: str,
    volume_name: str,
    remote_path: str,
    environment: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Upload one server-local file to a Modal Volume and register its metadata.

    For Codex with a local MCP server, local_path can point at a local model file. For a
    remote ChatGPT MCP deployment, local_path refers to the MCP server filesystem; direct
    browser uploads require the planned signed-upload endpoint.
    """
    policy.check_model_upload(confirm=confirm)
    artifact = gateway.upload_model_file(
        name=name,
        version=version,
        local_path=Path(local_path).expanduser().resolve(),
        volume_name=volume_name,
        remote_path=remote_path,
        environment=environment or settings.default_environment,
    )
    store.models.put(artifact, overwrite=True)
    return artifact.model_dump(mode="json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Modal Plugin MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=settings.transport,
    )
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
