"""Inbound token validation — the only thing standing in front of the endpoint.

The Teams endpoint is, unavoidably, a public HTTPS URL. Everything behind it
starts coding-agent sessions on the operator's machine. So the failure mode
these tests guard against is not "a user sees an error"; it is "anyone on the
internet can start a session".

Each test is a specific way a token can look valid and not be.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from claude_teams.auth import BOT_CONNECTOR_ISSUER, InboundTokenVerifier, TokenError

APP_ID = "11111111-2222-3333-4444-555555555555"
SERVICE_URL = "https://smba.trafficmanager.net/emea/"
KID = "test-key-1"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StubKeyStore:
    """Serves one known key, and nothing else."""

    def __init__(self, keys: dict[str, object] | None = None) -> None:
        self.keys = keys if keys is not None else {KID: _PRIVATE_KEY.public_key()}
        self.lookups: list[str] = []

    async def key_for(self, kid: str) -> object:
        self.lookups.append(kid)
        try:
            return self.keys[kid]
        except KeyError:
            raise TokenError(f"unknown signing key {kid!r}") from None


def make_token(**overrides: object) -> str:
    claims: dict[str, object] = {
        "iss": BOT_CONNECTOR_ISSUER,
        "aud": APP_ID,
        "serviceUrl": SERVICE_URL,
        "exp": int(time.time()) + 300,
        "iat": int(time.time()) - 5,
    }
    claims.update(overrides)
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256", headers={"kid": KID})


def verifier(**overrides: object) -> InboundTokenVerifier:
    kwargs: dict[str, object] = {"app_id": APP_ID, "key_store": StubKeyStore()}
    kwargs.update(overrides)
    return InboundTokenVerifier(**kwargs)  # type: ignore[arg-type]


class TestHappyPath:
    async def test_a_well_formed_token_returns_its_claims(self) -> None:
        claims = await verifier().verify(f"Bearer {make_token()}", service_url=SERVICE_URL)
        assert claims["aud"] == APP_ID

    async def test_the_scheme_is_case_insensitive(self) -> None:
        claims = await verifier().verify(f"bearer {make_token()}", service_url=SERVICE_URL)
        assert claims["aud"] == APP_ID


class TestMissingOrMalformed:
    async def test_no_header_is_rejected(self) -> None:
        with pytest.raises(TokenError, match="Authorization"):
            await verifier().verify(None, service_url=SERVICE_URL)

    async def test_a_non_bearer_scheme_is_rejected(self) -> None:
        with pytest.raises(TokenError, match="Bearer"):
            await verifier().verify(f"Basic {make_token()}", service_url=SERVICE_URL)

    async def test_garbage_is_rejected(self) -> None:
        with pytest.raises(TokenError):
            await verifier().verify("Bearer not-a-token", service_url=SERVICE_URL)


class TestSignature:
    async def test_a_token_signed_by_an_unknown_key_is_rejected(self) -> None:
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = jwt.encode(
            {
                "iss": BOT_CONNECTOR_ISSUER,
                "aud": APP_ID,
                "serviceUrl": SERVICE_URL,
                "exp": int(time.time()) + 300,
            },
            other,
            algorithm="RS256",
            headers={"kid": "some-other-kid"},
        )
        with pytest.raises(TokenError):
            await verifier().verify(f"Bearer {token}", service_url=SERVICE_URL)

    async def test_an_unsigned_token_is_rejected(self) -> None:
        # alg=none is the oldest JWT attack there is and it is a one-line
        # mistake to allow: any library call that decodes before it verifies
        # accepts this token with perfectly correct claims.
        token = jwt.encode({"aud": APP_ID, "iss": BOT_CONNECTOR_ISSUER}, None, algorithm="none")
        with pytest.raises(TokenError):
            await verifier().verify(f"Bearer {token}", service_url=SERVICE_URL)

    async def test_a_symmetric_token_signed_with_the_app_id_is_rejected(self) -> None:
        # Algorithm confusion: the attacker knows the app id (it is in the
        # manifest, which is a file operators hand around) and signs HS256 with
        # it, betting the verifier will use the "public key" as an HMAC secret.
        token = jwt.encode(
            {
                "iss": BOT_CONNECTOR_ISSUER,
                "aud": APP_ID,
                "serviceUrl": SERVICE_URL,
                "exp": int(time.time()) + 300,
            },
            APP_ID,
            algorithm="HS256",
            headers={"kid": KID},
        )
        with pytest.raises(TokenError):
            await verifier().verify(f"Bearer {token}", service_url=SERVICE_URL)


class TestClaims:
    async def test_a_token_for_another_bot_is_rejected(self) -> None:
        token = make_token(aud="22222222-2222-2222-2222-222222222222")
        with pytest.raises(TokenError):
            await verifier().verify(f"Bearer {token}", service_url=SERVICE_URL)

    async def test_an_expired_token_is_rejected(self) -> None:
        token = make_token(exp=int(time.time()) - 600, iat=int(time.time()) - 900)
        with pytest.raises(TokenError):
            await verifier().verify(f"Bearer {token}", service_url=SERVICE_URL)

    async def test_a_token_from_the_wrong_issuer_is_rejected(self) -> None:
        token = make_token(iss="https://evil.example.com")
        with pytest.raises(TokenError):
            await verifier().verify(f"Bearer {token}", service_url=SERVICE_URL)


class TestServiceUrlBinding:
    async def test_a_mismatched_service_url_is_rejected(self) -> None:
        # The activity body says where the reply goes. Without binding it to
        # the token, a replayed-but-genuine token lets someone point this
        # process's outbound calls — carrying its own credentials — at a host
        # they control.
        with pytest.raises(TokenError, match="serviceUrl"):
            await verifier().verify(
                f"Bearer {make_token()}", service_url="https://evil.example.com/"
            )

    async def test_a_trailing_slash_difference_is_tolerated(self) -> None:
        # Teams is inconsistent about the trailing slash between the claim and
        # the activity body, and rejecting on it would break every request.
        claims = await verifier().verify(
            f"Bearer {make_token()}", service_url=SERVICE_URL.rstrip("/")
        )
        assert claims["serviceUrl"] == SERVICE_URL

    async def test_a_token_without_a_service_url_claim_is_rejected(self) -> None:
        token = make_token()
        payload = jwt.decode(token, options={"verify_signature": False})
        del payload["serviceUrl"]
        token = jwt.encode(payload, _PRIVATE_KEY, algorithm="RS256", headers={"kid": KID})
        with pytest.raises(TokenError, match="serviceUrl"):
            await verifier().verify(f"Bearer {token}", service_url=SERVICE_URL)
