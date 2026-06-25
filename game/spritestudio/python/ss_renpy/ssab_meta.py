"""Parse the ``.ssab`` metadata that the Brain does not surface over the C-API.

The runtime intentionally returns only a per-frame *draw plan* (FrameData) plus
SoA buffers — it never hands back the static project structure (animation
names, cellmap → image-path mapping, etc.). A Player needs that to:

  * enumerate selectable animation names (M0/M1), and
  * resolve ``DrawBatch.texture_hash`` to a concrete PNG file (M1/M2, Reference
    method).

We parse it straight from the ``.ssab`` FlatBuffer using the generated
``ss.format.SsAnimeBinary`` bindings.
"""

from __future__ import annotations

from dataclasses import dataclass

from ss.format.SsAnimeBinary import SsAnimeBinary


def _s(maybe_bytes) -> str:
    if maybe_bytes is None:
        return ""
    if isinstance(maybe_bytes, bytes):
        return maybe_bytes.decode("utf-8", "replace")
    return str(maybe_bytes)


@dataclass(frozen=True)
class AnimationInfo:
    name: str
    name_hash: int
    fps: int
    start_frame: int
    end_frame: int
    total_frame: int


@dataclass(frozen=True)
class CellMapInfo:
    name: str
    name_hash: int
    image_path: str
    image_path_hash: int


class SsabMeta:
    """Lazy, read-only view over a ``.ssab`` byte buffer."""

    def __init__(self, data: bytes):
        # Keep the buffer alive: the FlatBuffers accessors index into it.
        self._buf = data
        self._root = SsAnimeBinary.GetRootAs(data, 0)

    @property
    def name(self) -> str:
        return _s(self._root.Name())

    def animations(self) -> list[AnimationInfo]:
        out: list[AnimationInfo] = []
        for i in range(self._root.AnimationsLength()):
            a = self._root.Animations(i)
            out.append(AnimationInfo(
                name=_s(a.Name()),
                name_hash=a.NameHash(),
                fps=a.Fps(),
                start_frame=a.StartFrame(),
                end_frame=a.EndFrame(),
                total_frame=a.TotalFrame(),
            ))
        return out

    def animation_names(self) -> list[str]:
        return [a.name for a in self.animations()]

    def cellmaps(self) -> list[CellMapInfo]:
        out: list[CellMapInfo] = []
        for i in range(self._root.CellmapsLength()):
            c = self._root.Cellmaps(i)
            out.append(CellMapInfo(
                name=_s(c.Name()),
                name_hash=c.NameHash(),
                image_path=_s(c.ImagePath()),
                image_path_hash=c.ImagePathHash(),
            ))
        return out

    def texture_hash_map(self) -> dict[int, str]:
        """Map every plausible ``DrawBatch.texture_hash`` key to its image path.

        ``DrawBatch.texture_hash`` is an FNV1a hash tied to the cellmap. The SDK
        carries both the cellmap *name* hash and the *image-path* hash, so we
        register both as keys to the same image path — whichever the runtime
        emits, lookups resolve. (M1 confirms which one is actually used.)
        """
        m: dict[int, str] = {}
        for c in self.cellmaps():
            if c.image_path:
                m[c.name_hash] = c.image_path
                m[c.image_path_hash] = c.image_path
        return m


def load(path: str) -> SsabMeta:
    with open(path, "rb") as fh:
        return SsabMeta(fh.read())
