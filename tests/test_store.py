import json
from pathlib import Path

from modal_plugin.auth import owner_id_from_identity
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
    assert store.get_pipeline("local", "flux-dev") == updated


def test_same_pipeline_name_is_isolated_per_oauth_owner(tmp_path: Path) -> None:
    store = RegistryStore(tmp_path)
    owner_a = owner_id_from_identity("https://id.example", "a")
    owner_b = owner_id_from_identity("https://id.example", "b")
    store.create_pipeline(
        PipelineSpec(
            owner_id=owner_a,
            name="flux",
            app_name="app-a",
            function_name="generate",
        )
    )
    store.create_pipeline(
        PipelineSpec(
            owner_id=owner_b,
            name="flux",
            app_name="app-b",
            function_name="generate",
        )
    )

    pipeline_a = store.get_pipeline(owner_a, "flux")
    pipeline_b = store.get_pipeline(owner_b, "flux")
    assert pipeline_a is not None and pipeline_a.app_name == "app-a"
    assert pipeline_b is not None and pipeline_b.app_name == "app-b"
    assert [item.name for item in store.list_pipelines(owner_a)] == ["flux"]


def test_v02_pipeline_registry_migrates_to_local_owner(tmp_path: Path) -> None:
    old = PipelineSpec(
        name="legacy",
        app_name="image-app",
        function_name="generate",
    ).model_dump(mode="json")
    old.pop("owner_id")
    (tmp_path / "pipelines.json").write_text(
        json.dumps({"legacy": old}), encoding="utf-8"
    )

    store = RegistryStore(tmp_path)
    migrated = store.get_pipeline("local", "legacy")
    assert migrated is not None
    assert migrated.owner_id == "local"
    raw = json.loads((tmp_path / "pipelines.json").read_text(encoding="utf-8"))
    assert list(raw) == ["local:legacy"]
