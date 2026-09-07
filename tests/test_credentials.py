from pathlib import Path

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
