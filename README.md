# 모달 플러그인 / modal-plugin

An MCP control plane for managing Modal pipelines, model artifacts, and GPU runs from ChatGPT and Codex.

> Status: **v0.1 bootstrap**. The current implementation connects to one Modal credential context per MCP server instance. Multi-user OAuth account linking and direct browser uploads are the next milestones.

## What v0.1 does

- Uses the same MCP server from **Codex (stdio)** and **ChatGPT/remote MCP clients (Streamable HTTP)**.
- Verifies the connected Modal workspace and environments.
- Registers, reads, updates, and deletes named generation-pipeline definitions.
- Maps a pipeline to a deployed Modal `App` + `Function`, with an optional GPU override.
- Spawns Modal `FunctionCall`s, polls results, reads logs, and cancels runs.
- Registers model artifacts and uploads server-local files into Modal Volumes.
- Requires explicit `confirm=true` for compute runs, persistent uploads, cancellation, and deletes.
- Never stores Modal credentials in the local registry.

## Architecture

```text
ChatGPT ── Streamable HTTP ─┐
                            ├── modal-plugin MCP server ── Modal Python SDK ── Modal
Codex ───────── stdio ──────┘             │
                                          └── local JSON registry (v0.1)
```

A "pipeline" in v0.1 is deliberately a control-plane pointer to a deployed Modal entry function rather than arbitrary generated Python. That lets an agent safely change the app/function/environment/GPU/default arguments/model bindings without giving the MCP server an unrestricted code-execution endpoint.

## Requirements

- Python 3.10+
- A Modal account
- `uv` recommended

## Install

```bash
git clone https://github.com/coseung2/modal-plugin.git
cd modal-plugin
uv sync --extra dev
```

Authenticate locally with Modal:

```bash
uv run modal setup
```

Or provide Modal's standard credential environment variables to the MCP server:

```bash
export MODAL_TOKEN_ID="..."
export MODAL_TOKEN_SECRET="..."
```

Do **not** put real credentials in `.env.example`, Git commits, prompts, or issue text.

## Run for Codex / local MCP

```bash
uv run modal-plugin --transport stdio
```

Configure Codex to launch that command as an MCP server. The exact Codex configuration surface can evolve; the server itself only requires a standard stdio MCP client.

## Run as a remote MCP server

```bash
uv run modal-plugin --transport streamable-http --host 0.0.0.0 --port 8000
```

The MCP endpoint is served by the MCP Python SDK's Streamable HTTP transport. Put TLS and authentication in front of it before exposing it publicly.

## Example agent workflow

1. `modal_account_status()`
2. `create_pipeline(name="flux-dev", app_name="image-generation", function_name="generate", environment="dev", gpu="A100")`
3. Review the pipeline.
4. `run_pipeline(name="flux-dev", kwargs={"prompt": "..."}, confirm=true)`
5. `get_run_status(call_id="fc-...", include_result=true)`
6. `get_run_logs(call_id="fc-...")`

## MCP tools

### Account

- `modal_account_status`

### Pipelines

- `list_pipelines`
- `get_pipeline`
- `create_pipeline`
- `update_pipeline`
- `delete_pipeline`

### Runtime

- `run_pipeline`
- `get_run_status`
- `get_run_logs`
- `cancel_run`

### Models

- `list_models`
- `register_model`
- `upload_model_file`

## Model uploads

For a **local Codex MCP server**, `upload_model_file` can upload a local model file directly into a Modal Volume.

For a **remote ChatGPT MCP server**, the tool's `local_path` is a path on the MCP server, not the user's computer. Direct browser-to-storage upload therefore belongs in the next milestone: signed uploads to object storage followed by an import worker into a Modal Volume.

## Registry

v0.1 uses atomic JSON files under `.modal-plugin/` by default. This is intentionally simple and works for one process. Before horizontal scaling, replace `RegistryStore` with Postgres/Supabase or another transactional store.

## Roadmap

- [ ] Modal OAuth account linking with encrypted per-user refresh-token storage
- [ ] Authenticated remote MCP endpoint for ChatGPT
- [ ] Signed browser uploads for large model files
- [ ] Hugging Face / S3 / R2 model import jobs
- [ ] Versioned pipeline deployment from source manifests
- [ ] Production approval policy and audit log
- [ ] Transactional registry for multi-replica deployment
- [ ] Deployment template for the MCP service

## Security model

This project can incur cloud cost and touch persistent artifacts. Read [`SECURITY.md`](SECURITY.md) before exposing the server remotely.

## License

MIT
