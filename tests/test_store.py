from pathlib import Path

from modal_plugin.models import PipelinePatch, PipelineSpec
from modal_plugin.store import RegistryStore


def test_pipeline_create_and_update(tmp_path: Path) -> None:
    store = RegistryStore(tmp_path)
    created = store.create_pipeline(
        PipelineSpec(
            name="flux-dev",
            app_name="image-app",
            function_name="generate",
            environment="dev",
            gpu="A100",
        )
    )
    assert created.revision == 1

    updated = store.update_pipeline("flux-dev", PipelinePatch(gpu="H100"))
    assert updated.gpu == "H100"
    assert updated.revision == 2
    assert store.pipelines.get("flux-dev") == updated
