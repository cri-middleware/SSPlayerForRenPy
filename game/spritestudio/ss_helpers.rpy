# SSPlayer runtime helpers — small, escapable sugar over SSPlayer for the most
# common "play something" patterns, so creators don't hand-roll timing logic.
#
#   $ ss_play_once("ss_assets/ParticleEffect/e038.ssab", "hit",
#                  at=Transform(xpos=400, ypos=300), wait=True)     # cutscene beat
#   $ d = ss_duration("ss_assets/Ringo/Ringo.ssab", "attack1")      # one playthrough (s)
#
# These are thin compositions of documented Ren'Py APIs (show/hide/pause/sound)
# over SSPlayer — nothing here is impossible without them. Runs at init -9
# (after spritestudio.rpy at -10). Drop this file to remove the helpers.

init -9 python:

    def ss_duration(ssab, anim=None, speed=1.0):
        """Seconds one playthrough of `anim` takes (total_frames / fps / speed).

        `ssab` is the gamedir-relative .ssab path; `anim` defaults to the first
        animation. Returns 0.0 if it can't be determined (so callers degrade to
        "no wait")."""
        try:
            meta = SsabMeta(_ss_open_bytes(ssab))
            anims = meta.animations()
            if not anims:
                return 0.0
            a = next((x for x in anims if x.name == anim), anims[0])
            if not a.fps:
                return 0.0
            return (a.total_frame / float(a.fps)) / float(speed or 1.0)
        except Exception:
            return 0.0

    def ss_play_once(ssab, anim=None, at=None, tag=None, layer="master",
                     wait=False, hide=True, speed=1.0, loop=1, **kwargs):
        """Show a SpriteStudio animation played a fixed number of times: an
        effect, a full-screen cutscene, any one-shot pack.

        `at`    : a Transform/ATL for placement/scale (e.g. Transform(xalign=.5,
                  yalign=.5, zoom=1.5) to center + scale up a full-screen cutscene).
        `tag`   : the show tag (default derived from the .ssab stem).
        `wait`  : block for the animation's run (a cutscene beat), then hide.
        `hide`  : when waiting, hide afterwards (set False to leave the last frame).
        `loop`  : play count (>= 1; default 1 = once). A few passes sometimes read
                  better than one; a value below 1 is clamped to 1. This helper
                  plays a *finite* run — for an endless loop show SSPlayer(loop=-1)
                  directly instead.
        `**kwargs` go to SSPlayer (size, on_audio, ...).

        Non-blocking by default: it shows the animation (it freezes on its last
        frame once the run ends); hide it yourself with :func:`ss_hide_once`, or
        pass wait=True for a beat.
        """
        if tag is None:
            stem = ssab.replace("\\", "/").rsplit("/", 1)[-1]
            tag = "ss_once_" + (stem[:-len(".ssab")] if stem.endswith(".ssab") else stem).lower()
        loop = max(1, int(loop))   # finite run only: clamp an infinite/<1 loop to once
        d = SSPlayer(ssab, animation=anim, loop=loop, speed=speed, **kwargs)
        renpy.show(tag, what=d, at_list=([at] if at is not None else []), layer=layer)
        if wait:
            renpy.pause(ss_duration(ssab, anim, speed) * loop)
            if hide:
                renpy.hide(tag, layer=layer)
        return tag

    def ss_hide_once(tag, layer="master"):
        """Hide an animation previously shown by :func:`ss_play_once`.

        The teardown paired with a non-waiting :func:`ss_play_once`
        (``wait=False``): call it to take the one-shot animation back down."""
        renpy.hide(tag, layer=layer)

    def ss_auto_audio(player, frame, audio):
        """`on_audio` handler that plays an SS Audio event by its resolved file.

        Only needed when the built-in playback is OFF (`SS_ENABLE_AUDIO = False`):
        by default SSPlayer already resolves + plays Audio events itself (forward-
        only, honouring loop_num, with setup-time preload), so wiring this too
        would play every sound twice. When you do use it, prefer the resolved
        `audio.file_path` (ssab-relative → joined with the pack dir) and fall back
        to the bare `audio.sound_name`; best-effort, swallows errors."""
        try:
            base = getattr(player, "_base_dir", "")
            ref = getattr(audio, "file_path", "") or getattr(audio, "sound_name", "")
            if not ref:
                return
            path = (base + "/" + ref) if (base and getattr(audio, "file_path", "")) else ref
            renpy.sound.play(path)
        except Exception:
            pass
