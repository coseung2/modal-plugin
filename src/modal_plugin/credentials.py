from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field

from .models import SAFE_NAME_PATTERN, utc_now


class CredentialStoreDisabled(RuntimeError):
    pass


class LinkedAccount(BaseModel):
    account_id: str = Field(pattern=SAFE_NAME_PATTERN)
    auth_type: Literal["token", "oauth"]
    workspace: str
    environments: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class _CredentialEnvelope(LinkedAccount):
    ciphertext: str


class CredentialVault:
    """Encrypted credential storage for linked Modal accounts.

    The encryption key is never persisted by this class. In production it should come from a
    secret manager through MODAL_PLUGIN_CREDENTIAL_KEY.
    """

    def __init__(self, path: Path, key: str | None) -> None:
        self.path = path
        self._key = key
        self._lock = RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_raw({})

    @property
    def enabled(self) -> bool:
        return bool(self._key)

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode("ascii")

    def _fernet(self) -> Fernet:
        if not self._key:
            raise CredentialStoreDisabled(
                "Credential storage is disabled. Set MODAL_PLUGIN_CREDENTIAL_KEY to a Fernet key."
            )
        try:
            return Fernet(self._key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise CredentialStoreDisabled(
                "MODAL_PLUGIN_CREDENTIAL_KEY is not a valid Fernet key"
            ) from exc

    def _read_raw(self) -> dict[str, dict[str, Any]]:
        with self.path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise TypeError(f"Credential registry {self.path} is corrupt")
        return value

    def _write_raw(self, value: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            try:
                os.fchmod(fd, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def list(self) -> list[LinkedAccount]:
        with self._lock:
            raw = self._read_raw()
            return [
                LinkedAccount.model_validate({k: v for k, v in item.items() if k != "ciphertext"})
                for item in raw.values()
            ]

    def get_metadata(self, account_id: str) -> LinkedAccount | None:
        with self._lock:
            item = self._read_raw().get(account_id)
            if item is None:
                return None
            public = {k: v for k, v in item.items() if k != "ciphertext"}
            return LinkedAccount.model_validate(public)

    def load_secret(self, account_id: str) -> tuple[str, dict[str, str]] | None:
        with self._lock:
            item = self._read_raw().get(account_id)
            if item is None:
                return None
            envelope = _CredentialEnvelope.model_validate(item)
            try:
                plaintext = self._fernet().decrypt(envelope.ciphertext.encode("ascii"))
            except InvalidToken as exc:
                raise CredentialStoreDisabled(
                    "Unable to decrypt linked account credentials with the configured key"
                ) from exc
            payload = json.loads(plaintext.decode("utf-8"))
            if not isinstance(payload, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in payload.items()
            ):
                raise TypeError("Linked credential payload is corrupt")
            return envelope.auth_type, payload

    def save(
        self,
        *,
        account_id: str,
        auth_type: Literal["token", "oauth"],
        secret_payload: dict[str, str],
        workspace: str,
        environments: list[str],
    ) -> LinkedAccount:
        LinkedAccount(
            account_id=account_id,
            auth_type=auth_type,
            workspace=workspace,
            environments=environments,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        ciphertext = self._fernet().encrypt(
            json.dumps(secret_payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        with self._lock:
            raw = self._read_raw()
            previous = raw.get(account_id)
            now = utc_now()
            created_at = previous.get("created_at", now) if isinstance(previous, dict) else now
            envelope = _CredentialEnvelope(
                account_id=account_id,
                auth_type=auth_type,
                workspace=workspace,
                environments=environments,
                created_at=created_at,
                updated_at=now,
                ciphertext=ciphertext,
            )
            raw[account_id] = envelope.model_dump(mode="json")
            self._write_raw(raw)
            return LinkedAccount.model_validate(envelope.model_dump(exclude={"ciphertext"}))

    def delete(self, account_id: str) -> bool:
        with self._lock:
            raw = self._read_raw()
            if account_id not in raw:
                return False
            del raw[account_id]
            self._write_raw(raw)
            return True
