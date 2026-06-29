# SSPlayer runtime helpers — small, escapable sugar over SSPlayer for the most
# common "play something" patterns, so creators don't hand-roll timing logic.
#
#   $ ss_show_effect("ss_assets/ParticleEffect/e038.ssab", "hit",
#                    at=Transform(xpos=400, ypos=300), wait=True)   # cutscene beat
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

    def ss_show_effect(ssab, anim=None, at=None, tag=None, layer="master",
                       wait=False, hide=True, speed=1.0, **kwargs):
        """Show a one-shot SpriteStudio effect/animation (plays once).

        `at`    : a Transform/ATL for placement (e.g. Transform(xpos=.., ypos=..)).
        `tag`   : the show tag (default derived from the .ssab stem).
        `wait`  : block for one playthrough (a cutscene beat), then hide.
        `hide`  : when waiting, hide afterwards (set False to leave the last frame).
        `**kwargs` go to SSPlayer (size, on_audio, ...).

        Non-blocking by default: it shows the effect (it freezes on its last
        frame with loop=1); hide it yourself, or pass wait=True for a beat.
        """
        if tag is None:
            stem = ssab.replace("\\", "/").rsplit("/", 1)[-1]
            tag = "ss_fx_" + (stem[:-len(".ssab")] if stem.endswith(".ssab") else stem).lower()
        d = SSPlayer(ssab, animation=anim, loop=1, speed=speed, **kwargs)
        renpy.show(tag, what=d, at_list=([at] if at is not None else []), layer=layer)
        if wait:
            renpy.pause(ss_duration(ssab, anim, speed))
            if hide:
                renpy.hide(tag, layer=layer)
        return tag

    def ss_hide_effect(tag, layer="master"):
        """Hide an effect previously shown by :func:`ss_show_effect`."""
        renpy.hide(tag, layer=layer)

    def ss_auto_audio(player, frame, audio):
        """Default `on_audio` handler: play an SS audio-track event via renpy.sound.

        Pass to SSPlayer as `on_audio=ss_auto_audio`. Best-effort: `audio.sound_name`
        must resolve to a playable file in your project; otherwise wire your own
        handler that maps SS sound names to your audio files / channels.
        """
        try:
            name = getattr(audio, "sound_name", None)
            if name:
                renpy.sound.play(name)
        except Exception:
            pass
