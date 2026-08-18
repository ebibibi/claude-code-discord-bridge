"""The frontend contract, and the reference implementation that proves it fits.

``check_surface`` covers one conversation; this covers the object that hands
them out. Both matter for the same reason: a Teams frontend that implements the
methods but breaks an unwritten obligation would fail in production, not in CI.
"""

from __future__ import annotations

from claude_code_core.conformance import check_frontend
from claude_code_core.memory_surface import MemoryFrontend


async def test_memory_frontend_passes_the_contract() -> None:
    async def make() -> MemoryFrontend:
        return MemoryFrontend()

    report = await check_frontend(make, parent_id="channel-1")

    assert report.ok, report.summary()


async def test_the_contract_catches_a_frontend_that_forgets_its_conversations() -> None:
    """The failure this suite exists for: a follow-up opening a second thread.

    Forgetting is invisible from the outside — every call succeeds, and the
    scheduler cheerfully posts into a thread nobody is reading.
    """

    class Forgetful(MemoryFrontend):
        async def resolve_surface(self, thread_key):  # noqa: ANN001, ANN201
            return None

    async def make() -> Forgetful:
        return Forgetful()

    report = await check_frontend(make, parent_id="channel-1")

    assert not report.ok
    assert any("resolve" in failure for failure in report.failures), report.summary()


async def test_the_contract_catches_colliding_thread_keys() -> None:
    """Two conversations sharing a key means one session overwrites the other."""

    class Colliding(MemoryFrontend):
        async def create_surface(self, *, parent_id: str, title: str):  # noqa: ANN201
            return await super().create_surface(parent_id="fixed", title=title)

        async def resolve_surface(self, thread_key):  # noqa: ANN001, ANN201
            return await super().resolve_surface(thread_key)

    class Stuck(Colliding):
        async def create_surface(self, *, parent_id: str, title: str):  # noqa: ANN201
            surface = await MemoryFrontend.create_surface(self, parent_id="same", title=title)
            self._surfaces.clear()
            self._surfaces[surface.thread_key] = surface
            object.__setattr__(surface, "_thread_key", 42)
            return surface

    async def make() -> Stuck:
        return Stuck()

    report = await check_frontend(make, parent_id="channel-1")

    assert not report.ok


async def test_two_frontends_never_mint_the_same_key() -> None:
    """Scoping by frontend name is what keeps a Teams key out of Discord's space."""
    discord_like = MemoryFrontend(name="discord-ish")
    teams_like = MemoryFrontend(name="teams-ish")

    a = await discord_like.create_surface(parent_id="c1", title="t")
    b = await teams_like.create_surface(parent_id="c1", title="t")

    assert a.external_id == b.external_id
    assert a.thread_key != b.thread_key
