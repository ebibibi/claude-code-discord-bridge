"""Placeholder app icons, written without an imaging dependency.

Teams will not install a package whose icons are missing or the wrong size, and
the icons are the one part of the package a first-time operator does not have
yet. Generating a valid placeholder means ``ccdb teams manifest`` produces
something installable on the first run; supplying real artwork stays a flag.

Pillow is already an optional extra of this project, but reaching for it here
would make the Teams extra depend on an imaging library to draw two solid
rectangles. A PNG of a single colour is a header, one zlib stream and a
checksum — about forty lines, no dependency, and no version to keep current.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Callable

__all__ = ["color_icon_png", "outline_icon_png"]

Pixel = tuple[int, int, int, int]

#: Teams' required icon dimensions. Both are rejected at any other size.
COLOR_ICON_SIZE = 192
OUTLINE_ICON_SIZE = 32

#: The accent used for the placeholder colour icon.
_ACCENT: Pixel = (0x2B, 0x57, 0x9A, 0xFF)
_TRANSPARENT: Pixel = (0, 0, 0, 0)
_WHITE: Pixel = (0xFF, 0xFF, 0xFF, 0xFF)

#: Thickness of the outline icon's ring, in pixels.
_RING = 3


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def _png(size: int, pixel: Callable[[int, int], Pixel]) -> bytes:
    """Encode a square RGBA PNG whose colour at (x, y) is ``pixel(x, y)``.

    Uses filter type 0 (none) on every scanline: the images are flat, so a
    predictor would buy nothing and cost the only complexity in this file.
    """
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            raw.extend(pixel(x, y))
    # Bit depth 8, colour type 6 (RGBA), default compression/filter/interlace.
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


def color_icon_png() -> bytes:
    """A 192x192 solid accent square — the full-colour app icon."""
    return _png(COLOR_ICON_SIZE, lambda _x, _y: _ACCENT)


def outline_icon_png() -> bytes:
    """A 32x32 white ring on transparency — the monochrome outline icon.

    Teams tints this one, so it must be white-on-transparent; anything else
    renders as a grey blob in the activity rail.
    """
    edge = OUTLINE_ICON_SIZE - 1

    def pixel(x: int, y: int) -> Pixel:
        on_ring = min(x, y, edge - x, edge - y) < _RING
        return _WHITE if on_ring else _TRANSPARENT

    return _png(OUTLINE_ICON_SIZE, pixel)
