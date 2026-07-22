# Usage Guide

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

### Basic Parameters
- **1st Argument**: The path to the `.ssab` to play (relative to `game/`, e.g. `"ss_assets/Ringo/Ringo.ssab"`). Because the `.ssab` and its textures and external instance packs live together, this is enough to resolve the related resources. **You can also load an `.ssab` from an `.rpa` archive** (via the Ren'Py loader).
- **`animation` (Optional)**: The name of the animation to play initially. If omitted, the first animation in the data is played. **If you pass a non-existent name, it will result in an error** (with a list of valid animation names) on the first display.
- **`loop` (Optional)**: Playback count. `-1` (default) for infinite loop, `1` for a single play, `N` for N plays. `0` is a synonym for `-1` (infinite), not "do not play".
- **`speed` (Optional)**: Playback speed multiplier (default `1.0`).
- **`size` (Optional)**: If you pass `(w, h)` (or a single number for a square), it acts as a **normal image of that bounding box size**, allowing `xalign`/`xpos`/`pos` and container layouts to work directly (the animation is drawn at the center of the box). If omitted, it occupies the entire screen, and you must use `xoffset`/`yoffset` for positioning. In both cases, scaling via `zoom`/`Transform` applies.

```renpy
# You can place it with align if you specify size
add SSPlayer("ss_assets/Ringo/Ringo.ssab", size=(400, 600)) xalign 0.5 yalign 1.0
```

> [!TIP]
> Not sure which pack or animation to use? Open the **Asset Browser** with **Shift+B** in developer mode to browse every `.ssab`, preview animations live, and copy a ready-to-paste snippet. See the **Asset Browser** section (§8) below.

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
    # Show default standing image (idle motion)
    show ringo idle:
        yoffset 200

    r happy "The motion switches just by changing the attribute!"

    # Make them walk by combining with Transform
    show ringo walk:
        xoffset -400 yoffset 200
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
- You can also pass `aliases=` (for emotions, etc.) and `size=` (box size for `xalign`).
- The lip-sync start/stop timing can be adjusted using `start` / `stop` (Character callback event names).

> [!WARNING]
> **v1 Limitation**: Because talk/idle replace attributes while speaking, emotion attributes like `show ringo happy` won't reflect during `talk`, and it will return to `idle` afterwards (emotion-specific talks will be supported in the future).

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
    # Show the effect at a specific position matching the attack
    show hit_effect:
        xoffset -150 yoffset 50
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
$ current_anim = player.ss_get_animation()

# Switch to an arbitrary animation (load + cue -> play)
$ player.ss_play("run")
```

- **Separation of Loading and Playback**: `ss_set_animation("run")` only loads and cues the animation; it does not start playing. `ss_play()` starts the playback.
- **Playback Control**: `ss_pause()` / `ss_resume()` / `ss_stop()`, frame control `ss_set_frame()` / `ss_get_frame()`, speed `ss_set_speed()`, and looping `ss_set_loop()` are available.
- **Part Query**: `ss_part_transform("part_name")` retrieves the local transform (x/y/rotation/scale) of the part for the most recent frame.

---

## 5. Part Overrides (Part Color / Cell / Visibility)

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
| `ss_part_index(part_name)` | Part index, or `-1` if the part is not in the asset |
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

> **On using part indices**: Part indices are stable within one asset (the same `.ssab`), so if you set overrides frequently, resolve the name once with `ss_part_index()` and reuse that index.

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

---

## 6. Handling Animation Events (User Data / Signals)
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
    on_finished=my_finish_handler
)
```

**Available Callback Arguments:**
- `on_user_data`: Called when User Data is reached
- `on_signal`: Called when a Signal is reached
- `on_audio`: Called when an audio playback specified frame is reached
- `on_finished`: Called once every configured `loop` has played. Never fires under an infinite loop, nor on a commanded stop
- `on_looped`: Called each time a loop iteration completes; the final iteration fires `on_finished` instead
- `on_started`: Called when animation playback starts

> [!NOTE]
> Callbacks are invoked from the drawing thread in the form `cb(player, ...)` (start/finish/loop forms are `cb(player)`). To support pickling during rollback, please pass module-level functions rather than lambdas or local functions.

*Note: For polling-based retrieval (`ss_poll_events()`), refer to implementations like `ss_drain_events()` inside `script.rpy` of the demo project.*

---

## 7. Utilities

### One-Shot Playback Made Easy (`ss_play_once`)
Plays any `.ssab` once (effect or full-screen cutscene). With `wait=True`, it waits until playback finishes and automatically disappears; hide a non-waiting one with `ss_hide_once(tag)`.
```renpy
$ ss_play_once("ss_assets/ParticleEffect/e038.ssab", "hit",
               at=Transform(xpos=640, ypos=360), wait=True)
```
`ss_duration("…/Ringo.ssab", "attack1")` returns the duration in seconds for one cycle of that animation, so a character's "play and wait" can be written as `show ringo attack` + `$ renpy.pause(ss_duration(...))`.

### Attaching Something to a Part (`attachments`)
Make a displayable follow a named part (like a hand or head). Note: v1 only supports translation.
```renpy
image ringo = SSPlayer(
    "ss_assets/Ringo/Ringo.ssab",
    attachments={"head": Text("! ", size=40), "hand_r": "sword.png"},
)
```

### Checking Behavior (Diagnostics)
In developer mode, "runtime loaded / N pack(s)" is output to the log on startup. By calling `ss_diagnostics()` in the console (Shift+O), you can check the runtime status and a list of detected packs. If an `.ssab` cannot be read, you will get a clear error containing its path (relative to `game/`).

---

## 8. Asset Browser (Shift+B): Discover, Preview, and Copy Snippets

Press **Shift+B** in developer mode to open the **Asset Browser** — a built-in inspector that turns "which pack do I play, and how?" into a two-click answer. It is developer-mode only (the hotkey is disabled in release builds) and overlays the running game, so you can call it up at any time.

> [!TIP]
>
> <video autoplay loop muted playsinline width="100%">
>   <source src="../assets/2-asset_browser.webm" type="video/webm">
> </video>
> <img src="../assets/2-asset_browser.webp" width="100%" style="display: none;">

The window has three panes:

1. **Pack list (left).** Every `.ssab` the resolver can find under `ss_assets/` — including packs bundled inside an `.rpa` archive. Click one to select it.
2. **Live preview (center).** The selected animation plays for real (not a static thumbnail), alongside a metadata line — number of `animations`, `fps`, whether it has `effects`, and any external instance packs. Click any animation in the list to preview it instantly.
3. **Snippet (right).** Pick a **role** — Character / One-shot / UI — and a ready-to-paste `.rpy` snippet is generated for that pack. The default role is inferred from the pack's contents (an effect-only pack defaults to One-shot, for example), so you choose the role while watching the animation instead of guessing.

Exporting the snippet appends it to **`ss_snippets.txt`** in your project root and copies it to the clipboard, ready to paste straight into your script. Press **Esc** to close.

Because the browser reads through the same zero-config resolver as `SSPlayer`, anything it lists is guaranteed to load by the exact path shown — including packs the [Auto Importer](import.md) just generated, since the asset index is refreshed on import.

### Stays in sync with the Auto Importer

You do not have to relaunch to pick up a brand-new pack. Drop a new project into `SpriteStudio_Source/`, press **Shift+R** to reload, and the [Auto Importer](import.md) converts it and refreshes the index — reopen the browser (**Shift+B**) and the new pack is in the list, ready to preview on the spot.

> [!TIP]
>
> <video autoplay loop muted playsinline width="100%">
>   <source src="../assets/3-asset_browser_autoimport.webm" type="video/webm">
> </video>
> <img src="../assets/3-asset_browser_autoimport.webp" width="100%" style="display: none;">
