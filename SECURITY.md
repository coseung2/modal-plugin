# Security

This project controls infrastructure that can incur cost and can modify persistent model data.

- Never commit Modal tokens, OAuth refresh tokens, OAuth client secrets, `MODAL_PLUGIN_CREDENTIAL_KEY`, provider tokens, or `.modal.toml`.
- Linked Modal account credentials are encrypted with Fernet before they are written to `.modal-plugin/credentials.json`. The Fernet key must be supplied separately through `MODAL_PLUGIN_CREDENTIAL_KEY` or an equivalent secret manager injection.
- The browser account-link route is intentionally unauthenticated because it is used before an account exists. Access is gated by a high-entropy, one-time URL that expires quickly. Do not log full account-link URLs.
- Prefer short-lived or revocable credentials and least-privilege Modal environments.
- Keep production and development Modal environments separate.
- Cost-incurring runs, persistent uploads, cancellation, and destructive registry operations require explicit confirmation in the MCP tool schema.
- The built-in JSON registries are intended for one server instance. Use a transactional external store before running multiple replicas.
- `upload_model_file` can read a path visible to the MCP server. Do not expose a remote server to untrusted users until filesystem path allowlisting is added.
- The Streamable HTTP MCP endpoint itself still needs an authentication layer before Internet exposure. Account-link encryption does not authenticate MCP callers.

Please report security issues privately rather than opening a public issue containing credentials or exploit details.
