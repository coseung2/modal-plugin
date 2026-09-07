# 모달 플러그인 / modal-plugin

An MCP control plane for managing Modal accounts, generation pipelines, model artifacts, and GPU runs from ChatGPT and Codex.

> Status: **v0.2 account-linking bootstrap**. Token-based account linking works through a one-time browser URL. Modal OAuth refresh-token support is implemented for deployments that have Modal-issued OAuth client credentials. The MCP endpoint itself still needs production authentication before public deployment.

## What v0.2 does

- Uses the same MCP server from **Codex (stdio)** and **ChatGPT/remote MCP clients (Streamable HTTP)**.
- Keeps local `modal setup` / `MODAL_TOKEN_*` authentication as a fallback for Codex.
- Links multiple Modal accounts by `account_id` and encrypts stored credentials with Fernet.
- Keeps credentials out of tool arguments by using a short-lived one-time browser link.
- Supports Modal API-token accounts and Modal OAuth refresh-token accounts.
- Associates pipelines, model artifacts, and runs with the Modal account that owns them.
- Registers, reads, updates, and deletes named generation-pipeline definitions.
- Maps a pipeline to a deployed Modal `App` + `Function`, with an optional GPU override.
- Spawns Modal `FunctionCall`s, polls results, reads logs, and cancels runs.
- Registers model artifacts and uploads server-local files into Modal Volumes.
- Requires explicit `confirm=true` for compute runs, persistent uploads, cancellation, and deletes.

## Architecture

```text
ChatGPT ── Streamable HTTP ─┐
                            ├── modal-plugin MCP server ── account-aware Modal Client ── Modal
Codex ───────── stdio ──────┘             │
                                          ├── pipeline/model/run JSON registries
                                          └── encrypted credential registry
```

A "pipeline" is currently a control-plane pointer to a deployed Modal entry function rather than arbitrary generated Python. That lets an agent safely change app/function/environment/GPU/default arguments/model bindings without exposing an unrestricted code-execution endpoint. Source-manifest deployment is the next pipeline milestone.

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

## Local Codex authentication

For a local MCP server, existing Modal authentication continues to work:

```bash
uv run modal setup
uv run modal-plugin --transport stdio
```

A pipeline using `account_id="default"` falls back to the active local Modal profile when no encrypted linked account named `default` exists.

## Encrypted account linking

Generate an encryption key once and inject it through your secret manager or environment:

```bash
uv run modal-plugin --generate-credential-key
export MODAL_PLUGIN_CREDENTIAL_KEY="<generated value>"
```

Do not commit this key. The encrypted registry is stored under `.modal-plugin/credentials.json` by default.

For the remote HTTP server, configure its externally reachable base URL:

```bash
export MODAL_PLUGIN_PUBLIC_BASE_URL="https://modal-plugin.example.com"
uv run modal-plugin --transport streamable-http --host 0.0.0.0 --port 8000
```

Then an MCP client can call:

```text
create_modal_account_link(account_id="default")
```

The tool returns a one-time URL, valid for 10 minutes by default. Open it in a browser and enter either a Modal API token pair or, when your deployment has Modal-issued OAuth client credentials configured, a Modal OAuth refresh token. Credentials are POSTed directly from the browser to the MCP service and are not sent through ChatGPT or Codex.

### Modal OAuth deployments

Modal's Python SDK supports `Client.from_oauth_credentials(refresh_token, oauth_client_id=..., oauth_client_secret=...)` for managing Modal on behalf of third-party users. If Modal has issued OAuth integration credentials to your application, configure:

```bash
export MODAL_PLUGIN_MODAL_OAUTH_CLIENT_ID="oc-..."
export MODAL_PLUGIN_MODAL_OAUTH_CLIENT_SECRET="ov-..."
```

The public Modal documentation describes consuming the refresh token but does not currently document a self-service OAuth client registration/authorization flow. This repository therefore does not guess authorization/token endpoint URLs. Once Modal issues the integration details, the browser callback can be wired to that flow without changing the per-user client/vault design.

## Example agent workflow

1. `list_modal_accounts()`
2. `create_modal_account_link(account_id="studio")` if needed
3. `modal_account_status(account_id="studio")`
4. `create_pipeline(name="flux-dev", account_id="studio", app_name="image-generation", function_name="generate", environment="dev", gpu="A100")`
5. Review the pipeline.
6. `run_pipeline(name="flux-dev", kwargs={"prompt": "..."}, confirm=true)`
7. `get_run_status(call_id="fc-...", include_result=true)`
8. `get_run_logs(call_id="fc-...")`

## MCP tools

### Accounts

- `list_modal_accounts`
- `create_modal_account_link`
- `disconnect_modal_account`
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

For a **remote ChatGPT MCP server**, `local_path` is a path on the MCP server, not the user's computer. Direct browser-to-storage upload is therefore a separate milestone: signed uploads to object storage followed by an import worker into a Modal Volume.

## Remote MCP security

`streamable-http` uses stateless JSON responses, but the MCP endpoint does **not** yet implement production caller authentication. Do not expose it directly to the Internet. Put it behind a private gateway while developing. The next auth milestone is an OAuth-protected MCP resource server suitable for ChatGPT plus authenticated Codex remote access.

## Registry

v0.2 still uses local atomic JSON registries. Credentials are encrypted separately, but horizontal scaling still requires a transactional shared database and a real secret/KMS integration.

## Roadmap

- [x] Encrypted multi-account credential registry
- [x] One-time browser account-link flow
- [x] Modal OAuth refresh-token client support
- [ ] Modal-hosted OAuth authorization callback once integration endpoints are issued
- [ ] OAuth-protected remote MCP endpoint for ChatGPT
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
