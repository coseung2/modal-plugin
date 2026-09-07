from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Generic, TypeVar

from pydantic import BaseModel

from .models import ModelArtifact, PipelinePatch, PipelineSpec, RunRecord, utc_now

T = TypeVar("T", bound=BaseModel)


class JsonRegistry(Generic[T]):
    """Small atomic JSON registry suitable for a single MCP server instance."""

    def __init__(self, path: Path, model: type[T], key_field: str) -> None:
        self.path = path
        self.model = model
        self.key_field = key_field
        self._lock = RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_raw({})

    def _read_raw(self) -> dict[str, dict]:
        with self.path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            raise TypeError(f"Registry {self.path} is corrupt: expected an object")
        return raw

    def _write_raw(self, value: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, default=str)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def list(self) -> list[T]:
        with self._lock:
            raw = self._read_raw()
            return [self.model.model_validate(item) for item in raw.values()]

    def get(self, key: str) -> T | None:
        with self._lock:
            item = self._read_raw().get(key)
            return self.model.model_validate(item) if item is not None else None

    def put(self, item: T, *, overwrite: bool = False) -> T:
        key = str(getattr(item, self.key_field))
        with self._lock:
            raw = self._read_raw()
            if key in raw and not overwrite:
                raise ValueError(f"{key!r} already exists")
            raw[key] = item.model_dump(mode="json")
            self._write_raw(raw)
        return item

    def delete(self, key: str) -> bool:
        with self._lock:
            raw = self._read_raw()
            if key not in raw:
                return False
            del raw[key]
            self._write_raw(raw)
            return True


class RegistryStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.pipelines = JsonRegistry(root / "pipelines.json", PipelineSpec, "name")
        self.models = JsonRegistry(root / "models.json", ModelArtifact, "name")
        self.runs = JsonRegistry(root / "runs.json", RunRecord, "call_id")

    def create_pipeline(self, spec: PipelineSpec) -> PipelineSpec:
        return self.pipelines.put(spec)

    def update_pipeline(self, name: str, patch: PipelinePatch) -> PipelineSpec:
        current = self.pipelines.get(name)
        if current is None:
            raise KeyError(name)
        changes = patch.model_dump(exclude_none=True)
        updated = current.model_copy(
            update={**changes, "revision": current.revision + 1, "updated_at": utc_now()}
        )
        return self.pipelines.put(updated, overwrite=True)
