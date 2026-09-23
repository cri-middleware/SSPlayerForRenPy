# SpriteStudio Player for Ren'Py — Player Roadmap

This is the **Ren'Py Player** roadmap for SSPlayerForRenPy. It tracks Ren'Py-specific
implementation tasks for capabilities exposed by the Rust runtime / converter
([`SpriteStudio-SDK/ROADMAP.md`](./SpriteStudio-SDK/ROADMAP.md)).

For what the player deliberately does *not* support, see
[Limitations](./docs/en/limitations.md) ([日本語](./docs/ja/limitations.md)) — that page is
the user-facing list; this one is the development plan.

## Design principle — Ren'Py-native integration

`SSPlayer` is a `renpy.Displayable`, so features should fit Ren'Py's idioms rather than
recreate an engine layer inside it:

- **Use Ren'Py's own systems.** Placement and scaling belong to `Transform` / ATL and the
  `at` clause; volume belongs to the mixers; persistence belongs to the pickled displayable.
  Do not rebuild them behind an `ss_*` method.
- **Stay droppable.** Everything ships as `game/spritestudio/`, pasted into a stock project
  with no build step, so a feature must work without `scripts/`, `tools/` or the SDK
  checkout — and each sibling `.rpy` must stay independently removable.
- **Naming and style.** Public API is `ss_`-prefixed `snake_case` on the displayable;
  callbacks are constructor arguments (`on_finished`, …), matching how Ren'Py itself takes
  them. Names read as idiomatic Ren'Py rather than mirroring another port's spelling.

## Status legend

- ☐ **Ready** — player-only, no SDK dependency; can start now
- ⛔ **Blocked on SDK** — needs a `SpriteStudio-SDK/ROADMAP.md` phase first
- 🕒 **Deferred** — intentionally postponed; recorded here so it can be picked up later

---

## Player-side features

These need no new SDK API — the runtime already provides everything required. They are
listed because the [Player Porting Guide](./SpriteStudio-SDK/libs/ssruntime/docs) describes
them as player responsibilities and other official players implement them, but this one does
not yet.

### ☐ Per-frame callback

An `on_frame(player, frame_no)` constructor callback, fired once per processed tick after
the frame's world matrices are final — the hook a game needs to drive its own logic off the
animation clock.

- *Current state*: not available. The attachment layer consumes the same point internally,
  so the dispatch site already exists in `render()`.
- *Reference*: `SSPlayerForGodot`'s `frame_updated` signal; `SSPlayerForWeb`'s `onFrame`.

### ☐ Screen-language integration

A player is already a `Displayable`, so it drops into a `screen` — but it behaves like a
picture there, not like a control. Three pieces, in the order they build on each other.

- *Render size*. `render()` returns `self._size` when the constructor was given one and the
  full available `(width, height)` otherwise, so a player inside a `vbox` / `hbox` claims the
  whole area. Measure the animation's content box and return that as the natural size, with a
  `fit` (`contain` / `cover` / `none`) + `align` pair for how the animation sits in a box it
  was not authored for — the family's vocabulary, with `SSPlayerForReactNative`'s
  implementation as the reference.
- *Focus mask*. Ren'Py's `focus_mask` accepts a callable, which is exactly the hook a per-part
  hit test fits: an irregular button then stops taking clicks across its bounding box. It
  needs a **part rect read-out** first — `ss_part_rect(part)`, built from the `PartState`
  fields the runtime already delivers every frame (`size_x` / `size_y`, `anchor`, `pivot`)
  plus the `ss_part_transform()` this player already has — and then `ss_hit_test_part(x, y)`
  over it.
- *Button states*. `imagebutton` takes an image per state; a player takes none. Map
  `idle` / `hover` / `selected_idle` / `selected_hover` / `insensitive` onto an animation or a
  label so a player can back a `button` without the screen re-issuing `ss_set_animation` on
  every hover.
- *Reference*: this is the Ren'Py face of the same item the sibling ports carry — Godot's
  `Control` node, Unity's uGUI `Graphic`, Flutter's intrinsic sizing + `hitTest`.

### 🕒 Animation blending / crossfade

Layer and cross-fade animations on one player through the runtime's track stack —
`ss_runtime_set_track_animation`, `ss_runtime_crossfade`, `ss_runtime_add_track_source`,
`ss_runtime_fade_track` and the rest of the track and source calls.

- *Current state*: not available. The runtime side is complete; nothing on `SSPlayer` exposes
  it.
- *Reference*: `SSPlayerForWgpu`, the one official player that surfaces it
  (`set_track_animation` / `crossfade` / `fade_track` / …, with regression tests in
  `tests/tracks.rs`). The stems are fixed in the SDK's
  [Player API Conventions](./SpriteStudio-SDK/libs/ssruntime/docs/20_design/30_api_conventions.md)
  §3-2, and the design is its
  [Animation mixing](./SpriteStudio-SDK/libs/ssruntime/docs/50_features/10_animation_mixing.md)
  page.
- *Deferred*: until after the first release — a selling point, not a release blocker.

### 🕒 Flip and offset — *low priority*

Mirror playback horizontally / vertically, and shift the drawn animation, without moving the
host object.

- *Current state*: not available as a player knob. Ren'Py hosts mirror and shift the whole
  displayable instead — `at Transform(xzoom=-1.0)`, `at Transform(xoffset=…)` — which covers
  the common case, so this is recorded for parity rather than for a gap in what creators can
  do. What the sibling ports gain that a wrapping `Transform` does not is the ability to
  mirror the artwork while leaving objects pinned to parts un-mirrored; here, attachments are
  composited inside the player's own output, so a wrapping `Transform` flips them too.
- *Motivating problem does not apply*: on the other ports the feature exists because negating
  the host node's scale drags its children, colliders and particle systems along. `SSPlayer`
  is a plain displayable with none of those, so mirroring it disturbs nothing.
- *Reference*: `SSPlayerForGodot` (`flip_h` / `flip_v` / `offset`, folded into the root
  `CanvasItem` transform); `SSPlayerForUnity` (`FlipX` / `FlipY` / `Offset`, folded into the
  vertex positions); `SSPlayerForWeb` lists it at the same low priority.
- *If it is ever implemented*: the root transform must reach `part_transform()` as well as the
  geometry, or every attachment detaches the moment the player is flipped — this is the one
  mistake both sibling ports call out. Keep the sign convention they converged on (the mirror
  is carried on the **Y** axis), which is also what this player's `part_transform()` already
  produces; see *Mirrored parts* in the usage guide, and `30_core/40_render_loop.md` in the
  SDK docs for why the choice of axis is a convention rather than a detail.

---

## Shared with every port

Text and NineSlice parts, and nested timeline events inside Instance / Effect parts, are
exposed by the runtime but implemented by no official player yet, so they are tracked in the
SDK roadmap rather than here — see [Limitations](./docs/en/limitations.md).

Text and NineSlice are the two part kinds authored for UI, and the UI work above stops short
of both. Text is settled SDK-side as a **player responsibility**, so drawing it — and
substituting the string at runtime, which a localized UI label needs — is this side's work
whenever it is picked up. Stretching a NineSlice part to a screen's box is not: the runtime
evaluates its size from keyframes and hands over finished vertices, and the Override Layer
covers colour / cell / visibility only, so it waits on the SDK roadmap's **Per-part size
override** (Phase 3).
