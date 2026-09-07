# 모달 플러그인 / modal-plugin

An OAuth-protected MCP control plane for managing Modal accounts, generation pipelines, model artifacts, and GPU runs from ChatGPT and Codex.

> Status: **v0.3 remote-auth bootstrap**. The remote Streamable HTTP endpoint can operate as an OAuth 2.1 protected resource, validates JWT access tokens through OIDC/JWKS, and isolates Modal credentials and registry objects by authenticated OAuth subject. Local Codex stdio use remains supported.

## What v0.3 does

- Uses the same MCP tool surface from **Codex (stdio)** and **ChatGPT/remote MCP clients (Streamable HTTP)**.
- Protects remote MCP with OAuth bearer validation through an external authorization server / IdP.
- Publishes MCP Protected Resource Metadata through the MCP Python SDK.
- Verifies JWT signature, exact issuer, resource audience, expiry, and required scopes.
- Advertises tool-level OAuth `securitySchemes` metadata for ChatGPT/plugin hosts.
- Derives a stable internal owner from OAuth `iss + sub` and isolates accounts, pipelines, models, and runs by owner.
- Migrates v0.2 JSON registries and credentials to the local owner automatically.
- Never lets a remote OAuth user inherit the server machine's `modal setup` or `MODAL_TOKEN_*` credentials.
- Links multiple Modal accounts with encrypted Fernet storage and short-lived one-time browser URLs.
- Registers and edits generation pipelines backed by deployed Modal `App` + `Function` objects.
- Runs GPU work, polls results, tails logs, cancels calls, and uploads server-local model files to Modal Volumes.
- Requires explicit `confirm=true` for compute runs, persistent uploads, cancellation, and destructive actions.

## Architecture

```text
                      external OAuth / OIDC provider
                              │ metadata + JWKS
                              ▼
ChatGPT ── HTTPS/OAuth ── modal-plugin MCP ── per-user Modal Client ── Modal
                              │
Codex ─────── stdio ──────────┤
                              ├── owner-scoped pipeline/model/run registries
                              └── encrypted owner-scoped Modal credentials
```

A "pipeline" is currently a control-plane pointer to a deployed Modal entry function rather than arbitrary generated Python. Source-manifest deployment is a later milestone.

## Requirements

- Python 3.10+
- A Modal account
- `uv` recommended
- For remote ChatGPT use: an HTTPS hostname and an OAuth/OIDC authorization server that can issue JWT access tokens for this MCP resource

## Install

```bash
git clone https://github.com/coseung2/modal-plugin.git
cd modal-plugin
uv sync --extra dev
```

## Local Codex

Existing Modal authentication continues to work for the local stdio owner:

```bash
uv run modal setup
uv run modal-plugin --transport stdio
```

The local owner may use `account_id="default"` without storing another credential; it falls back to the active Modal profile. This fallback is deliberately unavailable to remote OAuth users.

## Remote OAuth MCP for ChatGPT

The plugin is a **resource server**, not an authorization server. Use an established OAuth/OIDC provider or your existing identity system. Do not put end-user login/password handling inside this repository.

Configure the externally reachable service origin and the authorization server:

```bash
export MODAL_PLUGIN_PUBLIC_BASE_URL="https://modal-plugin.example.com"
export MODAL_PLUGIN_OAUTH_ISSUER_URL="https://id.example.com/"
export MODAL_PLUGIN_OAUTH_JWKS_URL="https://id.example.com/.well-known/jwks.json"
export MODAL_PLUGIN_OAUTH_SCOPES="modal:manage"
export MODAL_PLUGIN_OAUTH_ALGORITHMS="RS256"
```

The MCP resource identifier is exactly:

```text
https://modal-plugin.example.com/mcp
```

Your authorization server must:

- expose standards-based OAuth/OIDC metadata for the configured issuer;
- support the client-registration strategy you use with ChatGPT (for example a pre-registered client, CIMD, or DCR);
- support Authorization Code + PKCE for interactive ChatGPT authorization;
- accept the MCP `resource` identifier and issue access tokens whose resource/audience is the exact `/mcp` URL;
- include a stable `sub`, exact `iss`, expiration, and the required scope(s);
- expose a JWKS containing the signing key used for the access token.

Then start the remote server:

```bash
uv run modal-plugin --transport streamable-http --host 0.0.0.0 --port 8000
```

Remote HTTP **fails closed** when OAuth is not configured. For local-only experiments you can explicitly opt out:

```bash
export MODAL_PLUGIN_ALLOW_INSECURE_HTTP=true
```

Do not use that setting on an Internet-facing deployment.

The server keeps DNS-rebinding protection enabled and allowlists only the Host/Origin derived from `MODAL_PLUGIN_PUBLIC_BASE_URL`.

## Encrypted Modal account linking

Generate an encryption key once and inject it through your deployment secret manager:

```bash
uv run modal-plugin --generate-credential-key
export MODAL_PLUGIN_CREDENTIAL_KEY="<generated value>"
```

Do not commit this key. The local bootstrap registry is `.modal-plugin/credentials.json`; credential payloads are encrypted at rest.

An authenticated MCP client calls:

```text
create_modal_account_link(account_id="studio")
```

The returned URL is high-entropy, one-time, and short-lived. It is bound to the OAuth user who requested it. The user opens the link and enters a Modal API token pair, or a Modal OAuth refresh token when the deployment has Modal-issued third-party OAuth credentials.

Credentials are POSTed directly from the browser to the MCP service and are not sent as ChatGPT/Codex tool arguments.

### Modal third-party OAuth

If Modal has issued OAuth integration credentials to this application:

```bash
export MODAL_PLUGIN_MODAL_OAUTH_CLIENT_ID="oc-..."
export MODAL_PLUGIN_MODAL_OAUTH_CLIENT_SECRET="ov-..."
```

These credentials are for **Modal account delegation** and are separate from the OAuth system protecting the ChatGPT ↔ MCP connection.

## Example workflow

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

## Multi-user isolation

For an authenticated remote request, the server hashes the token's exact `iss` and `sub` into an internal owner ID. The owner ID is never accepted as a tool argument. Every account credential, pipeline, model artifact, and FunctionCall lookup is scoped to that owner.

Two users can therefore both create `account_id="default"` and `pipeline="flux-dev"` without collisions. A remote user cannot address another user's records by guessing names or call IDs.

Existing v0.2 data is migrated to the special `local` owner when the registries are opened.

## Model uploads

For a **local Codex MCP server**, `upload_model_file` can upload a local model file directly into a Modal Volume.

For a **remote ChatGPT MCP server**, `local_path` is a path on the MCP server, not the user's computer. Large browser uploads and direct Hugging Face / S3 / R2 imports are separate milestones.

## Registry and scaling

v0.3 still uses local atomic JSON files. Authentication and owner isolation make a single remote instance safer, but horizontal scaling still requires transactional shared storage, shared account-link state, and a real KMS/secret-management integration.

## Roadmap

- [x] Encrypted multi-account Modal credential registry
- [x] One-time browser account-link flow
- [x] Modal OAuth refresh-token client support
- [x] OAuth-protected remote MCP resource server
- [x] OAuth subject-based tenant isolation
- [x] Production Host/Origin allowlisting for the MCP transport
- [ ] Modal-hosted OAuth authorization callback once Modal integration endpoints are issued
- [ ] Hugging Face / S3 / R2 model import jobs
- [ ] Signed browser uploads for large model files
- [ ] Versioned pipeline deployment from source manifests
- [ ] Production approval policy and audit log
- [ ] Transactional registry for multi-replica deployment
- [ ] Deployment template for the MCP service

## Security

This project can incur cloud cost and modify persistent model data. Read [`SECURITY.md`](SECURITY.md) before deployment.

## License

MIT
