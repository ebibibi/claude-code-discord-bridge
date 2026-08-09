"""Everything a Teams deployment must state about itself.

Teams asks for more up-front identity than Discord did. Discord needed one
token; Teams needs an Entra application, a tenant, a publicly reachable HTTPS
host, and an app package whose manifest agrees with all three. Any one of them
being wrong produces the same symptom — nothing arrives — so the value of this
module is that it turns each of those silences into a named exception before
the bot starts.

Nothing here is tenant-specific: every value comes from the environment,
because the whole point of the packaging work is that this can be handed to
somebody else's tenant unchanged.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = ["TeamsConfig"]

_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# A bare DNS host: labels of letters/digits/hyphens joined by dots. Deliberately
# rejects anything carrying a scheme, port, path or userinfo, because Teams'
# ``validDomains`` takes a host and merely fails validation otherwise.
_HOST = re.compile(r"^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$")

#: Namespace for deriving a stable Teams app id from an Entra app id. The value
#: is arbitrary but must never change: changing it would re-issue every
#: deployment's manifest id, and Teams treats a new manifest id as a different
#: app.
_MANIFEST_NAMESPACE = uuid.UUID("6f1c0f6e-9a1e-5f6d-9c1a-2b7f2f5a4d10")

DEFAULT_ENDPOINT_PATH = "/api/teams/messages"
DEFAULT_BOT_NAME = "Agent Relay"
DEFAULT_SHORT_DESCRIPTION = "Drive Claude Code and Codex sessions from Teams."
DEFAULT_LONG_DESCRIPTION = (
    "Ebi Agent Chat Relay runs coding-agent sessions inside a chat thread: "
    "streamed output, tool approvals, file delivery and parallel sessions."
)
DEFAULT_DEVELOPER_NAME = "Ebi Agent Chat Relay"
DEFAULT_VERSION = "1.0.0"


@dataclass(frozen=True)
class TeamsConfig:
    """Identity and addressing for one Teams deployment.

    Args:
        app_id: Entra application (client) id of the bot. Teams puts this in
            ``bots[].botId``, and inbound tokens are audienced to it.
        tenant_id: The tenant the bot's application lives in. Required even for
            a multi-tenant bot, because the outbound token is fetched there.
        public_host: The bare DNS host Teams will call. Not a URL.
        app_password: The client secret, when password auth is used. Optional,
            because generating a manifest — the one thing an operator does
            *before* they have a secret — must not require one.
    """

    app_id: str
    tenant_id: str
    public_host: str
    app_password: str | None = field(default=None, repr=False)
    endpoint_path: str = DEFAULT_ENDPOINT_PATH
    bot_name: str = DEFAULT_BOT_NAME
    short_description: str = DEFAULT_SHORT_DESCRIPTION
    long_description: str = DEFAULT_LONG_DESCRIPTION
    developer_name: str = DEFAULT_DEVELOPER_NAME
    website_url: str = ""
    privacy_url: str = ""
    terms_url: str = ""
    version: str = DEFAULT_VERSION
    #: The Bot Connector host this tenant is served from. Optional, and worth
    #: setting: without it a scheduled post into a conversation this process
    #: has not heard from since starting has nowhere to go.
    service_url: str = ""
    #: The Teams app id. Left unset it is derived from ``app_id`` — deriving
    #: rather than generating matters, because a random id would change on
    #: every build and every already-installed conversation would quietly stop
    #: being served by the app the operator just published.
    manifest_id: str = ""

    def __post_init__(self) -> None:
        if not _GUID.match(self.app_id):
            raise ValueError(f"app_id must be a GUID, got {self.app_id!r}")
        if not _GUID.match(self.tenant_id):
            raise ValueError(f"tenant_id must be a GUID, got {self.tenant_id!r}")
        if not _HOST.match(self.public_host):
            raise ValueError(
                "public_host must be a bare DNS host with no scheme, port or path, "
                f"got {self.public_host!r}"
            )
        if not self.endpoint_path.startswith("/"):
            raise ValueError(f"endpoint_path must start with '/', got {self.endpoint_path!r}")
        if not self.manifest_id:
            object.__setattr__(
                self, "manifest_id", str(uuid.uuid5(_MANIFEST_NAMESPACE, self.app_id))
            )
        elif not _GUID.match(self.manifest_id):
            raise ValueError(f"manifest_id must be a GUID, got {self.manifest_id!r}")

    @property
    def messaging_endpoint(self) -> str:
        """The URL to paste into the Azure Bot resource's messaging endpoint."""
        return f"https://{self.public_host}{self.endpoint_path}"

    @property
    def can_send_outbound(self) -> bool:
        """Whether this config carries enough to authenticate an outbound call."""
        return bool(self.app_password)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> TeamsConfig:
        """Build from environment variables, naming any that are missing.

        Raises:
            ValueError: naming the variable, so the operator does not have to
                map a field name back to the export they forgot.
        """

        def required(name: str) -> str:
            value = env.get(name, "").strip()
            if not value:
                raise ValueError(f"{name} is required for the Teams frontend")
            return value

        def optional(name: str, default: str = "") -> str:
            return env.get(name, "").strip() or default

        return cls(
            app_id=required("CCDB_TEAMS_APP_ID"),
            tenant_id=required("CCDB_TEAMS_TENANT_ID"),
            public_host=required("CCDB_TEAMS_PUBLIC_HOST"),
            app_password=optional("CCDB_TEAMS_APP_PASSWORD") or None,
            endpoint_path=optional("CCDB_TEAMS_ENDPOINT_PATH", DEFAULT_ENDPOINT_PATH),
            bot_name=optional("CCDB_TEAMS_BOT_NAME", DEFAULT_BOT_NAME),
            short_description=optional("CCDB_TEAMS_SHORT_DESCRIPTION", DEFAULT_SHORT_DESCRIPTION),
            long_description=optional("CCDB_TEAMS_LONG_DESCRIPTION", DEFAULT_LONG_DESCRIPTION),
            developer_name=optional("CCDB_TEAMS_DEVELOPER_NAME", DEFAULT_DEVELOPER_NAME),
            website_url=optional("CCDB_TEAMS_WEBSITE_URL"),
            privacy_url=optional("CCDB_TEAMS_PRIVACY_URL"),
            terms_url=optional("CCDB_TEAMS_TERMS_URL"),
            version=optional("CCDB_TEAMS_APP_VERSION", DEFAULT_VERSION),
            service_url=optional("CCDB_TEAMS_SERVICE_URL"),
            manifest_id=optional("CCDB_TEAMS_MANIFEST_ID"),
        )
