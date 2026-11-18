# SpriteStudio images — every converted pack is an image, the way Ren'Py makes
# one of every file under images/.
#
#     show ringo              # ss_assets/Ringo/Ringo.ssab, its first animation
#     show ringo wait1        # ... playing wait1; any animation is an attribute
#
# The tag is the .ssab's file name, lower-cased, with anything a show statement
# cannot spell (a space, a bracket) turned into "_": "Ringo.ssab" is `ringo`,
# "BG art w pink.ssab" is `bg_art_w_pink`. The packs are the ones the Shift+B
# browser lists — under ss_assets/, and the auto importer's `ss_output_dir` —
# and they are registered in the shipped game too, from inside a .rpa as well.
#
# A tag the game already uses is left alone: an `image` statement, an
# SSCharacter, or a file under images/ with that tag defines it, and this adds
# nothing. Registration runs late (init 999) so that all of those come first.
# Of two packs that spell one tag, the first in path order has it.
#
# `define ss_auto_images = False` turns this off; so does deleting this file.

init 999 python:
    from ss_renpy.snippet import image_tag as _ss_image_tag

    def _ss_register_images():
        if not getattr(store, "ss_auto_images", True):
            return
        roots = _ss_index_roots()
        taken = set(renpy.get_available_image_tags())
        registered = {}
        for p in sorted(renpy.list_files()):
            rp = p.replace("\\", "/")
            if not rp.endswith(".ssab") or not any(
                    rp == r or rp.startswith(r + "/") for r in roots):
                continue
            stem = rp.rsplit("/", 1)[-1][:-len(".ssab")]
            tag = _ss_image_tag(stem)
            if tag in taken:
                # A tag the game defined is the game's to keep. A second pack
                # spelling a tag this registered is worth a line, since
                # `show <tag>` quietly plays the first.
                if tag in registered and config.developer:
                    print("[SSPlayer] image %s is %s; %s spells the same tag and "
                          "is not an image (use its path)." % (tag, registered[tag], rp))
                continue
            # The player opens nothing until it is shown, so registering every
            # pack costs a file listing, not a read of each one.
            renpy.image(tag, SSPlayer(rp))
            taken.add(tag)
            registered[tag] = rp

    _ss_register_images()
