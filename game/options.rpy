# SpriteStudio Player for Ren'Py — demo project configuration.
#
# This is part of the DEMO, not the library (see CLAUDE.md). It exists so the
# project runs as a standalone Ren'Py app via `renpy-sdk/renpy.sh .`.
#
# The key line is `gui.init(...)`: it triggers `layout.defaults()`
# (renpy/common/00gui.rpy), which wires up the quit / main-menu prompts. Without
# it, a bare project (script.rpy only) crashes when you close the window with
#   AttributeError: 'Layout' object has no attribute 'yesno_prompt'
# because the layout system was never initialized.

define config.name = _("SpriteStudio Player for Ren'Py — Demo")
define config.version = "demo"
define config.save_directory = "SSPlayerForRenPy-demo"
define config.window_title = "SpriteStudio Player for Ren'Py — Demo"
define config.has_autosave = False
define config.has_quicksave = False

init python:
    gui.init(1280, 720)
