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

from ss.format.PartType import PartType
from ss.format.PartTypeEffect import PartTypeEffect
from ss.format.PartTypeInstance import PartTypeInstance
from ss.format.SsAnimeBinary import SsAnimeBinary

# PartType union discriminators we special-case (see ss/format/PartType.py).
PART_TYPE_NORMAL = PartType.PartTypeNormal      # 2
PART_TYPE_INSTANCE = PartType.PartTypeInstance  # 6
PART_TYPE_EFFECT = PartType.PartTypeEffect      # 8


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


@dataclass(frozen=True)
class PartInfo:
    """Static per-part data (index == ``PartState.part_index`` == slot_index).

    ``part_type`` is the :class:`PartType` union discriminator. For Instance
    parts the ``ref_anime_*`` fields name the referenced pack/animation; for
    Effect parts ``ref_effect_name_hash`` keys the embedded effect. All ref
    fields are empty/0 for other part types.
    """
    index: int
    name: str
    parent_index: int
    part_type: int
    ref_anime_pack: str = ""
    ref_anime_pack_hash: int = 0
    ref_anime_name: str = ""
    ref_anime_name_hash: int = 0
    ref_effect_name_hash: int = 0

    @property
    def is_instance(self) -> bool:
        return self.part_type == PART_TYPE_INSTANCE

    @property
    def is_effect(self) -> bool:
        return self.part_type == PART_TYPE_EFFECT


@dataclass(frozen=True)
class ExternalInstanceInfo:
    """An external ``.ssab`` referenced by an Instance part (must be loaded)."""
    anime_pack_name: str
    anime_pack_name_hash: int
    anime_name: str
    anime_name_hash: int


@dataclass(frozen=True)
class EffectInfo:
    name: str
    name_hash: int
    fps: int


class SsabMeta:
    """Lazy, read-only view over a ``.ssab`` byte buffer."""

    def __init__(self, data: bytes):
        # Keep the buffer alive: the FlatBuffers accessors index into it.
        self._buf = data
        self._root = SsAnimeBinary.GetRootAs(data, 0)

    @property
    def data(self) -> bytes:
        """The backing ``.ssab`` bytes (e.g. to re-bind an internal instance ref)."""
        return self._buf

    @property
    def name(self) -> str:
        return _s(self._root.Name())

    @property
    def name_hash(self) -> int:
        return self._root.NameHash()

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

    def parts(self) -> list[PartInfo]:
        """Enumerate every part with its type and (for Instance/Effect) refs.

        Resolves the ``PartData.part_type`` FlatBuffers *union*: the
        discriminator (``PartTypeType()``) selects the value table, which for
        Instance/Effect we read for the playback references the C-API needs.
        Index equals the runtime part index (== draw-plan slot index).
        """
        out: list[PartInfo] = []
        for i in range(self._root.PartsLength()):
            pd = self._root.Parts(i)
            ptype = pd.PartTypeType()
            ref_pack = ref_name = ""
            ref_pack_hash = ref_name_hash = ref_effect_hash = 0
            if ptype == PART_TYPE_INSTANCE:
                tbl = pd.PartType()
                if tbl is not None:
                    inst = PartTypeInstance()
                    inst.Init(tbl.Bytes, tbl.Pos)
                    ref_pack = _s(inst.RefAnimePack())
                    ref_pack_hash = inst.RefAnimePackHash()
                    ref_name = _s(inst.RefAnimeName())
                    ref_name_hash = inst.RefAnimeNameHash()
            elif ptype == PART_TYPE_EFFECT:
                tbl = pd.PartType()
                if tbl is not None:
                    eff = PartTypeEffect()
                    eff.Init(tbl.Bytes, tbl.Pos)
                    ref_effect_hash = eff.RefEffectNameHash()
            out.append(PartInfo(
                index=i, name=_s(pd.Name()), parent_index=pd.ParentIndex(),
                part_type=ptype, ref_anime_pack=ref_pack,
                ref_anime_pack_hash=ref_pack_hash, ref_anime_name=ref_name,
                ref_anime_name_hash=ref_name_hash,
                ref_effect_name_hash=ref_effect_hash))
        return out

    def part_names(self) -> list[str]:
        return [p.name for p in self.parts()]

    def instance_parts(self) -> list[PartInfo]:
        return [p for p in self.parts() if p.is_instance]

    def effect_parts(self) -> list[PartInfo]:
        return [p for p in self.parts() if p.is_effect]

    def external_instances(self) -> list[ExternalInstanceInfo]:
        """External ``.ssab`` packs referenced by Instance parts (docs/08 §1)."""
        out: list[ExternalInstanceInfo] = []
        for i in range(self._root.ExternalInstancesLength()):
            e = self._root.ExternalInstances(i)
            out.append(ExternalInstanceInfo(
                anime_pack_name=_s(e.AnimePackName()),
                anime_pack_name_hash=e.AnimePackNameHash(),
                anime_name=_s(e.AnimeName()),
                anime_name_hash=e.AnimeNameHash()))
        return out

    def effects(self) -> list[EffectInfo]:
        """The effect definitions embedded in this pack (keyed by name hash)."""
        out: list[EffectInfo] = []
        for i in range(self._root.EffectsLength()):
            e = self._root.Effects(i)
            out.append(EffectInfo(
                name=_s(e.Name()), name_hash=e.NameHash(), fps=e.Fps()))
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
