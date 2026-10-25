# 🔘 Buttons

`SSButton` makes an animation a button. Each state of the button — idle, hover, held down, insensitive, and selected — plays its own part of the animation, and the mouse can be kept to some of its parts, so an irregular button stops taking clicks across its whole box. It is a Ren'Py button, so `action`, `alt`, `hovered`, styles, sounds and the keyboard work as they do for an `imagebutton`.

```renpy
screen title_menu():
    add SSButton("ss_assets/ui/start.ssab", action=Start(), parts=["face"], alt=_("Start")):
        xalign 0.5
        yalign 0.7
```

The first argument is the `.ssab` path, or an `SSPlayer` you made — pass one when you want its own arguments (`size=`, callbacks) or keep it in a variable.

`SSButton` is in `spritestudio/ss_ui.rpy`. A game that does not use it can delete that file.

## States and Labels

In SpriteStudio, put labels named after the states in one animation:

| Button state | Label |
|---|---|
| idle | `normal` |
| hover — the mouse over it, or the keyboard on it | `hover` |
| held down — the mouse button held down on it | `pressed` |
| insensitive | `disabled` |

Each state plays from its label up to the frame before the next label — whatever that label is called — and loops. The last label runs to the end of the animation. Labels match exactly, so write them in lower case.

- A state with no label plays `normal` (`pressed` plays `hover` first); with no `normal` either, the whole animation plays.
- The labels are read from the animation the player is on when the button first shows (the pack's first animation for a path). `animation="button"` names another.

### Selected Buttons

A button is selected when its action says so — a `SetVariable` whose variable holds its value, a `ToggleVariable` that is on, a `Preference` that is set. A selected button plays the same labels with `selected_` in front: `selected_normal`, `selected_hover`, `selected_pressed`, `selected_disabled`.

When a selected label is missing, the selected label it falls back to is tried before any plain one, so whether the button is on stays visible: a selected button under the mouse plays `selected_hover`, else `selected_normal`, and only then `hover`, `normal` or the whole animation. Held down is the exception: `pressed` comes right after `selected_pressed`, because it lasts only while the mouse is down and shows that the press was taken. An animation with no selected labels plays as it does unselected.

```renpy
# A toggle: Ringo dances while the music is on
add SSButton("ss_assets/Ringo/Ringo.ssab", action=ToggleVariable("music_on"),
             clips={"normal": "wait1", "selected_normal": "dance"})
```

## Using Other Animations (`clips`)

`clips` gives a state something else to play than its label: the name of a whole animation, or a dict with an `"animation"`, a `"label"` or both — a label's section, in that animation or in the one the labels are read from. The keys are the label names, `selected_normal` and the other selected ones included.

```renpy
# Ringo has no labels named after the states, so each state plays an animation
add SSButton("ss_assets/Ringo/Ringo.ssab", action=Start(),
             clips={"normal": "wait1", "hover": "joy", "disabled": "sitdown_wait"})

# Hover plays the "glow" label's section of the "effects" animation
add SSButton(menu_player, clips={"hover": {"animation": "effects", "label": "glow"}})
```

A clip also covers the states that fall back to it: a `normal` clip plays for hover and insensitive too, when they have no label or clip of their own. A clip naming an animation or a label the pack lacks is reported once in `log.txt`, and the state plays as if it had none.

## Where the Mouse Counts

| You pass | The mouse counts on |
|---|---|
| nothing | the whole box |
| `focus_mask=True` | the drawn pixels, as for an image button |
| `parts=["face", "hand"]` | the outlines of those parts as they are drawn, frame by frame (see [Outlines and Hit Testing](usage.md#outlines-and-hit-testing)) |

The keyboard reaches the button whichever you choose. The box is the player's — the animation's canvas, or its `size=` — so art drawn outside it takes no clicks. A `zoom` in an `at` transform on the button scales the area with the art.

## Reduced Motion

`reduced_motion=True` holds each state on the first frame of its section. The player is stopped, so no events or sounds fire. Where the animation has a `reduced_motion` label, idle plays that label's section instead, so a button can keep a gentle loop. A selected button stays held on its selected section, so it still shows that it is on.

Ren'Py has no setting for it, so keep one among your preferences:

```renpy
default persistent.reduced_motion = False

screen title_menu():
    add SSButton("ss_assets/ui/start.ssab", action=Start(),
                 reduced_motion=persistent.reduced_motion)

# in the preferences screen
textbutton _("Reduce motion") action ToggleField(persistent, "reduced_motion")
```

## Self-Voicing

With self-voicing on, the button reads its `alt` text, as an image button does. Without `alt`, the animation itself says nothing.

## Notes

- **The button plays the player.** It picks the animation, the section and the loop count, and plays and stops it, so do not call `ss_play()` and the like on that player, nor show it anywhere else.
- **Held down is the mouse's.** Ren'Py's own buttons have no such state. `SSButton` shows it while the mouse button, or a touch, is down over the button: whenever letting go would click it, since Ren'Py clicks the button the mouse is released over, wherever the press began. A key runs the action as it goes down, so the keyboard shows no held-down state.
- `parts` names the parts of the pack the player itself plays, not the parts inside an Instance part.
