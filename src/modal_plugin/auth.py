from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import jwt
from jwt import PyJWKClient
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier


def claim_scopes(claims: dict[str, Any]) -> list[str]:
    value = claims.get("scope", claims.get("scp", []))
    if isinstance(value, str):
        return [scope for scope in value.split() if scope]
    if isinstance(value, list):
        return [str(scope) for scope in value if str(scope)]
    return []


def owner_id_from_identity(issuer: str, subject: str) -> str:
    digest = hashlib.sha256(f"{issuer}\0{subject}".encode("utf-8")).hexdigest()
    return f"oauth-{digest[:32]}"


def current_owner_id() -> str:
    """Return a stable internal owner ID for the current OAuth user.

    stdio and explicitly insecure HTTP development fall back to the local owner.
    """
    token = get_access_token()
    if token is None:
        return "local"
    issuer = str((token.claims or {}).get("iss") or "")
    subject = token.subject or ""
    if not issuer or not subject:
        raise PermissionError("Authenticated token is missing issuer or subject")
    return owner_id_from_identity(issuer, subject)


class OIDCJWTVerifier(TokenVerifier):
    """Verify JWT access tokens against an OIDC/JWKS issuer."""

    def __init__(
        self,
        *,
        issuer: str,
        resource: str,
        jwks_url: str,
        algorithms: list[str],
    ) -> None:
        self.issuer = issuer
        self.resource = resource
        self.algorithms = algorithms
        self.jwks = PyJWKClient(jwks_url)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            signing_key = (await asyncio.to_thread(self.jwks.get_signing_key_from_jwt, token)).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=self.algorithms,
                audience=self.resource,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "sub"]},
            )
        except (jwt.PyJWTError, ValueError, OSError):
            return None

        subject = str(claims.get("sub") or "")
        if not subject:
            return None

        client_id = claims.get("azp") or claims.get("client_id")
        if not client_id:
            audience = claims.get("aud")
            if isinstance(audience, list) and audience:
                client_id = audience[0]
            elif isinstance(audience, str):
                client_id = audience
            else:
                client_id = "oauth-client"

        expires_at = claims.get("exp")
        return AccessToken(
            token=token,
            client_id=str(client_id),
            scopes=claim_scopes(claims),
            expires_at=int(expires_at) if isinstance(expires_at, int | float) else None,
            resource=self.resource,
            subject=subject,
            claims={"iss": self.issuer},
        )
