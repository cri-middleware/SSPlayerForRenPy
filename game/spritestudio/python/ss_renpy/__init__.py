"""Ren'Py SSPlayer — SpriteStudio 7 animation playback for Ren'Py.

Layers:
  * ``ssruntime``  — ctypes FFI to libssruntime ("Brain"). No renpy import.
  * ``ssab_meta``  — parse static .ssab metadata (anim names, texture paths).
  * ``framedata``  — walk the per-frame FlatBuffers draw plan (M1+).
  * ``player``     — the Ren'Py Creator-Defined Displayable + public API (M1+).

The first two layers run under plain CPython, which is what the M0 smoke test
(``tools/m0_smoke.py``) exercises.

Layout: ``ss_renpy``, the flatc-generated ``ss.*`` bindings (namespaces
``ss.runtime`` / ``ss.format``), and the vendored pure-Python ``flatbuffers``
runtime are all siblings under this library's ``python/`` directory. Putting
``python/`` on ``sys.path`` makes all three importable; ``bootstrap_paths``
does exactly that.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))   # .../spritestudio/python/ss_renpy
_PY = os.path.dirname(_HERE)                          # .../spritestudio/python


def bootstrap_paths() -> None:
    """Ensure the library's ``python/`` dir is on sys.path.

    Idempotent. Safe to call from both plain CPython and Ren'Py.
    """
    if _PY not in sys.path:
        sys.path.insert(0, _PY)
