import json
from pathlib import Path

from modal_plugin.auth import owner_id_from_identity
from modal_plugin.credentials import CredentialVault


def test_credentials_are_encrypted_at_rest(tmp_path: Path) -> None:
    key = CredentialVault.generate_key()
    vault = CredentialVault(tmp_path / "credentials.json", key)
    linked = vault.save(
        account_id="default",
        auth_type="token",
        secret_payload={"token_id": "ak-test", "token_secret": "as-super-secret"},
        workspace="demo",
        environments=["dev"],
    )

    assert linked.workspace == "demo"
    raw = (tmp_path / "credentials.json").read_text(encoding="utf-8")
    assert "as-super-secret" not in raw
    assert "ak-test" not in raw

    auth_type, payload = vault.load_secret("default") or (None, {})
    assert auth_type == "token"
    assert payload == {"token_id": "ak-test", "token_secret": "as-super-secret"}


def test_same_account_id_is_isolated_per_owner(tmp_path: Path) -> None:
    vault = CredentialVault(tmp_path / "credentials.json", CredentialVault.generate_key())
    owner_a = owner_id_from_identity("https://id.example", "a")
    owner_b = owner_id_from_identity("https://id.example", "b")
    vault.save(
        owner_id=owner_a,
        account_id="default",
        auth_type="token",
        secret_payload={"token_id": "a", "token_secret": "secret-a"},
        workspace="workspace-a",
        environments=["dev"],
    )
    vault.save(
        owner_id=owner_b,
        account_id="default",
        auth_type="token",
        secret_payload={"token_id": "b", "token_secret": "secret-b"},
        workspace="workspace-b",
        environments=["dev"],
    )

    account_a = vault.get_metadata("default", owner_id=owner_a)
    account_b = vault.get_metadata("default", owner_id=owner_b)
    assert account_a is not None and account_a.workspace == "workspace-a"
    assert account_b is not None and account_b.workspace == "workspace-b"
    loaded_a = vault.load_secret("default", owner_id=owner_a)
    assert loaded_a is not None and loaded_a[1]["token_secret"] == "secret-a"


def test_v02_credential_registry_migrates_to_local_owner(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    key = CredentialVault.generate_key()
    vault = CredentialVault(path, key)
    vault.save(
        account_id="legacy",
        auth_type="oauth",
        secret_payload={"refresh_token": "refresh-test"},
        workspace="demo",
        environments=["dev"],
    )

    raw = json.loads(path.read_text(encoding="utf-8"))
    old = raw["local:legacy"]
    old.pop("owner_id")
    path.write_text(json.dumps({"legacy": old}), encoding="utf-8")

    migrated = CredentialVault(path, key)
    assert migrated.get_metadata("legacy") is not None
    rewritten = json.loads(path.read_text(encoding="utf-8"))
    assert list(rewritten) == ["local:legacy"]


def test_delete_linked_account(tmp_path: Path) -> None:
    vault = CredentialVault(tmp_path / "credentials.json", CredentialVault.generate_key())
    vault.save(
        account_id="lab",
        auth_type="oauth",
        secret_payload={"refresh_token": "refresh-test"},
        workspace="demo",
        environments=["dev", "prod"],
    )
    assert vault.delete("lab") is True
    assert vault.get_metadata("lab") is None
