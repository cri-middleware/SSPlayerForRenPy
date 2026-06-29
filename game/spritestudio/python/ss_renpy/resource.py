"""Resource seam for the engine-independent playback core (no ``renpy`` import).

:class:`~ss_renpy.player.SSInternalPlayer` never owns texture lifetime. When an
animation is set up it asks an injected :class:`ResourceManager` to *ensure*
(``acquire``) each texture that animation needs; the host (Ren'Py) backs that
with its own image/texture cache and, at draw time, hands a native handle back
via ``get``. Headless callers use :class:`RecordingResourceManager`, which
records the requested paths but loads nothing.

A *pack reader* is just a ``Callable[[str], bytes]`` mapping an external
instance pack **name** to its ``.ssab`` bytes; :func:`filesystem_pack_reader`
is the obvious on-disk implementation used by the headless tools. It is kept
separate from the texture base dir on purpose: texture paths are host-relative
identifiers handed to the ResourceManager, while pack bytes are read by whatever
mechanism the host owns (filesystem, Ren'Py loader, archive, ...).
"""

from __future__ import annotations

import os
from typing import Callable, List


class ResourceManager:
    """Host-provided texture cache. The core only ever calls :meth:`acquire`."""

    def acquire(self, path: str) -> None:
        """Ensure the texture identified by ``path`` is loaded / cached.

        Called by the core from ``set_animation`` and as external instance packs
        are discovered. ``path`` is a host-relative texture identifier (for
        Ren'Py, a gamedir-relative image path). Must be idempotent and cheap to
        call repeatedly.
        """
        raise NotImplementedError

    def get(self, path: str):
        """Return the host texture handle for ``path``, or ``None``.

        Used by the *render* layer, never by the core; the default returns
        ``None`` so a headless core needs no implementation.
        """
        return None


class RecordingResourceManager(ResourceManager):
    """Headless :class:`ResourceManager`: records acquired paths, loads nothing.

    ``acquired`` preserves first-seen order; ``acquired_set`` is for membership
    tests. Handy for asserting *which* textures ``set_animation`` requested.
    """

    def __init__(self) -> None:
        self.acquired: List[str] = []
        self.acquired_set = set()

    def acquire(self, path: str) -> None:
        if path and path not in self.acquired_set:
            self.acquired_set.add(path)
            self.acquired.append(path)


# A pack reader maps an external-instance pack NAME to its ``.ssab`` bytes.
PackReader = Callable[[str], bytes]


def filesystem_pack_reader(base_dir: str) -> PackReader:
    """:data:`PackReader` reading ``<base_dir>/<pack_name>.ssab`` from disk.

    Returns ``b""`` when the pack is absent so the caller skips that instance
    gracefully (matching the rig's tolerant behaviour).
    """

    def read(pack_name: str) -> bytes:
        path = os.path.join(base_dir, pack_name + ".ssab")
        if os.path.exists(path):
            with open(path, "rb") as fh:
                return fh.read()
        return b""

    return read
