# Shared image definitions for the demo scenes.
#
# `bg room` is the backdrop the demo scenes drop the SSPlayer characters onto
# (`scene bg room` in scene_helper.rpy / scene_ringo.rpy / scene_mask.rpy). It is
# a flat fill matching the SSPlayer preview/viewer background (`ss_demo` screen in
# scene_viewer.rpy, `Solid("#2a2e36")`) so the character reads the same on the
# demo pages as it does in the in-engine viewer. Swap this for an image file at
# `game/images/bg room.png` if you want real art instead.
image bg room = Solid("#2a2e36")
