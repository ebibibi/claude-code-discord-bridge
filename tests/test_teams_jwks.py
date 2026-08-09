"""Key caching, rotation and the refresh amplifier that comes with it."""

from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from claude_teams.auth import TokenError
from claude_teams.jwks import OpenIdKeyStore

METADATA_URL = "https://login.example.com/openid"
JWKS_URL = "https://login.example.com/keys"


def jwk_for(kid: str) -> dict[str, object]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = kid
    return jwk


class FakeHttp:
    """Serves a metadata document and a JWKS set that the test can swap."""

    def __init__(self, kids: list[str]) -> None:
        self.jwks = {"keys": [jwk_for(kid) for kid in kids]}
        self.calls: list[str] = []

    async def __call__(self, url: str) -> dict[str, object]:
        self.calls.append(url)
        if url == METADATA_URL:
            return {"jwks_uri": JWKS_URL}
        return self.jwks

    def rotate_to(self, kids: list[str]) -> None:
        self.jwks = {"keys": [jwk_for(kid) for kid in kids]}


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def store(http: FakeHttp, clock: Clock, **overrides: object) -> OpenIdKeyStore:
    kwargs: dict[str, object] = {"metadata_url": METADATA_URL, "now": clock}
    kwargs.update(overrides)
    return OpenIdKeyStore(http, **kwargs)  # type: ignore[arg-type]


class TestCaching:
    async def test_the_document_is_fetched_once_for_repeated_lookups(self) -> None:
        http, clock = FakeHttp(["a"]), Clock()
        s = store(http, clock)
        await s.key_for("a")
        await s.key_for("a")
        assert http.calls == [METADATA_URL, JWKS_URL]


class TestRotation:
    async def test_an_unknown_kid_triggers_a_refresh(self) -> None:
        # A time-based cache alone would reject every request between a
        # rotation and the next expiry, and recover by itself — the hardest
        # kind of outage to catch in the act.
        http, clock = FakeHttp(["old"]), Clock()
        s = store(http, clock, min_refresh_interval=60.0)
        await s.key_for("old")

        http.rotate_to(["new"])
        clock.t += 61
        assert await s.key_for("new") is not None

    async def test_a_refresh_inside_the_floor_is_refused(self) -> None:
        # This path is reachable by anyone who can send a token, so an
        # unthrottled refresh is both an amplifier aimed at the key server and
        # a way to stall the endpoint.
        http, clock = FakeHttp(["old"]), Clock()
        s = store(http, clock, min_refresh_interval=300.0)
        await s.key_for("old")
        before = len(http.calls)

        http.rotate_to(["new"])
        with pytest.raises(TokenError, match="unknown signing key"):
            await s.key_for("new")
        assert len(http.calls) == before

    async def test_keys_are_refetched_once_they_age_out(self) -> None:
        # Bounds how long a key withdrawn upstream keeps being honoured here.
        http, clock = FakeHttp(["a"]), Clock()
        s = store(http, clock, min_refresh_interval=1.0, max_key_age=3600.0)
        await s.key_for("a")
        before = len(http.calls)

        clock.t += 3601
        await s.key_for("a")
        assert len(http.calls) > before


class TestMalformedDocuments:
    async def test_metadata_without_a_jwks_uri_is_an_error(self) -> None:
        async def fetch(_url: str) -> dict[str, object]:
            return {"issuer": "https://example.com"}

        s = OpenIdKeyStore(fetch, metadata_url=METADATA_URL)
        with pytest.raises(TokenError, match="jwks_uri"):
            await s.key_for("a")

    async def test_one_unusable_key_does_not_poison_the_set(self) -> None:
        # The connector publishes keys for algorithms this verifier does not
        # accept. Failing the whole document over one of them would take the
        # endpoint down for a reason that is not a problem.
        http, clock = FakeHttp(["good"]), Clock()
        http.jwks["keys"].append({"kid": "broken", "kty": "RSA", "n": "!!!", "e": "AQAB"})
        s = store(http, clock)
        assert await s.key_for("good") is not None

    async def test_a_document_with_no_usable_keys_is_an_error(self) -> None:
        async def fetch(url: str) -> dict[str, object]:
            if url == METADATA_URL:
                return {"jwks_uri": JWKS_URL}
            return {"keys": []}

        s = OpenIdKeyStore(fetch, metadata_url=METADATA_URL)
        with pytest.raises(TokenError, match="no usable keys"):
            await s.key_for("a")
