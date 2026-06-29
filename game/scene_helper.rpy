# Helper-showcase scene: the convenience layer — SSCharacter (talking), size +
# attachments, and the ss_show_effect / ss_duration helpers, all in one scene.
# (Reached from the start menu in script.rpy.)

# SSCharacter registers an image under `tag` and returns a talking Character.
# We use tag="ringo_talk" so it does NOT clobber the `image ringo` in
# scene_ringo.rpy. (Ringo has no "talk" animation, so we use "joy" as a visible
# stand-in.)
define ringo_chr = SSCharacter(
    "ss_assets/Ringo/Ringo.ssab",
    talk="joy", idle="wait1", who="Ringo", tag="ringo_talk",
)

# `attachments` pins the ♪ to the "head" part so it follows the animation
# (v1 = translation only).
image ringo_point = SSPlayer(
    "ss_assets/Ringo/Ringo.ssab",
    animation="wait1",
    attachments={"head": Text("♪", size=64, color="#ffcc00")},
)

label ringo_helper_demo:
    scene bg room
    window show

    # 1. Living character: SSCharacter plays `talk` while speaking and `idle`
    #    when done. (Ringo has no "talk" anim, so "joy" is a visible stand-in.)
    #    Full-screen + yoffset like ringo_demo so the whole sprite is on screen.
    show ringo_talk:
        yoffset 200
    with dissolve
    ringo_chr "With SSCharacter, my motion switches just while I'm talking, su!" id helper_msg1
    ringo_chr "Right now I'm using 'joy' in place of a talk motion, so I get happy when I speak, su!" id helper_msg2

    # 2. Attachments: the ♪ is pinned to Ringo's "head" part and follows it.
    hide ringo_talk
    show ringo_point:
        yoffset 200
    with dissolve
    "The ♪ is pinned to my 'head' part, so it follows along." id helper_msg3

    # 3. One-shot effect via the helper (blocks for one playthrough = a beat).
    $ ss_show_effect("ss_assets/ParticleEffect/e040b.ssab",
                     at=Transform(xalign=0.5, yalign=0.4), wait=True)
    "ss_show_effect(wait=True) holds the beat until the effect finishes playing." id helper_msg4
    hide ringo_point
    with dissolve

    # 4. ss_duration times a beat to a motion WITHOUT removing the sprite
    #    (contrast beat 3's ss_show_effect, which hides the effect when done).
    #    Clear the lip-flap idle/talk attributes so only `dance` selects the anim.
    show ringo_talk dance -idle -talk:
        yoffset 200
    with dissolve
    # Wait exactly one playthrough, then settle back to idle. The image loops
    # (loop=-1), so switching right after the beat keeps it to a single dance.
    $ renpy.pause(ss_duration("ss_assets/Ringo/Ringo.ssab", "dance"))
    show ringo_talk idle:
        yoffset 200
    "That 'dance' beat was timed with ss_duration — and unlike a one-shot effect, she stays on screen." id helper_msg5

    ringo_chr "That's all for the new-feature showcase. Thanks for watching, su!" id helper_msg6

    return
