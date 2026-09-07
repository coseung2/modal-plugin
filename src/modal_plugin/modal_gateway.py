from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import modal

from .credentials import CredentialVault, LinkedAccount
from .models import ModelArtifact, PipelineSpec, RunRecord, utc_now


class ModalGateway:
    """Thin wrapper over the public Modal Python SDK with per-owner account clients."""

    def __init__(
        self,
        vault: CredentialVault,
        *,
        oauth_client_id: str | None = None,
        oauth_client_secret: str | None = None,
    ) -> None:
        self.vault = vault
        self.oauth_client_id = oauth_client_id
        self.oauth_client_secret = oauth_client_secret
        self._clients: dict[tuple[str, str], modal.Client] = {}

    def _client_from_linked_secret(
        self, account_id: str, *, owner_id: str
    ) -> modal.Client | None:
        loaded = self.vault.load_secret(account_id, owner_id=owner_id)
        if loaded is None:
            return None
        auth_type, payload = loaded
        if auth_type == "token":
            return modal.Client.from_credentials(payload["token_id"], payload["token_secret"])
        if not self.oauth_client_id or not self.oauth_client_secret:
            raise RuntimeError(
                "This account uses Modal OAuth but the server has no Modal OAuth client "
                "credentials. Set MODAL_PLUGIN_MODAL_OAUTH_CLIENT_ID and "
                "MODAL_PLUGIN_MODAL_OAUTH_CLIENT_SECRET."
            )
        return modal.Client.from_oauth_credentials(
            payload["refresh_token"],
            oauth_client_id=self.oauth_client_id,
            oauth_client_secret=self.oauth_client_secret,
        )

    def client(self, account_id: str = "default", *, owner_id: str = "local") -> modal.Client:
        cache_key = (owner_id, account_id)
        cached = self._clients.get(cache_key)
        if cached is not None and not cached.is_closed():
            return cached

        linked = self._client_from_linked_secret(account_id, owner_id=owner_id)
        if linked is not None:
            self._clients[cache_key] = linked
            return linked

        # Only the local stdio owner may inherit modal setup / MODAL_TOKEN_* credentials.
        if owner_id != "local" or account_id != "default":
            raise KeyError(f"Modal account {account_id!r} is not linked for this user")

        client = modal.Client.from_env()
        self._clients[cache_key] = client
        return client

    def invalidate_client(self, account_id: str, *, owner_id: str = "local") -> None:
        self._clients.pop((owner_id, account_id), None)

    @staticmethod
    def _inspect_client(client: modal.Client) -> dict[str, Any]:
        client.hello()
        workspace = modal.Workspace.from_context(client=client)
        workspace.hydrate(client=client)
        environments = modal.Environment.objects.list(client=client)
        return {
            "connected": True,
            "workspace": workspace.name,
            "environments": [env.name for env in environments],
        }

    def account_status(
        self, account_id: str = "default", *, owner_id: str = "local"
    ) -> dict[str, Any]:
        status = self._inspect_client(self.client(account_id, owner_id=owner_id))
        status["account_id"] = account_id
        status["linked"] = self.vault.get_metadata(account_id, owner_id=owner_id) is not None
        return status

    def link_token_account(
        self,
        *,
        account_id: str,
        token_id: str,
        token_secret: str,
        owner_id: str = "local",
    ) -> LinkedAccount:
        if not token_id or not token_secret:
            raise ValueError("token_id and token_secret are required")
        client = modal.Client.from_credentials(token_id, token_secret)
        status = self._inspect_client(client)
        linked = self.vault.save(
            owner_id=owner_id,
            account_id=account_id,
            auth_type="token",
            secret_payload={"token_id": token_id, "token_secret": token_secret},
            workspace=status["workspace"],
            environments=status["environments"],
        )
        self.invalidate_client(account_id, owner_id=owner_id)
        return linked

    def link_oauth_account(
        self,
        *,
        account_id: str,
        refresh_token: str,
        owner_id: str = "local",
    ) -> LinkedAccount:
        if not self.oauth_client_id or not self.oauth_client_secret:
            raise RuntimeError("Modal OAuth client credentials are not configured on this server")
        if not refresh_token:
            raise ValueError("refresh_token is required")
        client = modal.Client.from_oauth_credentials(
            refresh_token,
            oauth_client_id=self.oauth_client_id,
            oauth_client_secret=self.oauth_client_secret,
        )
        status = self._inspect_client(client)
        linked = self.vault.save(
            owner_id=owner_id,
            account_id=account_id,
            auth_type="oauth",
            secret_payload={"refresh_token": refresh_token},
            workspace=status["workspace"],
            environments=status["environments"],
        )
        self.invalidate_client(account_id, owner_id=owner_id)
        return linked

    def spawn_pipeline(
        self,
        pipeline: PipelineSpec,
        *,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        gpu: str | None = None,
    ) -> RunRecord:
        client = self.client(pipeline.account_id, owner_id=pipeline.owner_id)
        fn = modal.Function.from_name(
            pipeline.app_name,
            pipeline.function_name,
            environment_name=pipeline.environment,
            client=client,
        )
        selected_gpu = gpu if gpu is not None else pipeline.gpu
        if selected_gpu:
            fn = fn.with_options(gpu=selected_gpu)

        call = fn.spawn(
            *(pipeline.default_args if args is None else args),
            **{**pipeline.default_kwargs, **(kwargs or {})},
        )
        return RunRecord(
            call_id=call.object_id,
            pipeline_name=pipeline.name,
            owner_id=pipeline.owner_id,
            account_id=pipeline.account_id,
            environment=pipeline.environment,
            gpu=selected_gpu,
            status="spawned",
        )

    def get_run(self, record: RunRecord, *, include_result: bool = False) -> RunRecord:
        call = modal.FunctionCall.from_id(
            record.call_id,
            client=self.client(record.account_id, owner_id=record.owner_id),
        )
        if not include_result:
            return record.model_copy(update={"status": "unknown", "updated_at": utc_now()})

        try:
            result = call.get(timeout=0)
        except TimeoutError:
            return record.model_copy(update={"status": "spawned", "updated_at": utc_now()})
        except Exception as exc:  # noqa: BLE001 - remote user code may raise any exception type.
            return record.model_copy(
                update={"status": "failed", "error": str(exc), "updated_at": utc_now()}
            )
        return record.model_copy(
            update={"status": "completed", "result_preview": result, "updated_at": utc_now()}
        )

    def get_run_logs(
        self,
        call_id: str,
        *,
        account_id: str = "default",
        owner_id: str = "local",
        entries: int = 100,
    ) -> list[dict[str, Any]]:
        call = modal.FunctionCall.from_id(
            call_id, client=self.client(account_id, owner_id=owner_id)
        )
        return [
            {
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                "source": entry.source,
                "message": entry.message,
            }
            for entry in call.logs.tail(entries=entries)
        ]

    def cancel_run(
        self,
        call_id: str,
        *,
        account_id: str = "default",
        owner_id: str = "local",
        terminate_containers: bool = False,
    ) -> None:
        call = modal.FunctionCall.from_id(
            call_id, client=self.client(account_id, owner_id=owner_id)
        )
        call.cancel(terminate_containers=terminate_containers)

    def upload_model_file(
        self,
        *,
        name: str,
        version: str,
        account_id: str,
        owner_id: str,
        local_path: Path,
        volume_name: str,
        remote_path: str,
        environment: str,
        source: str | None = None,
    ) -> ModelArtifact:
        if not local_path.is_file():
            raise FileNotFoundError(local_path)

        digest = hashlib.sha256()
        with local_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)

        volume = modal.Volume.from_name(
            volume_name,
            environment_name=environment,
            create_if_missing=True,
            client=self.client(account_id, owner_id=owner_id),
        )
        with volume.batch_upload(force=True) as batch:
            batch.put_file(local_path, remote_path)

        return ModelArtifact(
            name=name,
            version=version,
            owner_id=owner_id,
            account_id=account_id,
            volume_name=volume_name,
            remote_path=remote_path,
            source=source or f"file://{local_path.name}",
            sha256=digest.hexdigest(),
            metadata={"environment": environment, "size_bytes": local_path.stat().st_size},
        )
