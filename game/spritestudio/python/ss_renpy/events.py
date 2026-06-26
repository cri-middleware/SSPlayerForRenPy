"""Decode the timeline events (UserData / Signal / Audio) the runtime reports.

This is the data half of "Step 4 — interactive features" in the porting guide
(``docs/06_playback_control`` §3). The Brain does not hand back event payloads
over the C-API; it only reports, after each ``update``, the *indices* of the
``EventsPerFrame`` records that the playhead passed through. We resolve those
indices straight from the ``.ssab`` FlatBuffer.

Index semantics (verified empirically against the overall packs):
  ``ss_runtime_get_passed_event_index(ctx, i)`` returns an index into the
  **currently-setup animation's** ``AnimationData.events`` vector (a vector of
  ``EventsPerFrame``). The resolved ``EventsPerFrame.frame_index`` equals the
  integer frame the event lives on (e.g. UserData.ssab → {0, 10}, Sound.ssab →
  {0, 10, 20}). So resolution is just ``AnimationData.Events(idx)``.

Engine-independent on purpose (no ``renpy`` import) so the headless tools and
the Ren'Py displayable share one decoder — mirrors ``framedata`` / ``ssab_meta``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ss.format.SsAnimeBinary import SsAnimeBinary
from ss.format.SignalCommandParamValue import SignalCommandParamValue


def _s(maybe_bytes) -> str:
    if maybe_bytes is None:
        return ""
    if isinstance(maybe_bytes, bytes):
        return maybe_bytes.decode("utf-8", "replace")
    return str(maybe_bytes)


# --- event payloads -------------------------------------------------------

@dataclass(frozen=True)
class UserDataEvent:
    """A SpriteStudio UserData marker (``PartAttributeUserData``).

    Each optional slot is ``None`` when the marker does not carry that field.
    ``rect`` is ``(x1, y1, x2, y2)``; ``point`` is ``(x, y)``.
    """
    part_index: int
    integer: int | None = None
    rect: tuple[float, float, float, float] | None = None
    point: tuple[float, float] | None = None
    string: str | None = None


@dataclass(frozen=True)
class SignalEvent:
    """A v7 Signal marker (``PartAttributeSignal``).

    ``params`` maps ``param_id`` → decoded value (``bool`` / ``int`` / ``float``
    / ``str``); a ``None``-typed param maps to ``None``.
    """
    part_index: int
    active: bool
    command_id: str
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AudioEvent:
    """A sound-trigger marker (``PartAttributeAudio``).

    The runtime only *reports* the trigger; actually playing the sound is the
    Player's job (``docs/00_limitations`` → "サウンド再生"). ``sound_name`` is the
    alias; the two hashes address ``SoundList`` / ``SoundFile`` for resolution.
    """
    part_index: int
    sound_name: str
    sound_name_hash: int
    sound_list_name_hash: int
    loop_num: int


@dataclass(frozen=True)
class FrameEvents:
    """All events on one ``EventsPerFrame`` record (one timeline frame)."""
    frame_index: int
    users: list[UserDataEvent] = field(default_factory=list)
    signals: list[SignalEvent] = field(default_factory=list)
    audios: list[AudioEvent] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.users or self.signals or self.audios)


# --- payload decoders -----------------------------------------------------

def _param_value(param):
    """Decode a ``SignalCommandParam`` union value to a native Python value."""
    vt = param.ValueType()
    tbl = param.Value()                       # generic flatbuffers Table or None
    if tbl is None:
        return None
    if vt == SignalCommandParamValue.Bool:
        from ss.format.BoolValueEntry import BoolValueEntry
        e = BoolValueEntry(); e.Init(tbl.Bytes, tbl.Pos)
        return bool(e.Value())
    if vt in (SignalCommandParamValue.Index, SignalCommandParamValue.Integer):
        from ss.format.IntValueEntry import IntValueEntry
        e = IntValueEntry(); e.Init(tbl.Bytes, tbl.Pos)
        return int(e.Value())
    if vt == SignalCommandParamValue.Floating:
        from ss.format.FloatValueEntry import FloatValueEntry
        e = FloatValueEntry(); e.Init(tbl.Bytes, tbl.Pos)
        return float(e.Value())
    if vt == SignalCommandParamValue.Text:
        from ss.format.StringValueEntry import StringValueEntry
        e = StringValueEntry(); e.Init(tbl.Bytes, tbl.Pos)
        return _s(e.Value())
    return None                               # NONE / None_


def _user_event(eu) -> UserDataEvent:
    v = eu.Value()
    integer = rect = point = string = None
    if v is not None:
        iv = v.Integer()
        if iv is not None:
            integer = int(iv.Value())
        rc = v.Rect()
        if rc is not None:
            rect = (rc.X1(), rc.Y1(), rc.X2(), rc.Y2())
        pt = v.Point()
        if pt is not None:
            point = (pt.V1(), pt.V2())
        st = v.Str()
        if st is not None:
            string = _s(st)
    return UserDataEvent(part_index=eu.PartIndex(), integer=integer,
                         rect=rect, point=point, string=string)


def _signal_event(es) -> SignalEvent:
    v = es.Value()
    active = False
    command_id = ""
    params: dict = {}
    if v is not None:
        active = bool(v.Active())
        command_id = _s(v.CommandId())
        for k in range(v.ParamsLength()):
            p = v.Params(k)
            if p is None:
                continue
            params[_s(p.ParamId())] = _param_value(p)
    return SignalEvent(part_index=es.PartIndex(), active=active,
                       command_id=command_id, params=params)


def _audio_event(ea) -> AudioEvent:
    v = ea.Value()
    name = ""
    name_hash = list_hash = loop = 0
    if v is not None:
        name = _s(v.SoundName())
        name_hash = v.SoundNameHash()
        list_hash = v.SoundListNameHash()
        loop = v.LoopNum()
    return AudioEvent(part_index=ea.PartIndex(), sound_name=name,
                      sound_name_hash=name_hash, sound_list_name_hash=list_hash,
                      loop_num=loop)


def parse_events_per_frame(epf) -> FrameEvents:
    """Turn one ``EventsPerFrame`` FlatBuffer record into a :class:`FrameEvents`."""
    users = [_user_event(epf.Users(i)) for i in range(epf.UsersLength())]
    signals = [_signal_event(epf.Signals(i)) for i in range(epf.SignalsLength())]
    audios = [_audio_event(epf.Audios(i)) for i in range(epf.AudiosLength())]
    return FrameEvents(frame_index=epf.FrameIndex(), users=users,
                       signals=signals, audios=audios)


# --- resolver -------------------------------------------------------------

class EventResolver:
    """Resolve passed-event indices for one setup animation into payloads.

    Construct once per animation (the index space is per-animation). Keeps the
    ``.ssab`` bytes alive — the FlatBuffers accessors index into them.
    """

    def __init__(self, ssab_bytes: bytes, animation_name: str):
        self._buf = ssab_bytes
        self.animation_name = animation_name
        root = SsAnimeBinary.GetRootAs(ssab_bytes, 0)
        self._anim = None
        for i in range(root.AnimationsLength()):
            a = root.Animations(i)
            if _s(a.Name()) == animation_name:
                self._anim = a
                break

    @property
    def available(self) -> bool:
        """True when the named animation was found (else resolution is a no-op)."""
        return self._anim is not None

    @property
    def events_length(self) -> int:
        return self._anim.EventsLength() if self._anim is not None else 0

    def resolve(self, event_idx: int) -> FrameEvents | None:
        """Resolve one ``passed_event_index`` into its :class:`FrameEvents`."""
        if self._anim is None:
            return None
        if event_idx < 0 or event_idx >= self._anim.EventsLength():
            return None
        return parse_events_per_frame(self._anim.Events(event_idx))

    def collect(self, rt) -> list[FrameEvents]:
        """Drain the events the last ``update`` passed through, in order.

        ``rt`` is anything exposing ``passed_event_count()`` /
        ``passed_event_index(i)`` (the :class:`ss_renpy.ssruntime.SSRuntime`
        wrapper). Empty records are dropped.
        """
        out: list[FrameEvents] = []
        for i in range(rt.passed_event_count()):
            fe = self.resolve(rt.passed_event_index(i))
            if fe is not None and not fe.is_empty:
                out.append(fe)
        return out
