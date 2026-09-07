from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from urllib.parse import quote

from mcp.server import MCPServer
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from .account_link import AccountLinkSessions, render_link_form
from .config import Settings
from .credentials import CredentialStoreDisabled, CredentialVault
from .modal_gateway import ModalGateway
from .models import ModelArtifact, PipelinePatch, PipelineSpec
from .policy import ActionPolicy
from .store import RegistryStore

settings = Settings()
data_dir = settings.ensure_data_dir()
store = RegistryStore(data_dir)
vault = CredentialVault(data_dir / "credentials.json", settings.credential_key_value())
gateway = ModalGateway(
    vault,
    oauth_client_id=settings.modal_oauth_client_id,
    oauth_client_secret=settings.modal_oauth_client_secret_value(),
)
policy = ActionPolicy()
link_sessions = AccountLinkSessions(settings.account_link_ttl_seconds)
mcp = MCPServer("modal-plugin")


@mcp.tool()
def list_modal_accounts() -> list[dict[str, Any]]:
    """List linked Modal accounts without returning credential material."""
    return [item.model_dump(mode="json") for item in vault.list()]


@mcp.tool()
def create_modal_account_link(account_id: str = "default") -> dict[str, Any]:
    """Create a one-time browser URL for securely linking a Modal account."""
    if not vault.enabled:
        raise CredentialStoreDisabled(
            "Set MODAL_PLUGIN_CREDENTIAL_KEY before linking accounts. See README for key generation."
        )
    session = link_sessions.create(account_id)
    base_url = settings.resolved_public_base_url()
    return {
        "account_id": account_id,
        "url": f"{base_url}/connect/modal/{quote(session.token, safe='')}",
        "expires_at": session.expires_at.isoformat(),
        "expires_in_seconds": settings.account_link_ttl_seconds,
    }


@mcp.tool()
def disconnect_modal_account(account_id: str = "default", confirm: bool = False) -> dict[str, Any]:
    """Delete a stored Modal account credential. Requires explicit confirmation."""
    if not confirm:
        raise PermissionError("Re-run with confirm=true to disconnect the Modal account.")
    deleted = vault.delete(account_id)
    gateway.invalidate_client(account_id)
    return {"account_id": account_id, "disconnected": deleted}


@mcp.tool()
def modal_account_status(account_id: str = "default") -> dict[str, Any]:
    """Verify Modal authentication and list the connected workspace environments."""
    return gateway.account_status(account_id)


@mcp.custom_route("/connect/modal/{token}", methods=["GET", "POST"])
async def modal_connect_route(request: Request):
    token = request.path_params["token"]
    session = link_sessions.get(token)
    if session is None:
        return JSONResponse(
            {"message": "This account-link URL is invalid or expired."}, status_code=404
        )

    if request.method == "GET":
        return HTMLResponse(
            render_link_form(session),
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    try:
        payload = await request.json()
        auth_type = payload.get("auth_type")
        if auth_type == "token":
            linked = gateway.link_token_account(
                account_id=session.account_id,
                token_id=str(payload.get("token_id", "")),
                token_secret=str(payload.get("token_secret", "")),
            )
        elif auth_type == "oauth":
            linked = gateway.link_oauth_account(
                account_id=session.account_id,
                refresh_token=str(payload.get("refresh_token", "")),
            )
        else:
            raise ValueError("auth_type must be 'token' or 'oauth'")
    except Exception as exc:  # noqa: BLE001 - return browser-safe account-link errors.
        return JSONResponse(
            {"message": f"Modal account connection failed: {exc}"},
            status_code=400,
            headers={"Cache-Control": "no-store"},
        )

    link_sessions.consume(token)
    return JSONResponse(
        {
            "message": f"Connected Modal workspace {linked.workspace} as {linked.account_id}.",
            "account": linked.model_dump(mode="json"),
        },
        headers={"Cache-Control": "no-store"},
    )


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
    account_id: str = "default",
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
        account_id=account_id,
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
    account_id: str | None = None,
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
        account_id=account_id,
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
    record = store.runs.get(call_id)
    if record is None:
        raise KeyError(f"Run {call_id!r} not found in this registry")
    return gateway.get_run_logs(call_id, account_id=record.account_id, entries=entries)


@mcp.tool()
def cancel_run(
    call_id: str,
    terminate_containers: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Cancel a Modal FunctionCall. Requires explicit confirmation."""
    policy.check_cancel(confirm=confirm)
    record = store.runs.get(call_id)
    if record is None:
        raise KeyError(f"Run {call_id!r} not found in this registry")
    gateway.cancel_run(
        call_id,
        account_id=record.account_id,
        terminate_containers=terminate_containers,
    )
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
    account_id: str = "default",
    source: str | None = None,
    sha256: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register metadata for a model already present in Modal storage."""
    artifact = ModelArtifact(
        name=name,
        version=version,
        account_id=account_id,
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
    account_id: str = "default",
    environment: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Upload one server-local file to a Modal Volume and register its metadata."""
    policy.check_model_upload(confirm=confirm)
    artifact = gateway.upload_model_file(
        name=name,
        version=version,
        account_id=account_id,
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
    parser.add_argument(
        "--generate-credential-key",
        action="store_true",
        help="Print a Fernet key for MODAL_PLUGIN_CREDENTIAL_KEY and exit.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.generate_credential_key:
        print(CredentialVault.generate_key())
        return
    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
