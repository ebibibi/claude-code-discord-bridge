"""``python -m claude_teams`` — build the app package an operator uploads.

Generating rather than checking in the manifest keeps one tenant's ids out of
the repository, and means the package can never disagree with the environment
the bot will actually run in: both read the same variables.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import TeamsConfig
from .manifest import write_app_package


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m claude_teams",
        description="Generate the Microsoft Teams app package for this deployment.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    package = sub.add_parser("manifest", help="Write the installable app package (.zip)")
    package.add_argument(
        "--out",
        type=Path,
        default=Path("dist/teams-app.zip"),
        help="Where to write the package (default: dist/teams-app.zip)",
    )
    package.add_argument("--color-icon", type=Path, help="192x192 PNG (a placeholder is generated)")
    package.add_argument("--outline-icon", type=Path, help="32x32 white-on-transparent PNG")

    args = parser.parse_args(argv)

    try:
        config = TeamsConfig.from_env(os.environ)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        target = write_app_package(
            config,
            args.out,
            color_icon=args.color_icon,
            outline_icon=args.outline_icon,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    generated = not (args.color_icon and args.outline_icon)
    print(f"wrote {target}")
    print(f"  Teams app id      {config.manifest_id}")
    print(f"  bot (Entra) app   {config.app_id}")
    print(f"  messaging endpoint {config.messaging_endpoint}")
    print("\nSet that messaging endpoint on the Azure Bot resource, then upload the zip.")
    if generated:
        print("Icons are placeholders — pass --color-icon/--outline-icon before publishing.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
