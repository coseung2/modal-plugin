from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from urllib.parse import quote

from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from .account_link import AccountLinkSessions, render_link_form
from .auth import OIDCJWTVerifier, current_owner_id
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


def _build_mcp() -> MCPServer:
    if not settings.remote_auth_enabled():
        return MCPServer("modal-plugin")

    resource_url = settings.mcp_resource_url()
    verifier = OIDCJWTVerifier(
        issuer=settings.oauth_issuer_url or "",
        resource=resource_url,
        jwks_url=settings.oauth_jwks_url or "",
        algorithms=settings.oauth_algorithm_list(),
    )
    return MCPServer(
        "modal-plugin",
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.oauth_issuer_url or ""),
            resource_server_url=AnyHttpUrl(resource_url),
            required_scopes=settings.oauth_scope_list(),
            validate_token_resource=True,
        ),
    )


mcp = _build_mcp()


def _tool_meta() -> dict[str, Any]:
    if settings.remote_auth_enabled():
        return {
            "securitySchemes": [
                {"type": "oauth2", "scopes": settings.oauth_scope_list()}
            ]
        }
    return {"securitySchemes": [{"type": "noauth"}]}


TOOL_META = _tool_meta()


@mcp.tool(meta=TOOL_META)
def list_modal_accounts() -> list[dict[str, Any]]:
    """List Modal accounts linked by the current authenticated user."""
    owner_id = current_owner_id()
    return [item.model_dump(mode="json") for item in vault.list(owner_id)]


@mcp.tool(meta=TOOL_META)
def create_modal_account_link(account_id: str = "default") -> dict[str, Any]:
    """Create a short-lived browser URL for securely linking a Modal account."""
    if not vault.enabled:
        raise CredentialStoreDisabled(
            "Set MODAL_PLUGIN_CREDENTIAL_KEY before linking accounts. "
            "See README for key generation."
        )
    owner_id = current_owner_id()
    session = link_sessions.create(account_id, owner_id=owner_id)
    base_url = settings.resolved_public_base_url()
    return {
        "account_id": account_id,
        "url": f"{base_url}/connect/modal/{quote(session.token, safe='')}",
        "expires_at": session.expires_at.isoformat(),
        "expires_in_seconds": settings.account_link_ttl_seconds,
    }


@mcp.tool(meta=TOOL_META)
def disconnect_modal_account(account_id: str = "default", confirm: bool = False) -> dict[str, Any]:
    """Delete one of the current user's stored Modal credentials. Requires confirmation."""
    if not confirm:
        raise PermissionError("Re-run with confirm=true to disconnect the Modal account.")
    owner_id = current_owner_id()
    deleted = vault.delete(account_id, owner_id=owner_id)
    gateway.invalidate_client(account_id, owner_id=owner_id)
    return {"account_id": account_id, "disconnected": deleted}


@mcp.tool(meta=TOOL_META)
def modal_account_status(account_id: str = "default") -> dict[str, Any]:
    """Verify the current user's Modal account and list its workspace environments."""
    return gateway.account_status(account_id, owner_id=current_owner_id())


@mcp.custom_route("/connect/modal/{token}", methods=["GET", "POST"])
async def modal_connect_route(request: Request):
    """Consume a high-entropy one-time account-link URL.

    MCP SDK custom routes are outside the bearer gate. The URL possession itself is the
    pre-authentication secret; it is generated only by an authenticated MCP tool in remote mode.
    """
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
                owner_id=session.owner_id,
                account_id=session.account_id,
                token_id=str(payload.get("token_id", "")),
                token_secret=str(payload.get("token_secret", "")),
            )
        elif auth_type == "oauth":
            linked = gateway.link_oauth_account(
                owner_id=session.owner_id,
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
            "account": linked.model_dump(mode="json", exclude={"owner_id"}),
        },
        headers={"Cache-Control": "no-store"},
    )


@mcp.custom_route("/health", methods=["GET"])
async def health_route(request: Request):  # noqa: ARG001
    return JSONResponse({"ok": True, "service": "modal-plugin"})


@mcp.tool(meta=TOOL_META)
def list_pipelines() -> list[dict[str, Any]]:
    """List generation pipelines owned by the current authenticated user."""
    return [
        item.model_dump(mode="json", exclude={"owner_id"})
        for item in store.list_pipelines(current_owner_id())
    ]


@mcp.tool(meta=TOOL_META)
def get_pipeline(name: str) -> dict[str, Any]:
    """Get one generation pipeline owned by the current authenticated user."""
    item = store.get_pipeline(current_owner_id(), name)
    if item is None:
        raise KeyError(f"Pipeline {name!r} not found")
    return item.model_dump(mode="json", exclude={"owner_id"})


@mcp.tool(meta=TOOL_META)
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
        owner_id=current_owner_id(),
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
    return store.create_pipeline(spec).model_dump(mode="json", exclude={"owner_id"})


@mcp.tool(meta=TOOL_META)
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
    """Update one of the current user's pipeline entries and increment its revision."""
    owner_id = current_owner_id()
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
    return store.update_pipeline(name, patch, owner_id=owner_id).model_dump(
        mode="json", exclude={"owner_id"}
    )


@mcp.tool(meta=TOOL_META)
def delete_pipeline(name: str, confirm: bool = False) -> dict[str, Any]:
    """Delete one of the current user's pipeline entries. Requires explicit confirmation."""
    if not confirm:
        raise PermissionError("Re-run with confirm=true to delete the pipeline registry entry.")
    deleted = store.delete_pipeline(current_owner_id(), name)
    return {"deleted": deleted, "name": name}


@mcp.tool(meta=TOOL_META)
def run_pipeline(
    name: str,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    gpu: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Spawn one of the current user's Modal pipelines. This may incur compute charges."""
    policy.check_run(confirm=confirm)
    owner_id = current_owner_id()
    pipeline = store.get_pipeline(owner_id, name)
    if pipeline is None:
        raise KeyError(f"Pipeline {name!r} not found")
    record = gateway.spawn_pipeline(pipeline, args=args, kwargs=kwargs, gpu=gpu)
    store.put_run(record)
    return record.model_dump(mode="json", exclude={"owner_id"})


@mcp.tool(meta=TOOL_META)
def get_run_status(call_id: str, include_result: bool = False) -> dict[str, Any]:
    """Poll one of the current user's Modal FunctionCalls."""
    owner_id = current_owner_id()
    record = store.get_run(owner_id, call_id)
    if record is None:
        raise KeyError(f"Run {call_id!r} not found in this registry")
    updated = gateway.get_run(record, include_result=include_result)
    store.put_run(updated)
    return updated.model_dump(mode="json", exclude={"owner_id"})


@mcp.tool(meta=TOOL_META)
def get_run_logs(call_id: str, entries: int = 100) -> list[dict[str, Any]]:
    """Return the most recent logs for one of the current user's Modal FunctionCalls."""
    if entries < 1 or entries > 1000:
        raise ValueError("entries must be between 1 and 1000")
    owner_id = current_owner_id()
    record = store.get_run(owner_id, call_id)
    if record is None:
        raise KeyError(f"Run {call_id!r} not found in this registry")
    return gateway.get_run_logs(
        call_id,
        owner_id=owner_id,
        account_id=record.account_id,
        entries=entries,
    )


@mcp.tool(meta=TOOL_META)
def cancel_run(
    call_id: str,
    terminate_containers: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Cancel one of the current user's Modal FunctionCalls. Requires explicit confirmation."""
    policy.check_cancel(confirm=confirm)
    owner_id = current_owner_id()
    record = store.get_run(owner_id, call_id)
    if record is None:
        raise KeyError(f"Run {call_id!r} not found in this registry")
    gateway.cancel_run(
        call_id,
        owner_id=owner_id,
        account_id=record.account_id,
        terminate_containers=terminate_containers,
    )
    cancelled = record.model_copy(update={"status": "cancelled"})
    store.put_run(cancelled)
    return {"cancelled": True, "call_id": call_id}


@mcp.tool(meta=TOOL_META)
def list_models() -> list[dict[str, Any]]:
    """List model artifacts owned by the current authenticated user."""
    return [
        item.model_dump(mode="json", exclude={"owner_id"})
        for item in store.list_models(current_owner_id())
    ]


@mcp.tool(meta=TOOL_META)
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
    """Register metadata for a model already present in the current user's Modal storage."""
    artifact = ModelArtifact(
        name=name,
        version=version,
        owner_id=current_owner_id(),
        account_id=account_id,
        volume_name=volume_name,
        remote_path=remote_path,
        source=source,
        sha256=sha256,
        metadata=metadata or {},
    )
    return store.put_model(artifact).model_dump(mode="json", exclude={"owner_id"})


@mcp.tool(meta=TOOL_META)
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
    """Upload one server-local file to the current user's Modal Volume and register it."""
    policy.check_model_upload(confirm=confirm)
    owner_id = current_owner_id()
    artifact = gateway.upload_model_file(
        name=name,
        version=version,
        owner_id=owner_id,
        account_id=account_id,
        local_path=Path(local_path).expanduser().resolve(),
        volume_name=volume_name,
        remote_path=remote_path,
        environment=environment or settings.default_environment,
    )
    store.put_model(artifact)
    return artifact.model_dump(mode="json", exclude={"owner_id"})


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

    settings.validate_http_security()
    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        stateless_http=True,
        json_response=True,
        transport_security=settings.transport_security(),
    )


if __name__ == "__main__":
    main()
