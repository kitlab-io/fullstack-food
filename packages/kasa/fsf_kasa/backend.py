"""TP-Link Kasa strips through the python-kasa library (`pip install python-kasa`).

Never run against a real strip: written from the library's documented interface. Treat it
as a first draft until `fsf node test <node> --actuate` has passed against hardware.
"""

from __future__ import annotations

import asyncio

from .bridge import PlugError


class KasaBackend:
    def __init__(self, host: str, timeout_s: float = 10.0):
        try:
            import kasa  # noqa: F401
        except ImportError:
            raise PlugError("python-kasa is not installed; pip install python-kasa") from None
        self.host, self.timeout_s = host, timeout_s

    async def _outlet(self, outlet: int):
        from kasa import Discover

        device = await Discover.discover_single(self.host, timeout=self.timeout_s)
        await device.update()
        children = getattr(device, "children", None) or [device]       # a single plug has no children
        if outlet >= len(children):
            raise PlugError(f"{self.host} has {len(children)} outlet(s); outlet {outlet} does not exist")
        return device, children[outlet]

    def _run(self, coroutine):
        try:
            return asyncio.run(asyncio.wait_for(coroutine, self.timeout_s * 2))
        except PlugError:
            raise
        except Exception as err:    # the library raises its own errors, and timeouts, for an unreachable strip
            raise PlugError(f"{self.host}: {err}") from None

    def set(self, outlet: int, on: bool) -> None:
        async def go():
            device, child = await self._outlet(outlet)
            try:
                await (child.turn_on() if on else child.turn_off())
            finally:
                await device.disconnect()
        self._run(go())

    def is_on(self, outlet: int) -> bool:
        async def go():
            device, child = await self._outlet(outlet)
            try:
                return bool(child.is_on)
            finally:
                await device.disconnect()
        return self._run(go())
