# ▶️ Usage Guide

In SpriteStudio Player for Ren'Py, you have very flexible control over SpriteStudio animations within Ren'Py. This guide explains how to use the player depending on your goals, ranging from simple rendering to integrating character standing images, and handling event callbacks.

> [!IMPORTANT]
> **Placement of `.ssab` files**
> The converted `.ssab` file, its textures (`.png`), and any referenced external instance packs must **reside in the same folder** (the auto importer outputs them to `game/ss_assets/<ProjectName>/`). Because the player resolves related resources from the same directory as the `.ssab`, you do not need to specify a separate folder for textures.

---

## 1. The Simplest Playback (Calling from a Screen)
Because the `SSPlayer` class acts as a Ren'Py Displayable (drawing object), the simplest way to show an animation is by `add`ing it directly into a screen.

```renpy
screen demo():
    # The first argument is the path to the .ssab (relative to game/)
    add SSPlayer("ss_assets/Ringo/Ringo.ssab") xalign 0.5 yalign 0.5
```

A screen runs again on every interaction, and keeps the player it is showing for as long as the arguments stay the same, so the animation plays on from line to line. Change an argument — `animation=` from a screen variable, say — and the screen gets a new player that starts from the top.

A player you keep in a variable is the one on screen: after `default ringo = SSPlayer(...)`, `add ringo` in a screen and `show expression ringo` both show that player, so `ringo.ss_*` calls — overrides, attachments, `ss_set_animation()` — reach what is drawn. Placed in several spots at once (two tags, or the particles of a `SnowBlossom`), it draws the same frame in each.

### Basic Parameters
- **1st Argument**: The path to the `.ssab` to play (relative to `game/`, e.g. `"ss_assets/Ringo/Ringo.ssab"`). Because the `.ssab` and its textures and external instance packs live together, this is enough to resolve the related resources. **You can also load an `.ssab` from an `.rpa` archive** (via the Ren'Py loader).
- **`animation` (Optional)**: The name of the animation to play initially. If omitted, the first animation in the data is played. **If you pass a non-existent name, it will result in an error** (with a list of valid animation names) on the first display. Lint (`renpy.sh . lint`, or **Check Script (Lint)** in the launcher) reports it before that for a player in an `image` or a `define`, along with a `.ssab` path that does not load and an image attribute that names no animation.
- **`loop` (Optional)**: Playback count. `-1` (default) for infinite loop, `1` for a single play, `N` for N plays. `0` is a synonym for `-1` (infinite), not "do not play".
- **`speed` (Optional)**: Playback speed multiplier (default `1.0`).
- **`size` (Optional)**: A `(w, h)` box (or a single number for a square) to use in place of the canvas, with the animation's origin at the box's centre. You rarely need it — see below.

### Size and Placement
Without `size`, a player is the size of the **canvas the animation was authored on** in SpriteStudio, with the animation's origin where the canvas's pivot puts it — the frame a PNG export of that animation would have. So it lays out like any image: `xalign` / `xpos`, `at left` / `at right` and Ren'Py's default bottom-centre placement all work, and a character authored standing on the bottom edge of its canvas stands wherever its `ypos` puts it.

- The size comes from the animation the player **starts** on and stays when the animation changes — through `ss_set_animation()` or an image attribute such as `show ringo dead` — so a sprite does not move when you switch it, even to an animation authored on a wider canvas. Whatever an animation draws outside that box is still drawn.
- To fit an animation into a box of your own, use Ren'Py's `fit` transform property. `scale-down` shrinks a canvas that is too big and leaves a smaller one alone:

```renpy
add SSPlayer("ss_assets/Ringo/Ringo.ssab") fit "scale-down" xysize (400, 300) xalign 0.5 yalign 1.0
```

> [!TIP]
> Not sure which pack or animation to use? Open the **Asset Browser** with **Shift+B** in developer mode to browse every `.ssab`, preview animations live, and copy a ready-to-paste snippet. See the **Asset Browser** section (§10) below.

> [!NOTE]
> The old `sprites_subdir` argument remains for backward compatibility, but it is unnecessary when specifying the path (deprecated).

---

## 2. Using as Standing Images (`image` statement and Character integration)
By combining it with Ren'Py's `image` statement, it functions powerfully as a **character standing image** (tachie) in visual novels. Using the `aliases` argument, you can link Ren'Py attribute names to SpriteStudio motion names.

```renpy
# Character definition (specify the .ssab path)
image ringo = SSPlayer(
    "ss_assets/Ringo/Ringo.ssab",
    aliases={
        "idle": "wait1",    # When 'idle' is called, play the 'wait1' motion
        "happy": "joy",
        "walk": "walk",
        "attack": ["attack1", "wait1"] # Pass a list to play them sequentially!
    }
)

define r = Character("Ringo", image="ringo")

label start:
    # Show default standing image (idle motion) at the bottom centre
    show ringo idle

    r happy "The motion switches just by changing the attribute!"

    # Make them walk by combining with Transform
    show ringo walk at left
    with move

    r attack "Attack! (It automatically returns to wait1 when attack1 ends)"
```

### Even Easier: Talking Character (`SSCharacter`)
Using `SSCharacter`, you can define a "living character" in one line that **automatically switches to 'talk' while speaking, and 'idle' when stopped**. This prepares the `image` declaration, `Character` definition, and lip-sync synchronization all at once, removing the need for line-by-line Python.

```renpy
# Register image + Character + lip-sync linked definition (tag is .ssab stem = "ringo")
define ringo = SSCharacter(
    "ss_assets/Ringo/Ringo.ssab",
    talk="talk",     # Animation name to play while speaking
    idle="wait1",    # Animation name when silent
)

label start:
    show ringo            # Show with tag "ringo"
    ringo "Hi. It stays on 'talk' while speaking, and returns to 'idle' when finished."
```

- The image tag is the lowercased file stem of the `.ssab` (e.g., `"ringo"`). You can override it with `tag=`.
- You can also pass `aliases=` (for emotions, etc.) and `size=` (see [Size and Placement](#size-and-placement)).
- The lip-sync start/stop timing can be adjusted using `start` / `stop` (Character callback event names).

> [!NOTE]
> While a line is spoken, `talk` replaces the attribute the sprite was showing, so an emotion such as `show ringo happy` is not visible during the line; it comes back when the line ends. There is no per-emotion talk animation.

---

## 3. Using as Effects (Loop Count Control)
For animations like magic explosions or hit effects that play once and end, you can restrict the playback count with the `loop` argument.

```renpy
image hit_effect = SSPlayer(
    "ss_assets/ParticleEffect/e038.ssab",
    animation="hit",
    loop=1 # End and disappear from the screen after 1 playback (or stop on the last frame)
)

label battle:
    # Show the effect at a specific position matching the attack. This effect
    # was authored around the centre of its canvas, so xcenter / ycenter place it.
    show hit_effect:
        xcenter 490 ycenter 410
    "KABOOM!"
```

---

## 4. Dynamic Control from Python
You can switch animations directly from Python (scripts) or retrieve information depending on the game logic.

```renpy
$ player = SSPlayer("ss_assets/Ringo/Ringo.ssab")

# Get a list of all included animation names
$ anim_names = player.ss_animation_names()

# Get the currently playing animation name
$ current_anim = player.ss_get_current_animation()

# Switch to an arbitrary animation (switch + cue -> play)
$ player.ss_play("run")
```

- **Separation of Switching and Playback**: `ss_set_animation("run")` only switches to the animation and cues it; it does not start playing. `ss_play()` starts the playback.
- **Switching is cheap**: everything the `.ssab` needs — textures included — is loaded in one go when the sprite is first shown, so `ss_set_animation()` is light enough to call every frame (there is no per-animation loading).
- **Playback Control**: `ss_pause()` / `ss_resume()` / `ss_stop()` (the playhead **stays where it stands** — `ss_stop()` does not rewind; `ss_play()` is what returns to the head), frame control `ss_set_frame_no()` / `ss_get_frame_no()`, speed `ss_set_speed_scale()`, and looping `ss_set_loop_count()` are available.
- **Playback finished**: `ss_is_finished()` reports whether every configured loop has played. A **state**, not a pulse — it latches on completion and stays true until the next `ss_play()` / `ss_set_animation()`, so a screen can ask about a completion it did not witness. It is not `not ss_is_playing()`: `ss_stop()` also stops playing but is not a completion, and this is what tells the two apart. Never true under an infinite loop count. The rising edge is the `on_animation_finished` callback; with a sequence, both describe the sequence being spent rather than each clip in it.
- **Playback Direction**: `ss_set_playback_direction(direction, style)` takes the two enumerators `ssruntime` exports — `DIRECTION_FORWARD` / `DIRECTION_BACKWARD` and `STYLE_NORMAL` / `STYLE_PINGPONG` — so reverse is `ss_set_playback_direction(ssruntime.DIRECTION_BACKWARD, ssruntime.STYLE_NORMAL)` and ping-pong is `STYLE_PINGPONG`. They are the Brain's own names, shared with every sibling Player; prefer them to the bare `0` / `1`. Read the current setting back with `ss_get_playback_direction()` / `ss_get_playback_style()` — these report the *setting*, not the instantaneous heading, so a ping-pong return leg still reads forward. `ss_is_playing_forward()` is the actual heading — **gate audio on it**: SpriteStudio has no reverse audio, so a sound key crossed on a backward leg is not meant to sound, and it is the test this player applies itself.
- **Loop boundary**: `ss_just_looped()` reports whether the last update crossed one. A **pulse**, not a state — true only inside the tick that crossed, which is why it is not `ss_is_looped`, and why reading it a tick late reads false.
- **Frame Skip**: on by default, so playback follows the clock — after a stall it catches up by skipping ahead, and a 2-second animation always takes 2 seconds. `ss_set_frame_skip_enabled(False)` advances exactly one frame per rendered frame instead: nothing is skipped, and a stall stretches the animation. Use it when every frame must be seen (a short effect, a frame-counted cutscene). Also available as the constructor argument `frame_skip=False`.
- **Part Query**: `ss_part_transform("part_name")` retrieves the local transform (x/y/rotation/scale) of the part for the most recent frame. For the whole part-query set, and for making a displayable follow a part, see the **Part Tracking** section (§5) below.

---

## 5. Part Tracking (Following a Specified Part)

A feature that makes a displayable you provide (a weapon, an effect, a hit marker) follow a specified part every frame. This player has no scene tree to place the follower into, so the child is **composited into the player's own render** at the part's position. You own the child and its contents; the player only draws it — and because it rides inside the player's render, any `at` clause, `Transform`, or `zoom` applied to the player carries the child along with it.

> The child can be any Ren'Py displayable: an image name, a `"file.png"`, a `Text(...)`, a `Solid(...)`, a `Transform(...)` — even another `SSPlayer`.

Configure it by passing `attachments=` to the constructor, as a `{part_name: child}` dict.

```renpy
image ringo = SSPlayer(
    "ss_assets/Ringo/Ringo.ssab",
    attachments={"head": Text("!", size=40), "hand_r": "sword.png"},
)
```

| Setting | Description |
|---|---|
| **part** | The name of the part to follow (the PartData name in the `.ssab`). `ss_part_names()` lists them, and the Asset Browser (Shift+B) shows them per pack |
| **child** | The displayable to make follow |
| **anchor** | Which point of the child is pinned to the part, as a 0–1 fraction of its size. `(0.5, 0.5)` centers it (default); `(0.5, 1.0)` puts its bottom edge on the part — the grip of a held item. This is also the rotation / scale pivot |
| **angle** | A fixed rotation offset in degrees (clockwise-positive) added on top of the part's own rotation, so the child's rest orientation lines up with the part's local axis |
| **drive_position** | Reflect the part's position. On by default |
| **drive_rotation** | Reflect the part's rotation. On by default |
| **drive_scale** | Reflect the part's scale as well. **Off by default** — a follower is placed *at* the part, not sized by it |
| **on_hide** | Behavior on frames where the part is hidden. `"follow"` (keep drawing; default) / `"hide"` (drop the child for those frames) |

### Registering from a Script

Attachments can also be added and removed at runtime instead of through the constructor.

```renpy
# Grip the sword by its bottom edge and lay it along the fingers
$ sword = ringo.ss_attach("hand_r", "sword.png", anchor=(0.5, 1.0), angle=-90)

# Also reflect the part's scale, and stop drawing on hidden frames
$ ringo.ss_attach("head", "aura.png", drive_scale=True, on_hide="hide")

# Remove (by child, by part, or all of them)
$ ringo.ss_detach(child=sword)
$ ringo.ss_detach(part="hand_r")
$ ringo.ss_clear_attachments()
```

| Method | Description |
|---|---|
| `ss_attach(part, child, drive_scale, on_hide, anchor, angle, drive_position, drive_rotation)` | Adds an attachment and returns the normalized child (pass it back to `ss_detach`) |
| `ss_detach(child=None, part=None)` | Removes every attachment matching that child and / or part, and returns the number removed. With neither given it removes nothing |
| `ss_clear_attachments()` | Removes every attachment and returns the number removed |
| `ss_attachments()` | The current attachments as `(part_name, child)` pairs |
| `ss_part_names()` / `ss_find_part_index(part_name)` | The pack's part names / one part's index (`-1` if the part is not in the asset) |
| `ss_is_part_hidden(part_name)` | Whether the part is hidden on the last rendered frame |
| `ss_is_part_skinned_mesh(part_name)` | Whether the part is a bone-skinned mesh — a poor follow target (see the note below). Static, so it answers before the first frame |
| `ss_part_transform(part_name)` | The part's transform for the last rendered frame, or `None` |

> When you only need the part's position at a single moment (a projectile spawn point, for example) rather than continuous following, calling `ss_part_transform()` directly is simpler.

> **`show <tag>` draws a copy.** An `SSPlayer` registered with `image` is duplicated every time it is shown, so `attachments=` given to the constructor does carry into the copy — but a later `ss_attach()` on the variable you kept edits the template, not what is on screen. To attach while the game runs, keep one instance and show that object with `show expression player as tag`.

### Timing and Accuracy

Attachments are composited inside the player's own `render()`, in the same pass that computes the frame's pose, so **a child never lags the animation** — there is no separate drive step that could run at the wrong moment.

`ss_part_transform()` returns the pose the compositing itself uses, in player-local pixels with the animation's origin at the center of the player's box.

| Key | Meaning |
|---|---|
| `x` / `y` | Position in px, relative to the animation origin. Y is **down-positive** |
| `rotation` | Degrees, **clockwise-positive** |
| `xscale` / `yscale` | Scale as a **magnitude** (always positive) |

It returns `None` until the first frame has been rendered, and for a part that is not in the frame being drawn. A child whose part reads `None` is simply skipped for that frame.

`anchor` doubles as the rotation / scale pivot, and the child's unrotated size is measured every frame, so a child that changes size keeps its anchor. A hand part carries the wrist angle, so a held item usually needs an `angle` offset to lie along the fingers rather than standing straight up.

### Mirrored Parts

A part's pose can be a **reflection**, not merely a rotation and a scale. That happens whenever the part or one of its ancestors carries a negative scale in SpriteStudio, and it is common in real artwork — building the right-hand parts by mirroring the left-hand ones is ordinary practice.

**The position is always exact, and so is the direction the part faces** — `rotation` is the angle of the part's own +X axis whether or not the part is mirrored. What a child cannot receive is the reflection itself: `xscale` / `yscale` are magnitudes, so the sign that carries the mirror is dropped and **a child is never mirrored**, with or without `drive_scale`.

One consequence is worth knowing, because it does not look like a scale problem. A reflection is described as a rotation plus a flip of the Y axis, so a part that is *purely* mirrored left-to-right, with no rotation of its own, reports `rotation` as `±180` rather than `0`, with `xscale` and `yscale` both still positive. Take the Y flip away and a half-turn is what remains: the child is drawn **upside-down rather than mirrored**. That triple is **exactly what a part genuinely rotated by half a turn reports**, so these three values cannot tell the two apart.

This follows from describing a pose as a rotation and a scale at all, so it is something to design around rather than a defect to wait on:

- A **symmetric** child is unaffected. It looks the same mirrored, and its position and angle are exact.
- For an **asymmetric** child on a mirrored part, supply the mirrored artwork yourself, or pin it to a part that is not mirrored.
- The player does not report whether a pose is a reflection, so when it matters, check the part **and its parents** in the source project. Note that two mirrors cancel: a mirrored part under a mirrored parent is not mirrored.

> **Mirroring the whole sprite mirrors its children with it.** `at Transform(xzoom=-1.0)` applies to the player's finished output, and attachments are composited inside that output, so a child flips along with the artwork. For a character turning around, that is usually what you want; when it is not — a name plate or a gauge that has to stay readable — mirror the player and place that element outside it rather than attaching it.

### Notes

- **Children draw in front of the whole sprite.** They cannot be inserted between parts, so a child cannot be made to pass behind the character's body.
- The part name does not have to exist yet. A child registered for a part that is not in the current animation is simply not drawn, and starts riding on its own once the part appears.
- Part names resolve against the parts of the pack the player itself is playing. **Parts inside an Instance part (the child animation) cannot be specified** (the Instance part itself can).
- If several parts share a name, the **last** one in the pack is used. Rename duplicates in SpriteStudio when you need a specific one.
- **A bone-skinned mesh part cannot be followed directly.** A mesh part bound to bones (a deforming part such as a hand or a face) has its vertices drawn by bone skinning, while the part's own transform stays at its setup node position — usually near the character root. So attaching a child to such a part makes the child snap near the root rather than onto the visible art. To follow that spot, add a **NULL part** (a bone-point / empty part) at it in SpriteStudio and target that part's name instead; a bone (armature) or joint part works the same way. `ss_is_part_skinned_mesh("part_name")` reports whether a part is one of these — and `ss_attach` logs a one-time note (in `log.txt`) when it is handed such a target. A deform-only (rigid) mesh, which has no bones, follows fine and is not flagged.
- **A part's skew is not carried to its follower.** SpriteStudio applies skew (shear) as a per-part deform that is *not* passed down to a part's children, and a follower behaves like a child — so a follower pinned to a sheared part rides its position, rotation and scale without the shear, and one under a sheared *parent* is unaffected by that parent's shear. This matches the editor. The art itself still draws sheared; only the pose a follower receives leaves skew out.
- Several children can ride the same part, and one player can carry as many attachments as you like.
- Attachments are plain data, so they are **saved with the game and survive rollback** — there is no re-registration step after a load.
- A child that fails to render is skipped for that frame and can never break the sprite.

---

## 6. Part Overrides (Part Color / Cell / Visibility)

Per-part runtime overrides let a script say "make this part this color / this cell / hidden **now**". An override wins over both the keyframe and any animation blending, so it does not have to fight the animation.

```renpy
$ ringo = SSPlayer("ss_assets/Ringo/Ringo.ssab", animation="wait1")

# Tint a part red (1 = Mul). Applies to normal (image) parts.
$ ringo.ss_set_part_color_override("apple", "#f00", blend_op=1)

# Make a part draw a different cell (cellmap name is written without ".ssce").
$ ringo.ss_set_part_cell_override("apple", "Ringo", "effect3")

# Force-hide a part, cascading to its descendants.
$ ringo.ss_set_part_visibility_override("apple_base", True, cascade=True)

# Revert
$ ringo.ss_clear_part_color_override("apple")
$ ringo.ss_clear_all_part_overrides()
```

| Method | Description |
|---|---|
| `ss_find_part_index(part_name)` | Part index, or `-1` if the part is not in the asset |
| `ss_set_part_color_override(part, color, blend_op=0, priority=1)` | Part Color override (single color) |
| `ss_set_part_color_override_corners(part, corners, blend_op=0, priority=1)` | Four-corner form: left-top, right-top, left-bottom, right-bottom |
| `ss_set_part_cell_override(part, cellmap_name, cell_name, priority=1)` | Draw a different cell |
| `ss_set_part_visibility_override(part, hide=True, cascade=False)` | Force-hide (`hide=False` reverts to the animation) |
| `ss_clear_part_color_override` / `ss_clear_part_cell_override` / `ss_clear_part_visibility_override` | Clear one override on one part |
| `ss_clear_all_part_overrides()` | Clear every override on the player |
| `ss_cellmap_names()` / `ss_cell_names(cellmap_name)` | Discover the cellmap / cell names you can pass to a cell override |

The `part` argument of every method takes either a **part name** or a **part index**, and the call returns `False` when the part is unknown or the runtime rejects it.

**Colors** take any Ren'Py color form — `"#f00"`, `(255, 0, 0)`, `Color(...)`, or a packed `0xRRGGBBAA` int.

The cellmap / cell names you can pass to a cell override are enumerated from the pack:

```renpy
$ print(ringo.ss_cellmap_names())       # -> ["Ringo", ...]
$ print(ringo.ss_cell_names("Ringo"))   # -> ["effect3", ...]
```

> **On using part indices**: Part indices are stable within one asset (the same `.ssab`), so if you set overrides frequently, resolve the name once with `ss_find_part_index()` and reuse that index.

### Blend operation (`blend_op`)

The `blend_op` of `ss_set_part_color_override()` offers the same four operations as the keyframed Part Color.

| Value | Blend operation |
|---|---|
| `0` | Mix (default) |
| `1` | Mul (multiply) |
| `2` | Add |
| `3` | Sub (subtract) |

An out-of-range value fails the call and returns `False`.

### Priority mode (`priority`)

Part Color and cell overrides conflict with the animation, so they take a `priority` (visibility does not — it is a plain force-hide flag, and any new animation clears it):

| Value | Priority mode | Behavior |
|---|---|---|
| `0` | OverwriteOnNextKeyframe | The override applies until the animation data updates that attribute |
| `1` | HoldUntilNextAnimation (default) | The override wins for the current animation and is cleared when a new animation is set up |
| `2` | Permanent | The override applies for as long as the same animation data (`.ssab`) is playing, surviving animation changes |

### Notes

- **Color** applies to normal parts, **cell** to normal and mask parts; other part types silently ignore the override (the call still returns `True`).
- Colors are interpreted in the same 8-bit sRGB space as the authored Part Color, and alpha is pre-multiplied by the runtime — pass the color as authored, without converting it yourself.
- A cell override is resolved when you set it, so an unknown cellmap / cell name fails immediately (returns `False`).
- Overrides live on the runtime, which owns their lifecycle. Do not re-apply them after an animation change; choose the priority mode that expresses what you want instead.
- Overrides are restored when a saved game is loaded, so a costume change survives save / load. One-shot (`priority=0`) overrides are the exception — they are momentary by design and are not carried across a save.
- Overrides do not reach parts **inside** an instance part (the child animation runs as a separate player). Force-hiding the instance part itself does stop its contents from being drawn.

> **On when an override is reflected in the drawing**: setting or clearing an override redraws the sprite immediately, even while playback is stopped or paused — you do not have to nudge the frame to make it appear.

> [!NOTE]
> **Whole texture vs. one part.** The *cell* override here repoints a single part to a different cell of the same texture. To swap the **entire** texture at runtime — a costume or palette change that applies to every part sampling it — use `ss_set_cellmap_texture()` instead; see section 7, *Runtime Texture Replacement*, below.

---

## 7. Runtime Texture Replacement (Costume / Expression Changes)

Swap the texture an animation samples from — **at runtime, from your script** — without touching the original data. This is how you do a costume change or a dynamic facial expression: prepare a second atlas with the **same layout** and bind it in place of the pack's own.

This is different from the Part Overrides above. A *cell* override repoints **one part** to a different cell of the same texture; a texture replacement swaps **the whole texture** wherever it is drawn.

```renpy
$ ringo = SSPlayer("ss_assets/Ringo/Ringo.ssab", animation="wait1")

# Bind a different atlas in place of the "Ringo" cellmap.
$ ringo.ss_set_cellmap_texture("Ringo", "ss_assets/Ringo/Ringo_night.png")

# Restore the pack's own atlas.
$ ringo.ss_set_cellmap_texture("Ringo", None)
```

| Method | Description |
|---|---|
| `ss_texture_names()` | The texture names you can replace (every cellmap, plus any texture-change target) |
| `ss_set_cellmap_texture(name, texture)` | Replace the atlas `name` binds; `texture` is any displayable (an image name, `"file.png"`, or a Displayable). `None` restores the original |
| `ss_get_cellmap_texture(name)` | The displayable currently overriding `name`, or `None` when it is not overridden |

The `name` is a **cellmap name** (written without `.ssce`, e.g. `"Ringo"`) or a **texture file name** (e.g. `"common.png"`); enumerate the valid ones with `ss_texture_names()`. An unknown name returns `False`.

### Notes

- **Same size and layout.** The replacement is assumed to be an atlas of the same size and cell layout as the original — the cell rectangles and UVs are unchanged, so a texture of a different resolution samples a different region. Swap in a re-skin, not an arbitrary picture.
- **Whole-texture, not per-part.** The swap takes effect everywhere that texture is drawn in this player, including instance sub-animations that bind the same file. To repoint a single part, use a cell override instead.
- **Texture changes are covered.** When the animation itself switches textures on the timeline (an authored *texture change*), replacing the cellmap also covers those frames — the cellmap and its texture-change target resolve to the same image here.
- **Survives save / load.** A replacement set from your script is restored when a saved game is loaded, so a costume change persists.
- Setting or clearing a replacement redraws the sprite immediately, even while playback is stopped or paused.

---

## 8. Handling Animation Events (User Data / Signals)
You can receive information on "User Data" and "Signals" configured on the SpriteStudio side within Ren'Py. This makes it possible to play sound effects on specific frames or synchronize script progression.

### Receiving via Callbacks (Event-Driven)
By passing corresponding functions during the `SSPlayer` instance creation, you can trigger logic at specific timings.

```python
init python:
    def my_signal_handler(player, frame, signal):
        print(f"Signal Received: Command={signal.command_id}, Params={signal.params}")

    def my_finish_handler(player):
        print("Animation reached the end")
```
```renpy
# Register callbacks and play
image boss = SSPlayer(
    "ss_assets/Boss/Boss.ssab",
    on_signal=my_signal_handler,
    on_animation_finished=my_finish_handler
)
```

**Available Callback Arguments:**
- `on_user_data`: Called when User Data is reached
- `on_signal`: Called when a Signal is reached
- `on_audio`: Called when an audio playback specified frame is reached
- `on_animation_finished`: Called once every configured `loop` has played. Never fires under an infinite loop, nor on a commanded stop
- `on_animation_looped`: Called each time a loop iteration completes; the final iteration fires `on_animation_finished` instead
- `on_animation_started`: Called when animation playback starts

> [!NOTE]
> Callbacks are invoked from the drawing thread in the form `cb(player, frame_index, event)` for the per-part events, and `cb(player)` for start/finish/loop. `frame_index` is the frame the key is **authored** on, which is not necessarily the frame it was noticed on — one update can step across several and fires every key in between. The event itself carries `part_index` and `part_name` (`None` when the pack has no name for that part). To support pickling during rollback, please pass module-level functions rather than lambdas or local functions.

*Note: For polling-based retrieval (`ss_poll_events()`), refer to implementations like `ss_drain_events()` inside `scene_viewer.rpy` of the demo project.*

---

## 9. Utilities

### One-Shot Playback Made Easy (`ss_play_once`)
Plays any `.ssab` once (effect or full-screen cutscene). With `wait=True`, it waits until playback finishes and automatically disappears; hide a non-waiting one with `ss_hide_once(tag)`.
```renpy
$ ss_play_once("ss_assets/ParticleEffect/e038.ssab", "hit",
               at=Transform(xcenter=640, ycenter=360), wait=True)
```
`ss_duration("…/Ringo.ssab", "attack1")` returns the duration in seconds for one cycle of that animation, so a character's "play and wait" can be written as `show ringo attack` + `$ renpy.pause(ss_duration(...))`.

### Checking Behavior (Diagnostics)
In developer mode, "runtime loaded / N pack(s)" is output to the log on startup. By calling `ss_diagnostics()` in the console (Shift+O), you can check the runtime status and a list of detected packs. If an `.ssab` cannot be read, you will get a clear error containing its path (relative to `game/`).

---

## 10. Asset Browser (Shift+B): Discover, Preview, and Copy Snippets

Press **Shift+B** in developer mode to open the **Asset Browser** — a built-in inspector that turns "which pack do I play, and how?" into a two-click answer. It is developer-mode only (the hotkey is disabled in release builds) and overlays the running game, so you can call it up at any time.

> [!TIP]
>
> <video autoplay loop muted playsinline width="100%">
>   <source src="assets/2-asset_browser.webm" type="video/webm">
> </video>
> <img src="assets/2-asset_browser.webp" width="100%" style="display: none;">

The window has three panes:

1. **Pack list (left).** Every `.ssab` the resolver can find under `ss_assets/` — including packs bundled inside an `.rpa` archive. Click one to select it.
2. **Live preview (center).** The selected animation plays for real (not a static thumbnail), alongside a metadata line — number of `animations`, `fps`, whether it has `effects`, and any external instance packs. Click any animation in the list to preview it instantly. **Drag** the sprite to move it and **scroll the wheel** (or press `+` / `-`) to scale it — handy for a pack whose art is far bigger or smaller than the preview box; **Reset view** (or `0`) puts it back as it opened, centred at 100%. Scaling never interrupts playback, and the zoom is kept while you click through the animations of one pack.
3. **Snippet (right).** Pick a **role** — Character / One-shot / UI — and a ready-to-paste `.rpy` snippet is generated for that pack. The default role is inferred from the pack's contents (an effect-only pack defaults to One-shot, for example), so you choose the role while watching the animation instead of guessing.

Exporting the snippet appends it to **`ss_snippets.txt`** in your project root and copies it to the clipboard, ready to paste straight into your script. Press **Esc** to close.

Because the browser reads through the same zero-config resolver as `SSPlayer`, anything it lists is guaranteed to load by the exact path shown — including packs the [Auto Importer](import.md) just generated, since the asset index is refreshed on import.

### Stays in sync with the Auto Importer

You do not have to relaunch to pick up a brand-new pack. Drop a new project into `SpriteStudio_Source/` and the [Auto Importer](import.md) converts it and refreshes the index on the next reload — with [hot reload](import.md#hot-reload) on (one **Shift+R** per launch) that reload happens by itself. Reopen the browser (**Shift+B**) and the new pack is in the list, ready to preview on the spot.

> [!TIP]
>
> <video autoplay loop muted playsinline width="100%">
>   <source src="assets/3-asset_browser_autoimport.webm" type="video/webm">
> </video>
> <img src="assets/3-asset_browser_autoimport.webp" width="100%" style="display: none;">
