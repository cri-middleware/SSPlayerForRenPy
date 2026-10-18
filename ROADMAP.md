# SpriteStudio Player for Ren'Py — Roadmap

This file lists unfinished work only. Technical constraints live in
[Limitations](./docs/en/limitations.md) ([日本語](./docs/ja/limitations.md)); SDK-side work lives
in the [SDK ROADMAP](https://github.com/cri-middleware/SpriteStudio-SDK/blob/HEAD/ROADMAP.md).

## Playback & rendering

These need no new SDK API — the runtime already provides everything required. Each item's
*Reference* names the sibling Players that have it, or that carry the same item.

- [ ] **Per-frame callback** — An `on_frame(player, frame_no)` constructor callback, fired once
  per processed tick after the frame's world matrices are final: the hook a game needs to drive
  its own logic off the animation clock. The attachment layer already consumes that point
  inside `render()`, so the dispatch site exists. Reference: `SSPlayerForGodot`'s
  `frame_updated` signal; `SSPlayerForWeb`'s `onFrame`.
- [ ] **Crossfade on image attributes** — `SSPlayer` exposes the runtime's track stack, but an
  image attribute still cuts: `show ringo walk` builds a new player through `_duplicate`, which
  knows nothing of the animation shown. Following Ren'Py's Live2D, `fade=` and `default_fade` on
  `SSPlayer` would crossfade from the animation shown — a selling point — which needs the
  incoming player to reach the outgoing one's runtime and to be the only path switching track 0
  on that tag. Reference: `SSPlayerForWgpu`'s Bevy integration, where `transition_ms` decides
  between a crossfade and a cut and track-0 commands are refused.

## UI integration

- [ ] **Screen-language integration** — A player is already a `Displayable`, so it drops into a
  `screen` and lays out like an image, its natural size the authored canvas and Ren'Py's `fit` /
  `xysize` / `align` placing it, but it lacks the behaviour of a control. This is the Ren'Py
  face of the sibling ports' item (Godot's `Control` node, Unity's uGUI `Graphic`, Flutter's
  intrinsic sizing and `hitTest`), in two steps, the second building on the first.
  - [ ] **Focus mask** — Ren'Py's `focus_mask` accepts a callable, which is exactly the hook
    a per-part hit test fits: an irregular button then stops taking clicks across its
    bounding box. It needs a **part rect read-out** first — `ss_part_rect(part)`, built from
    the `PartState` fields the runtime already delivers every frame (`size_x` / `size_y`,
    `anchor`, `pivot`) plus the `ss_part_transform()` this player already has — and then
    `ss_hit_test_part(x, y)` over it.
  - [ ] **Button states** — `imagebutton` takes an image per state; a player takes none. Map
    `idle` / `hover` / `selected_idle` / `selected_hover` / `insensitive` onto an animation or
    a label so a player can back a `button` without the screen re-issuing `ss_set_animation`
    on every hover.

## Needs SDK

- [ ] **Stretch a NineSlice part to a screen's box** — The runtime evaluates a NineSlice
  part's size from keyframes and hands over finished vertices, and the Override Layer covers
  colour / cell / visibility only, so nothing can size the part to the box a screen gives it.
  Waits for: Per-part size override.

## Backlog

- [ ] **Flip and offset** — Mirror and shift the drawn animation without moving the host object;
  low priority, because `at Transform(xzoom=-1.0)` / `at Transform(xoffset=…)` covers the common
  case and only falls short at leaving objects pinned to parts un-mirrored, since attachments
  composite inside the player's own output. The root transform has to reach `part_transform()`
  as well as the geometry, with the mirror carried on the **Y** axis as the sibling ports do
  (*Mirrored parts* in the usage guide). Reference: `SSPlayerForGodot` (`flip_h` / `flip_v` /
  `offset`); `SSPlayerForUnity` (`FlipX` / `FlipY` / `Offset`); `SSPlayerForWeb` (`flipX` /
  `flipY` / `offsetX` / `offsetY`).
- [ ] **Per-emotion talk in `SSCharacter`** — While a line is spoken, `talk` replaces the
  attribute the sprite was showing, so a `happy` character talks with the one talk animation;
  `talk` could also take a mapping from that attribute to the animation to talk with
  (`talk={"happy": "joy_talk", None: "talk"}`). Not started until a pack authors a talk
  animation per emotion, since Ringo has none to check an implementation against.
- [ ] **Text parts** — Not drawn. Text is one of the two part kinds authored for UI and settled
  SDK-side as a **player responsibility**, so drawing it, and substituting the string at runtime
  for a localized label, is this side's work with no SDK roadmap entry.
- [ ] **NineSlice parts** — Not drawn. The runtime hands over finished vertices, so this is a
  Player-side draw path; the SDK roadmap has no entry for it.
- [ ] **Timeline events of Instance / Effect parts** — Only the root animation's UserData /
  Signal / Audio events are surfaced. The SDK roadmap has no entry for them.
- [ ] **Built into Ren'Py** — SpriteStudio support that ships with Ren'Py, as Live2D's does, so a
  project plays `.ssab` without `spritestudio/` copied into its `game/`. A wish, not scheduled: it
  rests on Ren'Py's maintainers taking it in, and on Ren'Py's own build producing the native cores
  for every platform it targets. Being BSD-3-Clause, the cores could come inside the Ren'Py SDK
  rather than as a separate download installed through the launcher, which is how the Cubism SDK
  arrives.
