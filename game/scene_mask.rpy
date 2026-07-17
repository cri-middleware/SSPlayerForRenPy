# Mask / clipping-mask feature sample. Shows the `overall/Mask` pack,
# which contains both pure masks (cut holes / keep OUTSIDE) and clipping
# write-masks (confine INSIDE), plus a reversed mask and circle cut-outs.
# (Reached from the start menu in script.rpy.)

# A `size` is given so it positions like a normal image (xalign/yalign), centered
# in the box.
image mask_sample = SSPlayer(
    "ss_assets/overall/Mask.ssab",
    size=(640, 640),
)

label mask_demo:
    scene bg room
    window show

    show mask_sample:
        xalign 0.5 yalign 0.5
    with dissolve

    "This is the SpriteStudio 'Mask' sample (overall/Mask.ssab)." id mask_msg1

    "A pure mask part cuts a hole in the parts drawn below it — the content is kept OUTSIDE the mask shape (e.g. the circular cut-outs)." id mask_msg2

    "A clipping (write-mask) part instead confines the parts drawn above it INSIDE its own shape, like a window." id mask_msg3

    "Both effects come from one stencil: each part's 'visible inside mask' flag decides the inside/outside polarity per the spec (09_mask)." id mask_msg4

    hide mask_sample
    with dissolve
    return
