import asyncio
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from modal_plugin.auth import OIDCJWTVerifier, claim_scopes, owner_id_from_identity


def test_claim_scopes_supports_oauth_and_oidc_shapes() -> None:
    assert claim_scopes({"scope": "openid modal:manage"}) == ["openid", "modal:manage"]
    assert claim_scopes({"scp": ["modal:read", "modal:manage"]}) == [
        "modal:read",
        "modal:manage",
    ]


def test_owner_id_is_stable_and_issuer_scoped() -> None:
    first = owner_id_from_identity("https://id.example", "user-1")
    assert first == owner_id_from_identity("https://id.example", "user-1")
    assert first != owner_id_from_identity("https://other.example", "user-1")
    assert first.startswith("oauth-")
    assert len(first) == len("oauth-") + 32


def test_oidc_verifier_checks_signature_issuer_and_resource_audience() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    issuer = "https://id.example/tenant/"
    resource = "https://modal.example/mcp"
    claims = {
        "iss": issuer,
        "sub": "user-123",
        "aud": resource,
        "scope": "modal:manage",
        "exp": 4102444800,
        "iat": 1700000000,
        "azp": "chatgpt-client",
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test"})

    verifier = OIDCJWTVerifier(
        issuer=issuer,
        resource=resource,
        jwks_url="https://id.example/.well-known/jwks.json",
        algorithms=["RS256"],
    )
    verifier.jwks = SimpleNamespace(
        get_signing_key_from_jwt=lambda _: SimpleNamespace(key=public_key)
    )

    access = asyncio.run(verifier.verify_token(token))
    assert access is not None
    assert access.subject == "user-123"
    assert access.resource == resource
    assert access.scopes == ["modal:manage"]
    assert access.claims == {"iss": issuer}

    wrong_audience = jwt.encode(
        {**claims, "aud": "https://other.example/mcp"},
        private_key,
        algorithm="RS256",
        headers={"kid": "test"},
    )
    assert asyncio.run(verifier.verify_token(wrong_audience)) is None
