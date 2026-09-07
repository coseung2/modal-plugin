from __future__ import annotations

from dataclasses import dataclass


class ConfirmationRequired(PermissionError):
    pass


@dataclass(frozen=True)
class ActionPolicy:
    require_run_confirmation: bool = True
    require_model_upload_confirmation: bool = True
    require_cancel_confirmation: bool = True

    def check_run(self, *, confirm: bool) -> None:
        if self.require_run_confirmation and not confirm:
            raise ConfirmationRequired(
                "GPU/compute execution can incur Modal charges. Re-run with confirm=true after "
                "reviewing the pipeline, environment, and GPU settings."
            )

    def check_model_upload(self, *, confirm: bool) -> None:
        if self.require_model_upload_confirmation and not confirm:
            raise ConfirmationRequired(
                "Uploading changes persistent Modal storage. Re-run with confirm=true after "
                "reviewing the local path, volume, and destination."
            )

    def check_cancel(self, *, confirm: bool) -> None:
        if self.require_cancel_confirmation and not confirm:
            raise ConfirmationRequired(
                "Cancelling terminates active work. Re-run with confirm=true to cancel the call."
            )
