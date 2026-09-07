# Security

This project controls infrastructure that can incur cost and can modify persistent model data.

- Never commit Modal tokens, OAuth refresh tokens, client secrets, model-provider tokens, or `.modal.toml`.
- Prefer short-lived or revocable credentials and least-privilege Modal environments.
- Keep production and development Modal environments separate.
- Cost-incurring runs, persistent uploads, cancellation, and destructive registry operations require explicit confirmation in the MCP tool schema.
- The built-in JSON registry is intended for one server instance. Use a transactional external store before running multiple replicas.
- `upload_model_file` can read a path visible to the MCP server. Do not expose a remote server to untrusted users until filesystem path allowlisting is added.

Please report security issues privately rather than opening a public issue containing credentials or exploit details.
