"""Proving an inbound request really came from the Bot Connector.

Discord's transport was outbound-only: the bot dialled out over a websocket and
nothing on the internet could reach it. Teams reverses that. The endpoint is a
public HTTPS URL, and behind it sit coding-agent sessions with a shell. The
verification in this module is therefore not an authentication nicety — it is
the entire boundary.

The rules come from the Bot Framework authentication specification:

* signature must verify against a key published at the Bot Connector's OpenID
  metadata document, using an asymmetric algorithm we name explicitly
* ``iss`` must be the Bot Connector's issuer
* ``aud`` must be this bot's application id
* the token must be unexpired
* the ``serviceUrl`` claim must match the activity's own ``serviceUrl``

That last one carries more weight than it looks like. The activity body tells
this process where to send its reply, and the reply carries this process's
credentials. Without binding the two, a genuine token replayed with a doctored
body aims our authenticated outbound calls at a host of the caller's choosing.

Algorithms are pinned rather than taken from the token header, because the
header is attacker-controlled: the app id is printed in the manifest, and a
verifier that honours ``alg`` will happily treat an RSA public key as an HMAC
secret if asked.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

import jwt

__all__ = [
    "BOT_CONNECTOR_ISSUER",
    "BOT_CONNECTOR_OPENID_METADATA",
    "InboundTokenVerifier",
    "KeyStore",
    "TokenError",
]

#: Issuer of tokens the Bot Connector mints for channel traffic.
BOT_CONNECTOR_ISSUER = "https://api.botframework.com"

#: Where the connector publishes its signing keys.
BOT_CONNECTOR_OPENID_METADATA = "https://login.botframework.com/v1/.well-known/openidconfiguration"

#: The only signature algorithms accepted, regardless of what a token claims.
ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512")

#: Clock skew tolerated on ``exp`` / ``iat``, in seconds.
DEFAULT_LEEWAY = 60


class TokenError(Exception):
    """An inbound token was absent, malformed, or not trustworthy.

    Deliberately one type with no subclasses: the endpoint answers 401 to all
    of them and tells the caller nothing further, because distinguishing
    "expired" from "wrong audience" in a response is free reconnaissance.
    """


class KeyStore(Protocol):
    """Supplies the public key for a token's ``kid``."""

    async def key_for(self, kid: str) -> Any:
        """Return the public key, or raise :class:`TokenError` if unknown."""
        ...


class InboundTokenVerifier:
    """Verifies ``Authorization`` headers on inbound Teams activities."""

    def __init__(
        self,
        app_id: str,
        key_store: KeyStore,
        *,
        issuer: str = BOT_CONNECTOR_ISSUER,
        leeway: int = DEFAULT_LEEWAY,
    ) -> None:
        self.app_id = app_id
        self.key_store = key_store
        self.issuer = issuer
        self.leeway = leeway

    async def verify(self, authorization: str | None, *, service_url: str | None) -> dict[str, Any]:
        """Verify a header and return the token's claims.

        Args:
            authorization: The raw ``Authorization`` header value.
            service_url: The ``serviceUrl`` from the activity body, which the
                token must agree with.

        Raises:
            TokenError: for every failure, with no detail beyond what is safe
                to log locally.
        """
        token = _bearer_token(authorization)
        kid = _kid(token)
        key = await self.key_store.key_for(kid)

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self.app_id,
                issuer=self.issuer,
                leeway=self.leeway,
                options={"require": ["exp", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise TokenError(f"token rejected: {exc}") from exc

        _check_service_url(claims, service_url)
        return claims

    # Kept as a method so a caller holding only the verifier can answer
    # "is this token still good?" without re-deriving the leeway.
    def is_expired(self, claims: dict[str, Any]) -> bool:
        exp = claims.get("exp")
        return not isinstance(exp, int | float) or exp + self.leeway < time.time()


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise TokenError("missing Authorization header")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise TokenError("Authorization header must be a Bearer token")
    return value.strip()


def _kid(token: str) -> str:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise TokenError(f"malformed token header: {exc}") from exc
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise TokenError("token header has no kid")
    # Read only to select a key. The algorithm the token asks for is ignored:
    # the allow-list passed to decode() is what actually governs.
    return kid


def _check_service_url(claims: dict[str, Any], service_url: str | None) -> None:
    claimed = claims.get("serviceUrl")
    if not isinstance(claimed, str) or not claimed:
        raise TokenError("token has no serviceUrl claim")
    if service_url is None:
        raise TokenError("activity has no serviceUrl to match against the token")
    if claimed.rstrip("/") != service_url.rstrip("/"):
        raise TokenError("serviceUrl does not match the token")
