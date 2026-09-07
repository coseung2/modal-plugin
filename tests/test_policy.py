import pytest

from modal_plugin.policy import ActionPolicy, ConfirmationRequired


def test_run_requires_confirmation() -> None:
    with pytest.raises(ConfirmationRequired):
        ActionPolicy().check_run(confirm=False)


def test_run_accepts_confirmation() -> None:
    ActionPolicy().check_run(confirm=True)
