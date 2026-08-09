"""The app package, checked for the mistakes Teams reports as silence.

Teams validates a manifest and then, on failure, tells the operator very little
— and on *partial* success tells them nothing at all: the app installs, and
then simply never receives the message they are waiting for. The checks here
are the ones that map to that failure mode.
"""

from __future__ import annotations

import json
import zipfile

import pytest

from claude_teams.config import TeamsConfig
from claude_teams.manifest import build_manifest, write_app_package

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


class TestIdentityFields:
    def test_the_bot_id_is_the_entra_app_id_not_the_manifest_id(self) -> None:
        # The two GUIDs are easy to swap and the symptom is total silence:
        # Teams installs the app and routes messages to a bot id that has no
        # registration behind it.
        cfg = make()
        manifest = build_manifest(cfg)
        assert manifest["bots"][0]["botId"] == cfg.app_id
        assert manifest["id"] == cfg.manifest_id
        assert manifest["id"] != manifest["bots"][0]["botId"]

    def test_valid_domains_lists_the_bare_host(self) -> None:
        manifest = build_manifest(make())
        assert manifest["validDomains"] == ["relay.example.com"]


class TestReceivingChannelMessages:
    def test_resource_specific_consent_is_declared(self) -> None:
        # Without RSC a channel-installed bot only ever sees messages that
        # @mention it, so a thread reads as "the bot ignored me". This is the
        # single most consequential block in the file and the one the reference
        # manifest we studied did not have.
        manifest = build_manifest(make())
        rsc = manifest["authorization"]["permissions"]["resourceSpecific"]
        names = {entry["name"] for entry in rsc}
        assert "ChannelMessage.Read.Group" in names
        assert all(entry["type"] == "Application" for entry in rsc)

    def test_the_bot_is_installable_everywhere_a_conversation_can_happen(self) -> None:
        scopes = build_manifest(make())["bots"][0]["scopes"]
        assert set(scopes) == {"personal", "team", "groupChat"}


class TestSingleSignOn:
    def test_web_application_info_points_at_the_bot_application(self) -> None:
        manifest = build_manifest(make())
        assert manifest["webApplicationInfo"]["id"] == APP_ID
        assert manifest["webApplicationInfo"]["resource"] == f"api://relay.example.com/{APP_ID}"


class TestSecrets:
    def test_the_client_secret_never_reaches_the_manifest(self) -> None:
        # The package is a file the operator uploads and often forwards. A
        # secret in it is a secret in somebody's Downloads folder forever.
        rendered = json.dumps(build_manifest(make(app_password="s3cr3t-value")))
        assert "s3cr3t-value" not in rendered


class TestTeamsLengthLimits:
    def test_an_overlong_short_name_is_rejected_not_truncated(self) -> None:
        # Truncating would produce a working package with a mangled name and no
        # sign anything went wrong. The operator picked the name; they should
        # be the one to shorten it.
        with pytest.raises(ValueError, match="bot_name"):
            build_manifest(make(bot_name="R" * 31))

    def test_an_overlong_short_description_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="short_description"):
            build_manifest(make(short_description="d" * 81))


class TestDeveloperUrlDefaults:
    def test_urls_default_to_the_public_host(self) -> None:
        # Teams requires all three to be valid URLs. Defaulting beats failing
        # on a field nobody deploying internally has an answer for.
        manifest = build_manifest(make())
        assert manifest["developer"]["websiteUrl"] == "https://relay.example.com"
        assert manifest["developer"]["privacyUrl"].startswith("https://relay.example.com")
        assert manifest["developer"]["termsOfUseUrl"].startswith("https://relay.example.com")

    def test_explicit_urls_win(self) -> None:
        manifest = build_manifest(make(privacy_url="https://example.org/privacy"))
        assert manifest["developer"]["privacyUrl"] == "https://example.org/privacy"


class TestPackage:
    def test_the_zip_has_exactly_the_three_files_teams_requires(self, tmp_path) -> None:
        target = tmp_path / "app.zip"
        write_app_package(make(), target)
        with zipfile.ZipFile(target) as zf:
            assert sorted(zf.namelist()) == ["color.png", "manifest.json", "outline.png"]

    def test_the_manifest_in_the_zip_is_the_generated_one(self, tmp_path) -> None:
        target = tmp_path / "app.zip"
        write_app_package(make(), target)
        with zipfile.ZipFile(target) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        assert manifest["bots"][0]["botId"] == APP_ID

    def test_supplied_icons_are_used_verbatim(self, tmp_path) -> None:
        color = tmp_path / "brand.png"
        color.write_bytes(b"\x89PNG\r\n\x1a\nnot-really-a-png")
        target = tmp_path / "app.zip"
        write_app_package(make(), target, color_icon=color)
        with zipfile.ZipFile(target) as zf:
            assert zf.read("color.png") == color.read_bytes()

    def test_generated_icons_are_valid_pngs_of_the_required_sizes(self, tmp_path) -> None:
        # Teams rejects a package whose icons are the wrong dimensions, and the
        # placeholder exists so that a first-time operator can install before
        # they have artwork. A placeholder that fails validation is worthless.
        target = tmp_path / "app.zip"
        write_app_package(make(), target)
        with zipfile.ZipFile(target) as zf:
            assert _png_size(zf.read("color.png")) == (192, 192)
            assert _png_size(zf.read("outline.png")) == (32, 32)


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    assert data[12:16] == b"IHDR", "first chunk is not IHDR"
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
