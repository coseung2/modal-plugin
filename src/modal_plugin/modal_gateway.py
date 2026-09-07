from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import modal

from .models import ModelArtifact, PipelineSpec, RunRecord, utc_now


class ModalGateway:
    """Thin wrapper over the public Modal Python SDK.

    Authentication is delegated to Modal's standard credential resolution. That supports
    local profiles, API token environment variables, and third-party OAuth environment
    variables without storing secrets in this application's registry.
    """

    def __init__(self) -> None:
        self._client: modal.Client | None = None

    def client(self) -> modal.Client:
        if self._client is None or self._client.is_closed():
            self._client = modal.Client.from_env()
        return self._client

    def account_status(self) -> dict[str, Any]:
        client = self.client()
        client.hello()
        workspace = modal.Workspace.from_context(client=client)
        workspace.hydrate()
        environments = modal.Environment.objects.list(client=client)
        return {
            "connected": True,
            "workspace": workspace.name,
            "environments": [env.name for env in environments],
        }

    def spawn_pipeline(
        self,
        pipeline: PipelineSpec,
        *,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        gpu: str | None = None,
    ) -> RunRecord:
        client = self.client()
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
            environment=pipeline.environment,
            gpu=selected_gpu,
            status="spawned",
        )

    def get_run(self, record: RunRecord, *, include_result: bool = False) -> RunRecord:
        call = modal.FunctionCall.from_id(record.call_id, client=self.client())
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

    def get_run_logs(self, call_id: str, *, entries: int = 100) -> list[dict[str, Any]]:
        call = modal.FunctionCall.from_id(call_id, client=self.client())
        return [
            {
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                "source": entry.source,
                "message": entry.message,
            }
            for entry in call.logs.tail(entries=entries)
        ]

    def cancel_run(self, call_id: str, *, terminate_containers: bool = False) -> None:
        call = modal.FunctionCall.from_id(call_id, client=self.client())
        call.cancel(terminate_containers=terminate_containers)

    def upload_model_file(
        self,
        *,
        name: str,
        version: str,
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
            client=self.client(),
        )
        with volume.batch_upload(force=True) as batch:
            batch.put_file(local_path, remote_path)

        return ModelArtifact(
            name=name,
            version=version,
            volume_name=volume_name,
            remote_path=remote_path,
            source=source or f"file://{local_path.name}",
            sha256=digest.hexdigest(),
            metadata={"environment": environment, "size_bytes": local_path.stat().st_size},
        )
