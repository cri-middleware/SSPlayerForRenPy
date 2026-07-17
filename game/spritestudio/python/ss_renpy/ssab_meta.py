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
PART_TYPE_MASK = PartType.PartTypeMask          # 12


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
class SoundFileInfo:
    """One entry of a pack ``SoundList`` (SDK doc: 40_components/90_audio.md).

    ``file_path`` is the audio file **as stored** in the ``.ssab`` — an
    ssab-relative reference (no normalisation), which the host
    joins with the pack base dir just like a cellmap ``image_path``.
    ``time_total`` is the clip length in milliseconds. ``list_name_hash`` +
    ``name_hash`` are exactly the pair an :class:`~ss_renpy.events.AudioEvent`
    carries (``sound_list_name_hash`` / ``sound_name_hash``), so they resolve
    an event straight to its file."""
    list_name: str
    list_name_hash: int
    name: str
    name_hash: int
    file_path: str
    file_path_hash: int
    time_total: int


@dataclass(frozen=True)
class PartInfo:
    """Static per-part data (index == ``PartState.part_index`` == slot_index).

    ``part_type`` is the :class:`PartType` union discriminator. For Instance
    parts the ``ref_anime_*`` fields name the referenced pack/animation; for
    Effect parts ``ref_effect_name_hash`` keys the embedded effect. All ref
    fields are empty/0 for other part types.

    The four ``*_mask`` flags are the **static** mask attributes (SDK doc:
    40_components/40_mask.md): they never change per frame, so a Player reads
    them once. Their meaning is role-dependent — see the ``is_*`` helpers below
    for the canonical classification (pure mask / writer / clipping / target
    polarity).
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
    visible_inside_mask: bool = False
    mask_write: bool = False
    mask_influence: bool = False
    draw_as_mask: bool = False

    @property
    def is_instance(self) -> bool:
        return self.part_type == PART_TYPE_INSTANCE

    @property
    def is_effect(self) -> bool:
        return self.part_type == PART_TYPE_EFFECT

    @property
    def is_mask_part(self) -> bool:
        """A dedicated ``PartTypeMask`` part (always a pure mask writer)."""
        return self.part_type == PART_TYPE_MASK

    @property
    def is_pure_mask(self) -> bool:
        """Writes the stencil but draws no colour.

        ``pure_mask = PartTypeMask || draw_as_mask``. (Only Shape/Text/Nines can
        be turned pure via ``draw_as_mask``; the flag is ignored on other kinds
        by the editor, so this is safe to evaluate uniformly.)
        """
        return self.is_mask_part or self.draw_as_mask

    @property
    def is_mask_writer(self) -> bool:
        """Contributes to the stencil/coverage at all.

        ``is_writer = pure_mask || mask_write``.
        """
        return self.is_pure_mask or self.mask_write

    @property
    def is_clipping(self) -> bool:
        """A drawing part that also writes the stencil.

        ``is_clipping = mask_write && !pure_mask`` — draws its own colour *and*
        clips parts drawn after it (higher draw priority).
        """
        return self.mask_write and not self.is_pure_mask


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
        # Positively identify this as a .ssab via the FlatBuffers file_identifier
        # ("SSAB", bytes 4-8) using the flatbuffers API — GetRootAs does NOT check
        # it. Safe on short/empty buffers (it just compares data[4:8]). Without
        # this a wrong-type / crafted buffer would reach the non-validating Rust
        # runtime and drive an OOB read (SDK_UPSTREAM_ISSUES #1).
        if not SsAnimeBinary.SsAnimeBinaryBufferHasIdentifier(data, 0):
            raise ValueError(
                "not a .ssab pack (missing 'SSAB' FlatBuffers file identifier)")
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
                ref_effect_name_hash=ref_effect_hash,
                visible_inside_mask=bool(pd.VisibleInsideMask()),
                mask_write=bool(pd.MaskWrite()),
                mask_influence=bool(pd.MaskInfluence()),
                draw_as_mask=bool(pd.DrawAsMask())))
        return out

    def part_names(self) -> list[str]:
        return [p.name for p in self.parts()]

    def instance_parts(self) -> list[PartInfo]:
        return [p for p in self.parts() if p.is_instance]

    def effect_parts(self) -> list[PartInfo]:
        return [p for p in self.parts() if p.is_effect]

    def external_instances(self) -> list[ExternalInstanceInfo]:
        """External ``.ssab`` packs referenced by Instance parts."""
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
        emits, lookups resolve.
        """
        m: dict[int, str] = {}
        for c in self.cellmaps():
            if c.image_path:
                m[c.name_hash] = c.image_path
                m[c.image_path_hash] = c.image_path
        return m

    # -- audio (SDK doc: 40_components/90_audio.md) ---------------------
    def sound_files(self) -> list[SoundFileInfo]:
        """Every ``SoundFile`` across the pack's ``SoundList``s, in file order.

        The runtime plays no audio (SDK doc: 10_introduction/20_limitations.md)
        — it only *reports* Audio triggers; the Player resolves and plays them.
        This surfaces the pack's sound
        table so the host can (a) preload the files at setup and (b) resolve an
        :class:`~ss_renpy.events.AudioEvent` to a concrete file."""
        out: list[SoundFileInfo] = []
        for i in range(self._root.SoundListsLength()):
            sl = self._root.SoundLists(i)
            if sl is None:
                continue
            ln, lh = _s(sl.Name()), sl.NameHash()
            for j in range(sl.TableDataLength()):
                sf = sl.TableData(j)
                if sf is None:
                    continue
                out.append(SoundFileInfo(
                    list_name=ln, list_name_hash=lh,
                    name=_s(sf.Name()), name_hash=sf.NameHash(),
                    file_path=_s(sf.FilePath()), file_path_hash=sf.FilePathHash(),
                    time_total=sf.TimeTotal()))
        return out

    def has_audio(self) -> bool:
        """True if the pack defines any playable sound file (the 'lazy
        initialization' gate — the host spins up audio only when this is true)."""
        return any(sf.file_path for sf in self.sound_files())

    def sound_file_map(self) -> dict:
        """Map an Audio event's identifying hashes → its ssab-relative file path.

        Keyed by BOTH ``(sound_list_name_hash, sound_name_hash)`` and (as a
        fallback) the bare ``sound_name_hash`` — the belt-and-suspenders keying
        :meth:`texture_hash_map` uses, so an :class:`~ss_renpy.events.AudioEvent`
        resolves whichever pair it carries even if two lists reuse a name."""
        m: dict = {}
        for sf in self.sound_files():
            if not sf.file_path:
                continue
            m[(sf.list_name_hash, sf.name_hash)] = sf.file_path
            m.setdefault(sf.name_hash, sf.file_path)
        return m


def load(path: str) -> SsabMeta:
    with open(path, "rb") as fh:
        return SsabMeta(fh.read())
