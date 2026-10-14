"""The playback decisions ``SSPlayer`` makes as a Ren'Py host, without Ren'Py.

``SSPlayer`` (``spritestudio.rpy``) owns the policy around its
``SSInternalPlayer``: when a render means the player was shown afresh, how the
constructor's animation (or sequence) is started, and how a core Ren'Py dropped
on pickling is put back the way it was. That policy lives here, in plain
Python, so the headless suite can drive it with a real core; the displayable
keeps the state (it pickles with it) and calls these.

Everything here drives the core through its public API only. The core stays
free of policy: it reports, and this decides.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

# What `playback_state` reports, and `restore` takes back.
PLAYING = "playing"
PAUSED = "paused"
STOPPED = "stopped"


class ShowClock:
    """The animation clock of one player, which may be drawn from several places.

    Ren'Py hands every render the ``st`` of the place it is drawn from -- each
    particle of a SnowBlossom, each tag a player is shown under -- and each
    place's ``st`` counts from when that place appeared. A player has one
    timeline, so only the first render of a frame advances it, by however far
    the place that render came from has moved on since the last frame.

    That place is found among the last frame's renders: its ``st`` there is the
    largest one not past this one. A render that matches none of them is a
    re-show (the player was shown afresh), and :attr:`reshown` says so.
    Comparing against one place alone -- the one drawn first last frame --
    would read that place going away as a re-show: when the oldest particle of
    a SnowBlossom dies, or the first of two tags is hidden, every place left is
    younger than it was, and the animation would restart.

    Holds no Ren'Py state; it starts empty after a load, which the first render
    reads as the first frame ever drawn.
    """

    __slots__ = ("reshown", "_frame", "_prev", "_cur")

    def __init__(self) -> None:
        self.reshown = False
        self._frame = None
        self._prev: List[float] = []   # st of every render in the last frame drawn
        self._cur: List[float] = []    # ... and in this one

    def advance(self, frame, st: float) -> Optional[float]:
        """Record one render of frame number ``frame``, drawn at ``st`` seconds.

        Returns the seconds to advance the animation by on the first render of
        a frame -- ``0.0`` on the very first one, and on a re-show -- and
        ``None`` on any later render of the same frame, which draws the frame
        the first one advanced to. Sets :attr:`reshown`.
        """
        self.reshown = False
        if frame == self._frame:
            self._cur.append(st)
            return None
        self._frame = frame
        # The frame that just ended becomes the one to match against, and the
        # one before it is emptied for reuse: two lists, no allocation per frame.
        last = self._cur
        self._cur = self._prev
        self._prev = last
        del self._cur[:]
        self._cur.append(st)
        if not last:
            return 0.0
        since = None
        for s in last:
            if s <= st and (since is None or s > since):
                since = s
        if since is None:
            self.reshown = True
            return 0.0
        return st - since


def playback_state(core) -> str:
    """``PLAYING`` / ``PAUSED`` / ``STOPPED``, as `restore` should bring it back.

    Ren'Py pickles the displayable without the native core and rebuilds it
    lazily, so whether playback was live has to be carried as plain data
    alongside the frame -- otherwise every restore resumes. A naturally
    finished one-shot reads as ``STOPPED``: the Brain parks it on its last frame
    with ``is_playing`` false, and restoring it as playing would fire the
    completion edge a second time. Never raises -- a state it cannot read
    reports ``PLAYING``, which is what a restore did before states existed.
    """
    try:
        if core.is_pausing():
            return PAUSED
        if core.is_finished() or not core.is_playing():
            return STOPPED
    except Exception:
        pass
    return PLAYING


def apply_kept(core, frame_skip: bool = True,
               frame_rate: Optional[int] = None) -> None:
    """Give a freshly built ``core`` the settings the Brain keeps across
    animation changes, which a rebuilt core therefore starts without: frame
    skipping (``frame_skip``) and the frame-rate override (``frame_rate``,
    ``None`` for none set). Both survive setup, so they can go on before the
    animation is set up."""
    if not frame_skip:
        core.set_frame_skip_enabled(False)
    if frame_rate is not None:
        core.set_frame_rate(frame_rate)


def start_initial(core, animation, loop: int, speed: float,
                  start_frame: float = -1.0, still: bool = False,
                  pack: str = "") -> List[str]:
    """Set up and play the constructor's ``animation`` on ``core``.

    ``animation`` is a name, ``None`` (the pack's first), or a list: a sequence
    plays its first clip now and returns the rest, for the host to chain on
    each ``FramePlan.finished`` -- the core has no notion of a queue. A clip
    that is not the last plays once; the last plays ``loop`` times.
    ``still`` holds the first frame by pausing, which also stops the redraws
    (a speed of 0 would draw the same frame every frame).

    Raises when the pack lacks the animation, naming ``pack`` and the name.
    """
    core.set_speed_scale(speed)
    if isinstance(animation, (list, tuple)) and animation:
        queue = list(animation)
        first = queue.pop(0)
        core.set_loop_count(1 if queue else loop)
        ok = core.set_animation(first)
    else:
        queue = []
        core.set_loop_count(loop)
        ok = core.set_animation(animation)   # None -> the first available
    if not ok:
        raise Exception(
            "ss: animation %r not found in %s (have: %s)"
            % (animation, pack, ", ".join(core.animation_names()) or "(none)"))
    if start_frame is not None and start_frame >= 0:
        core.play(start_frame=start_frame)
    else:
        core.play()
    if still:
        core.pause()
    return queue


def restore(core, animation: Optional[str], speed: float, loop: int,
            frame: float, state: str = PLAYING,
            section: Optional[Sequence[int]] = None) -> bool:
    """Put a freshly built ``core`` back on ``animation`` at ``frame``.

    ``loop`` is the count the core last ran with, which already encodes the
    sequence rule (1 for a clip mid-chain). ``section`` is the playback section
    the game set on this animation, if any: the Brain resets it on every setup,
    so a rebuilt core has to be given it again, and before the seek, since
    setting a section moves the head. ``state`` is what `playback_state` read:

      * ``STOPPED`` (a stopped player, or a one-shot that had finished) seeks
        without ``play()``, which would resume it and, for the one-shot, re-arm
        the completion edge so ``on_animation_finished`` -- and the sequence
        advance -- fired again for the same run. The setup left the head
        parked, so the seek alone poses the frame.
      * otherwise it plays and then seeks, in that order: ``play()`` rewinds to
        the section start, so seeking first would put the head back at the
        start. ``PAUSED`` then holds that frame.

    Returns False, having changed nothing that matters, when the pack no longer
    has ``animation`` (it was re-exported since the save); the caller then
    starts afresh rather than leave the core with nothing set up.
    """
    core.set_speed_scale(speed)
    core.set_loop_count(loop)
    if not core.set_animation(animation):
        return False
    if section is not None:
        core.set_animation_section(section[0], section[1])
    if state == STOPPED:
        core.set_frame_no(frame)
    else:
        core.play()
        core.set_frame_no(frame)
        if state == PAUSED:
            core.pause()
    return True
