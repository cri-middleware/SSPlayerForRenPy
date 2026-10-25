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
PART_TYPE_MESH = PartType.PartTypeMesh          # 9
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
class LabelInfo:
    name: str
    frame: int


@dataclass(frozen=True)
class LabelTable:
    """The labels of one animation and the frame range it was authored with.

    ``labels`` are in frame order; the pack keeps them sorted by name hash, so
    "the next label" is only meaningful after this sort. ``start_frame`` /
    ``end_frame`` are the animation's own, never a playback section's."""
    labels: tuple
    start_frame: int
    end_frame: int

    def frame_of(self, label: str) -> int | None:
        """The frame ``label`` marks, or ``None`` when there is no such label.

        ``"_start"`` and ``"_end"`` are the animation's first and last frame,
        as in SpriteStudio, where they are never in the table; a real label of
        the same name wins."""
        for l in self.labels:
            if l.name == label:
                return l.frame
        if label == "_start":
            return self.start_frame
        if label == "_end":
            return self.end_frame
        return None


@dataclass(frozen=True)
class CellMapInfo:
    name: str
    name_hash: int
    image_path: str
    image_path_hash: int


@dataclass(frozen=True)
class ExternalTextureInfo:
    """A texture referenced by a *texture change* (``TCHG``) attribute.

    ``name`` is the texture's file name, resolved against the pack dir exactly
    like a cellmap ``image_path``; ``name_hash`` is the hash of that FILE name —
    a different namespace from a cellmap's *name* hash, and the key such a part's
    ``DrawBatch.texture_hash`` carries."""
    name: str
    name_hash: int


@dataclass(frozen=True)
class SoundFileInfo:
    """One entry of a pack ``SoundList``.

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

    The four ``*_mask`` flags are the **static** mask attributes:
    they never change per frame, so a Player reads
    them once. Their meaning is role-dependent — see the ``is_*`` helpers below
    for the canonical classification (pure mask / writer / clipping / target
    polarity).

    ``skinned_mesh`` is the other static flag a Player reads once: a mesh part
    whose vertices are drawn by bone skinning (``PartMeshBinding`` present with a
    non-empty ``influence_bone``). Its own transform stays at the setup node
    (usually near the character root), so it is a poor *part-tracking* target —
    see :meth:`is_part_skinned_mesh`.
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
    skinned_mesh: bool = False

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

    def canvas_rect(self, name: str | None = None) -> tuple[float, float, float, float] | None:
        """The authored canvas of animation ``name`` (the first one when
        ``None``), as ``(x, y, width, height)`` in player-local space: the
        animation's origin at ``(0, 0)`` and ``y`` downward, the space
        ``part_transform`` reports in. ``None`` for an unknown name or a
        zero-sized canvas.

        The pivot is where the origin sits inside the canvas, in editor space —
        normalised from the canvas centre, ``y`` upward — so ``pivot (0, -0.5)``,
        a character standing on the canvas's bottom edge, gives a box that lies
        entirely above the origin. The runtime's metadata carries no pivot,
        which is why this reads the pack.
        """
        for i in range(self._root.AnimationsLength()):
            a = self._root.Animations(i)
            if name is not None and _s(a.Name()) != name:
                continue
            size, pivot = a.CanvasSize(), a.Pivot()
            if size is None or pivot is None:
                return None
            w, h = size.V1(), size.V2()
            if w <= 0.0 or h <= 0.0:
                return None
            return (-pivot.V1() * w - w / 2.0, pivot.V2() * h - h / 2.0, w, h)
        return None

    def label_table(self, name: str | None = None) -> LabelTable | None:
        """The labels of animation ``name`` (the first one when ``None``) in
        frame order; ``None`` for an unknown name. The C-API exports no label
        lookup, so a section named by labels resolves against this."""
        for i in range(self._root.AnimationsLength()):
            a = self._root.Animations(i)
            if name is not None and _s(a.Name()) != name:
                continue
            labels = []
            for j in range(a.LabelsLength()):
                l = a.Labels(j)
                if l is not None and l.Name() is not None:
                    labels.append(LabelInfo(name=_s(l.Name()), frame=l.Time()))
            labels.sort(key=lambda l: l.frame)
            return LabelTable(labels=tuple(labels),
                              start_frame=a.StartFrame(), end_frame=a.EndFrame())
        return None

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

    def cell_names(self, cellmap_name: str) -> list[str]:
        """Names of the cells in ``cellmap_name`` (``[]`` when unknown).

        The cellmap is named without its ``.ssce`` extension, matching how the
        pack stores it. Together with :meth:`cellmaps` this enumerates the valid
        targets of a per-part *cell override* (mirrors SSPlayerForUnity's
        ``GetCellNames``).
        """
        for i in range(self._root.CellmapsLength()):
            c = self._root.Cellmaps(i)
            if _s(c.Name()) != cellmap_name:
                continue
            return [_s(c.Cells(j).Name()) for j in range(c.CellsLength())]
        return []

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
            # Skinned == a mesh binding with at least one influencing bone. A
            # rigid (deform-only) mesh has a binding with no bones and tracks
            # fine, so the bone count — not the binding's mere presence — is the
            # gate (SDK ssab.fbs: PartMeshBinding.influence_bone).
            mb = pd.MeshBinding()
            skinned = bool(mb is not None and mb.InfluenceBoneLength() > 0)
            out.append(PartInfo(
                index=i, name=_s(pd.Name()), parent_index=pd.ParentIndex(),
                part_type=ptype, ref_anime_pack=ref_pack,
                ref_anime_pack_hash=ref_pack_hash, ref_anime_name=ref_name,
                ref_anime_name_hash=ref_name_hash,
                ref_effect_name_hash=ref_effect_hash,
                visible_inside_mask=bool(pd.VisibleInsideMask()),
                mask_write=bool(pd.MaskWrite()),
                mask_influence=bool(pd.MaskInfluence()),
                draw_as_mask=bool(pd.DrawAsMask()),
                skinned_mesh=skinned))
        return out

    def part_names(self) -> list[str]:
        return [p.name for p in self.parts()]

    def is_part_skinned_mesh(self, name: str) -> bool:
        """Whether ``name`` is a bone-skinned mesh part (``False`` if unknown).

        A skinned mesh is drawn from its bound bones, so its own node transform
        stays put at the setup pose while the visible art deforms elsewhere —
        which makes it a poor *part-tracking* target (a follower snaps to the
        node, not the art). See the sibling Players' ``is_part_skinned_mesh``
        and the mirror of the existing ``is_part_hidden`` query. Deform-only
        (rigid) meshes and every non-mesh part return ``False``.
        """
        for p in self.parts():
            if p.name == name:
                return p.skinned_mesh
        return False

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

    def external_textures(self) -> list[ExternalTextureInfo]:
        """Textures targeted by a *texture change* (``TCHG``) attribute.

        A second texture table alongside :meth:`cellmaps`, listing files that no
        cellmap points at."""
        out: list[ExternalTextureInfo] = []
        for i in range(self._root.ExternalTexturesLength()):
            t = self._root.ExternalTextures(i)
            out.append(ExternalTextureInfo(
                name=_s(t.Name()), name_hash=t.NameHash()))
        return out

    def texture_hash_map(self) -> dict[int, str]:
        """Map every plausible ``DrawBatch.texture_hash`` key to its image path.

        ``DrawBatch.texture_hash`` is an FNV1a hash drawn from TWO namespaces:
        a cellmap's own hash for an ordinary part, and a texture FILE-name hash
        for a part whose drawing applies a texture change (``TCHG``). The former
        is carried as both the cellmap *name* hash and the *image-path* hash, so
        we register both; the latter lives in ``external_textures`` — miss it and
        those batches resolve to no texture and the part silently vanishes.

        One file legitimately appears under several keys (an atlas that is also a
        TCHG target); the host's ResourceManager dedupes by path.
        """
        m: dict[int, str] = {}
        for c in self.cellmaps():
            if c.image_path:
                m[c.name_hash] = c.image_path
                m[c.image_path_hash] = c.image_path
        for t in self.external_textures():
            if t.name:
                m[t.name_hash] = t.name
        return m

    def replaceable_texture_names(self) -> list[str]:
        """Names accepted by a runtime *texture replacement* (a Player-side
        override), cellmaps first then ``external_textures``.

        A cellmap is named WITHOUT its file extension (``common``); an external
        texture is a file NAME (``common.png``). They are different strings that
        hash into the two distinct spaces ``DrawBatch.texture_hash`` draws from,
        so both are listed —
        every entry is legitimately replaceable. Mirrors the sibling players'
        ``get_cellmap_names``; dedup guards only against a repeated name."""
        out: list[str] = []
        seen: set[str] = set()
        for c in self.cellmaps():
            if c.name and c.name not in seen:
                seen.add(c.name)
                out.append(c.name)
        for t in self.external_textures():
            if t.name and t.name not in seen:
                seen.add(t.name)
                out.append(t.name)
        return out

    def resolve_texture_image(self, name: str) -> str:
        """Pack-relative image path for a replaceable-texture ``name`` (``""``
        when unknown).

        A cellmap name resolves to its ``image_path``; an external-texture name
        IS its file path. Cellmaps are searched first, then ``external_textures``
        — the same order as :meth:`replaceable_texture_names` and the sibling
        players' name->hash resolution."""
        if not name:
            return ""
        for c in self.cellmaps():
            if c.name == name:
                return c.image_path
        for t in self.external_textures():
            if t.name == name:
                return t.name
        return ""

    # -- audio ----------------------------------------------------------
    def sound_files(self) -> list[SoundFileInfo]:
        """Every ``SoundFile`` across the pack's ``SoundList``s, in file order.

        The runtime plays no audio —
        it only *reports* Audio triggers; the Player resolves and plays them.
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
