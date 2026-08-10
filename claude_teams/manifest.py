"""Generate the Teams app package from configuration.

The manifest is written here rather than shipped as a file to edit, because
every value in it that matters is already in :class:`~claude_teams.config.TeamsConfig`
— and a checked-in manifest is a place for one tenant's ids to end up in the
repository.

Two decisions in this file are the interesting ones:

**Resource-specific consent is declared.** Without ``ChannelMessage.Read.Group``
a channel-installed bot only receives messages that @mention it. That turns
"drive a session by talking in the thread" into "prefix every message with a
mention", which is not the product. It is opt-in consent granted by the team
owner at install time, so declaring it costs the operator one checkbox and
nothing else.

**Lengths are validated, never truncated.** Teams enforces short limits on the
name and descriptions. Silently trimming produces a package that installs with
a mangled name; raising hands the choice back to whoever wrote the string.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from .commands import default_menu
from .config import TeamsConfig
from .icons import color_icon_png, outline_icon_png

__all__ = ["MANIFEST_VERSION", "build_manifest", "write_app_package"]

MANIFEST_VERSION = "1.17"
_SCHEMA = (
    "https://developer.microsoft.com/en-us/json-schemas/teams/"
    f"v{MANIFEST_VERSION}/MicrosoftTeams.schema.json"
)

# Teams' own field limits. Exceeding any of them fails app validation.
MAX_SHORT_NAME = 30
MAX_FULL_NAME = 100
MAX_SHORT_DESCRIPTION = 80
MAX_FULL_DESCRIPTION = 4000

# The command menu is generated from :mod:`claude_teams.commands` rather than
# written here. Teams has no slash commands for bots — picking an entry only
# pre-fills the compose box — so these are advertisements for the text router,
# and an advertisement the router does not answer is the failure mode worth
# designing out.


def _checked(value: str, limit: int, field_name: str) -> str:
    if len(value) > limit:
        raise ValueError(f"{field_name} must be at most {limit} characters, got {len(value)}")
    return value


def build_manifest(
    config: TeamsConfig, *, commands: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    """Build the manifest document for *config*.

    Args:
        commands: The command menu. Defaults to what a deployment registering
            the standard commands answers; pass ``router.menu()`` to advertise
            exactly what a custom router handles.

    Raises:
        ValueError: if a field exceeds the length Teams allows.
    """
    menu = default_menu() if commands is None else commands
    site = f"https://{config.public_host}"
    return {
        "$schema": _SCHEMA,
        "manifestVersion": MANIFEST_VERSION,
        "version": config.version,
        "id": config.manifest_id,
        "developer": {
            "name": _checked(config.developer_name, MAX_SHORT_NAME, "developer_name"),
            "websiteUrl": config.website_url or site,
            "privacyUrl": config.privacy_url or f"{site}/privacy",
            "termsOfUseUrl": config.terms_url or f"{site}/terms",
        },
        "icons": {"color": "color.png", "outline": "outline.png"},
        "name": {
            "short": _checked(config.bot_name, MAX_SHORT_NAME, "bot_name"),
            "full": _checked(config.bot_name, MAX_FULL_NAME, "bot_name"),
        },
        "description": {
            "short": _checked(config.short_description, MAX_SHORT_DESCRIPTION, "short_description"),
            "full": _checked(config.long_description, MAX_FULL_DESCRIPTION, "long_description"),
        },
        "accentColor": "#2B579A",
        "bots": [
            {
                "botId": config.app_id,
                "scopes": ["personal", "team", "groupChat"],
                "supportsFiles": True,
                "isNotificationOnly": False,
                "commandLists": [{"scopes": ["personal", "team", "groupChat"], "commands": menu}],
            }
        ],
        "permissions": ["identity", "messageTeamMembers"],
        "validDomains": [config.public_host],
        "authorization": {
            "permissions": {
                "resourceSpecific": [
                    # Read messages in the channel the app is installed in,
                    # without needing an @mention on every turn.
                    {"name": "ChannelMessage.Read.Group", "type": "Application"},
                    # Read the roster so a session can name who asked.
                    {"name": "TeamMember.Read.Group", "type": "Application"},
                ]
            }
        },
        # Single sign-on. Present from the start because the alternative — a
        # second, interactive consent later — is a migration for every already
        # installed tenant.
        "webApplicationInfo": {
            "id": config.app_id,
            "resource": f"api://{config.public_host}/{config.app_id}",
        },
    }


def write_app_package(
    config: TeamsConfig,
    target: Path,
    *,
    color_icon: Path | None = None,
    outline_icon: Path | None = None,
    commands: list[dict[str, str]] | None = None,
) -> Path:
    """Write the installable ``.zip`` for *config* and return its path.

    Args:
        target: Where to write the package.
        color_icon: 192x192 PNG. Generated as a flat placeholder when omitted.
        outline_icon: 32x32 white-on-transparent PNG. Likewise.
    """
    manifest = build_manifest(config, commands=commands)
    color = color_icon.read_bytes() if color_icon else color_icon_png()
    outline = outline_icon.read_bytes() if outline_icon else outline_icon_png()

    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        zf.writestr("color.png", color)
        zf.writestr("outline.png", outline)
    return target
