"""What a Teams deployment must state before it is allowed to start.

The theme of these tests is *fail at import, not in production*. A Teams bot
whose manifest points at the wrong domain, or whose app id is a display name
somebody pasted by mistake, does not fail loudly — Teams simply never delivers
a message, and the operator is left staring at a bot that "does nothing".
Every check here converts one of those silences into an exception.
"""

from __future__ import annotations

import pytest

from claude_teams.config import TeamsConfig

APP_ID = "11111111-2222-3333-4444-555555555555"
TENANT = "99999999-8888-7777-6666-555555555555"


def make(**overrides: object) -> TeamsConfig:
    kwargs: dict[str, object] = {
        "app_id": APP_ID,
        "tenant_id": TENANT,
        "public_host": "relay.example.com",
    }
    kwargs.update(overrides)
    return TeamsConfig(**kwargs)  # type: ignore[arg-type]


class TestIdentity:
    def test_an_app_id_that_is_not_a_guid_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="app_id"):
            make(app_id="my-bot")

    def test_a_tenant_id_that_is_not_a_guid_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            make(tenant_id="contoso.onmicrosoft.com")

    def test_the_manifest_id_is_derived_and_stable(self) -> None:
        # Two ids exist: the Entra app id (the bot) and the Teams app id (the
        # package). Making the operator invent a second GUID is a step they can
        # get wrong, so it is derived — and derived deterministically, because
        # a manifest whose id changes between builds installs as a *new* app
        # and orphans every existing conversation.
        assert make().manifest_id == make().manifest_id
        assert make().manifest_id != make(app_id=TENANT).manifest_id

    def test_an_explicit_manifest_id_wins(self) -> None:
        explicit = "abcdefab-1234-1234-1234-abcdefabcdef"
        assert make(manifest_id=explicit).manifest_id == explicit


class TestPublicHost:
    def test_a_host_with_a_scheme_is_rejected(self) -> None:
        # validDomains takes a bare host. Pasting the endpoint URL in here is
        # the single most common manifest mistake and Teams reports it as
        # "app validation failed" with no hint at which field.
        with pytest.raises(ValueError, match="public_host"):
            make(public_host="https://relay.example.com")

    def test_a_host_with_a_path_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="public_host"):
            make(public_host="relay.example.com/api/messages")

    def test_a_bare_host_is_accepted(self) -> None:
        assert make(public_host="relay.example.com").public_host == "relay.example.com"

    def test_the_messaging_endpoint_is_built_from_the_host(self) -> None:
        cfg = make(public_host="relay.example.com", endpoint_path="/api/teams/messages")
        assert cfg.messaging_endpoint == "https://relay.example.com/api/teams/messages"

    def test_the_endpoint_path_must_be_absolute(self) -> None:
        with pytest.raises(ValueError, match="endpoint_path"):
            make(endpoint_path="api/teams/messages")


class TestSecrets:
    def test_the_password_never_appears_in_a_repr(self) -> None:
        # Configs get logged on startup failures. A secret that survives repr()
        # ends up in journalctl, and from there in a pasted bug report.
        cfg = make(app_password="s3cr3t-value")
        assert "s3cr3t-value" not in repr(cfg)

    def test_a_config_without_a_password_cannot_send(self) -> None:
        assert make().can_send_outbound is False
        assert make(app_password="s3cr3t-value").can_send_outbound is True


class TestFromEnv:
    def test_missing_app_id_is_an_error_naming_the_variable(self) -> None:
        with pytest.raises(ValueError, match="CCDB_TEAMS_APP_ID"):
            TeamsConfig.from_env({})

    def test_an_empty_variable_is_treated_as_missing(self) -> None:
        # An exported-but-empty variable is the classic way a .env edit half
        # lands. Treating "" as set would produce a GUID validation error that
        # points at the wrong problem.
        with pytest.raises(ValueError, match="CCDB_TEAMS_APP_ID"):
            TeamsConfig.from_env({"CCDB_TEAMS_APP_ID": "  "})

    def test_a_full_environment_round_trips(self) -> None:
        cfg = TeamsConfig.from_env(
            {
                "CCDB_TEAMS_APP_ID": APP_ID,
                "CCDB_TEAMS_TENANT_ID": TENANT,
                "CCDB_TEAMS_APP_PASSWORD": "s3cr3t-value",
                "CCDB_TEAMS_PUBLIC_HOST": "relay.example.com",
                "CCDB_TEAMS_BOT_NAME": "Relay",
            }
        )
        assert cfg.app_id == APP_ID
        assert cfg.bot_name == "Relay"
        assert cfg.can_send_outbound is True
