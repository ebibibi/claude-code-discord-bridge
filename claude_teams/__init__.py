"""Microsoft Teams frontend for Ebi Agent Chat Relay.

A sibling of :mod:`claude_discord`, not a layer under it. Both packages
implement the same vocabulary from :mod:`claude_code_core.frontend`, and
neither imports the other — which is what keeps "Teams is the degraded copy of
Discord" from becoming true by construction.

Why a separate distribution extra
---------------------------------
Teams needs an inbound HTTPS listener and JWT validation; Discord needs
neither. Making every Discord deployment carry those dependencies to install a
feature it will never call is the sort of weight the project's own guidance
rules out, so the requirements live behind ``pip install
claude-code-discord-bridge[teams]``. Importing this package without them raises
at import time with the install command, rather than at the first inbound
request with a traceback nobody sees.

What is here
------------
Configuration, the real Teams capability numbers, an app-package generator,
inbound token validation, an echo endpoint, and ``TeamsSurface`` — the
:class:`~claude_code_core.frontend.ConversationSurface` implementation, which
the shared conformance contract is run against. What is *not* here yet is
interaction (card actions cannot be routed back) and file transfer; both are
stated as such rather than faked, and the conformance gap is pinned by name in
``tests/test_teams_conformance.py``.
"""

from __future__ import annotations

from .capabilities import TEAMS_CAPABILITIES
from .config import TeamsConfig
from .conversation import ConversationRef
from .surface import TEAMS_FRONTEND, TeamsSurface

__all__ = [
    "TEAMS_CAPABILITIES",
    "TEAMS_FRONTEND",
    "ConversationRef",
    "TeamsConfig",
    "TeamsSurface",
]
