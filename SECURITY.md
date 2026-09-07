# Security

This project controls infrastructure that can incur cost and can modify persistent model data.

- Never commit Modal tokens, OAuth refresh tokens, OAuth client secrets, `MODAL_PLUGIN_CREDENTIAL_KEY`, provider tokens, or `.modal.toml`.
- Internet-facing Streamable HTTP should use OAuth/JWT validation. The server fails closed without it unless `MODAL_PLUGIN_ALLOW_INSECURE_HTTP=true` is explicitly set.
- JWT validation checks signature through configured JWKS, exact issuer, exact MCP resource audience, expiration, and the MCP server's required scopes.
- Remote ownership is derived internally from the verified token's `iss + sub`. Owner IDs are not accepted from tool arguments.
- Remote OAuth users never fall back to the host machine's `modal setup` or `MODAL_TOKEN_*` credentials.
- Linked Modal credentials are encrypted with Fernet before writing `.modal-plugin/credentials.json`. Keep `MODAL_PLUGIN_CREDENTIAL_KEY` in a separate secret manager or protected environment injection.
- The browser Modal-account link route is intentionally outside the bearer gate. Access is controlled by a high-entropy, one-time URL generated for an authenticated owner and expiring quickly. Do not log full account-link URLs.
- DNS-rebinding protection remains enabled for remote MCP; allowed Host and Origin values are derived from `MODAL_PLUGIN_PUBLIC_BASE_URL`.
- Prefer short-lived/revocable credentials, least-privilege scopes, and separate Modal development/production environments.
- GPU runs, persistent uploads, cancellation, credential disconnects, and destructive registry operations require explicit confirmation in the MCP tool surface.
- `upload_model_file` can read a path visible to the MCP server. Do not grant the remote service arbitrary sensitive filesystem access; path allowlisting is still a planned hardening step.
- The built-in JSON registries and in-memory account-link sessions are designed for one server process. Use transactional shared state before horizontal scaling.
- Treat your external OAuth authorization server configuration as part of the security boundary. It must bind tokens to the exact MCP resource and issue a stable subject.

Please report security issues privately rather than opening a public issue containing credentials or exploit details.
