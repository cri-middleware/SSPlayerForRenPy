# Ringo image-attribute demo — drives a SpriteStudio character through Ren'Py
# image attributes (`show ringo idle/walk/attack ...`) and a Character's `image=`
# argument, so motions/expressions change straight from `say` statements.
# (Reached from the start menu in script.rpy.)

image ringo = SSPlayer(
    "ss_assets/Ringo/Ringo.ssab",   # the .ssab path (gamedir-relative)
    aliases={
        "idle": "wait1",
        "happy": "joy",
        "walk": "walk",
        "attack": ["attack1", "wait1"]  # a list plays the animations in sequence
    }
)

image ringo_tyu = SSPlayer("ss_assets/Ringo/Ringo_tyu.ssab")

define r = Character(_("Ringo"), image="ringo")

image hit_effect = SSPlayer(
    "ss_assets/ParticleEffect/e038.ssab",
    animation="hit",
    loop=1 # an effect: play once, then stop
)

image effect_e040b = SSPlayer("ss_assets/ParticleEffect/e040b.ssab")

label ringo_demo:
    scene bg room
    window show  # keep the dialogue window up (handy for checking layers)

    show ringo idle at ss_stand

    "Ringo has appeared." id ringo_msg1

    r happy "I can change my motion just by changing my attributes, su!" id ringo_msg2

    r piyo "I can even play the dizzy motion (piyo) just by specifying its name, su." id ringo_msg3

    # The SSPlayer's box is the canvas Ringo was authored on, so it moves like
    # any image: ss_stand (script.rpy) is plain xpos / ypos.
    show ringo walk at ss_stand(240)
    with move
    r walk "Of course, I can use 'move' and other Transforms together with this, su." id ringo_msg4

    show ringo walk at ss_stand
    with move
    r "After moving back to the center..." id ringo_msg5

    show ringo attack
    $ renpy.pause(0.05) # wait briefly for the attack's hit moment (the downward swing)

    # fire the effect at the hand to match the attack. The effect was authored
    # around its canvas centre, so xcenter / ycenter place that point.
    show hit_effect:
        xcenter 490 ycenter 410

    r "Ei! (When the attack finishes, I automatically return to the idle motion, su.)" id ringo_msg6

    r idle "Furthermore, by linking with the Character's 'image' argument, you can control expressions and motions just with say statements like this, su!" id ringo_msg7

    hide ringo
    with dissolve

    # Bonus: Ringo_tyu and the e040b particle effect shown simultaneously.
    show ringo_tyu at ss_stand
    show effect_e040b:
        xcenter 0.5 ycenter 560
    "As a bonus, here's my companion Ringo_tyu, along with a cool particle effect (e040b) playing at the same time!" id ringo_msg8

    return
