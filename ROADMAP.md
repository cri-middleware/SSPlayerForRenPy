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
- [ ] **Crossfade on image attributes** — `SSPlayer` exposes the runtime's track stack
  (`ss_crossfade`, `ss_set_track_animation`, …), but an image attribute still cuts: `show ringo
  walk` builds a new player through `_duplicate`, which knows nothing of the animation shown. Follow
  Ren'Py's Live2D: `fade=` and `default_fade` on `SSPlayer`, so that `show ringo walk` crossfades
  from the animation shown instead of cutting to it. The incoming player has to reach the outgoing
  one's runtime (Live2D keeps its motion state per image tag), and that path has to be the only
  one switching track 0 on that tag, or an `ss_crossfade` and an attribute fight over it. A
  selling point. Reference: `SSPlayerForWgpu`'s Bevy integration, where `transition_ms` on the
  component decides between a crossfade and a cut, and track-0 commands are refused.

## UI integration

- [ ] **Screen-language integration** — A player is already a `Displayable`, so it drops into
  a `screen` and lays out there like an image: its natural size is the authored canvas, and
  Ren'Py's own `fit` / `xysize` / `align` place it in a box it was not authored for. What it
  lacks is the behaviour of a control. This is the Ren'Py face of the item the sibling ports
  carry — Godot's `Control` node, Unity's uGUI `Graphic`, Flutter's intrinsic sizing +
  `hitTest`. Two steps, the second building on the first.
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
  Waits for: Per-part size override (Phase 3).

## Backlog

- [ ] **Flip and offset** — Mirror playback horizontally / vertically, and shift the drawn
  animation, without moving the host object. Low priority: Ren'Py hosts already mirror and
  shift the whole displayable with `at Transform(xzoom=-1.0)` / `at Transform(xoffset=…)`,
  which covers the common case, and `SSPlayer` has none of the children, colliders or
  particle systems that make negating a host's scale a problem on the other ports. What a
  wrapping `Transform` cannot do is mirror the artwork while leaving objects pinned to parts
  un-mirrored, because attachments are composited inside the player's own output. Reference:
  `SSPlayerForGodot` (`flip_h` / `flip_v` / `offset`, folded into the root `CanvasItem`
  transform); `SSPlayerForUnity` (`FlipX` / `FlipY` / `Offset`, folded into the vertex
  positions); `SSPlayerForWeb` (`flipX` / `flipY` / `offsetX` / `offsetY`, on every Web
  player). If it is implemented, the root transform must reach `part_transform()` as well as
  the geometry, or every attachment detaches the moment the player is flipped — the one
  mistake both sibling ports call out. Keep the sign convention they converged on (the mirror
  is carried on the **Y** axis), which is also what this player's `part_transform()` already
  produces; see *Mirrored parts* in the usage guide, and the SDK's
  [render loop](https://github.com/cri-middleware/SpriteStudio-SDK/blob/HEAD/libs/ssruntime/docs/30_core/40_render_loop.md)
  page for why the choice of axis is a convention rather than a detail.
- [ ] **Per-emotion talk in `SSCharacter`** — While a line is spoken, `talk` replaces the
  attribute the sprite was showing, so a `happy` character talks with the one talk animation
  and turns happy again only when the line ends. Let `talk` also take a mapping from that
  attribute to the animation to talk with — `talk={"happy": "joy_talk", None: "talk"}` — so
  the mapping is the only new vocabulary. Not started until there is a pack that authors a
  talk animation per emotion: Ringo has no talk animation at all, so nothing could check an
  implementation. The case is a creator who needs it, not parity — no other port has a say
  statement to hook.
- [ ] **Text parts** — Not drawn. Text is one of the two part kinds authored for UI, and it is
  settled SDK-side as a **player responsibility**, so drawing it — and substituting the string
  at runtime, which a localized UI label needs — is this side's work. The SDK roadmap has no
  entry for it.
- [ ] **NineSlice parts** — Not drawn. The runtime hands over finished vertices, so this is a
  Player-side draw path; the SDK roadmap has no entry for it.
- [ ] **Timeline events of Instance / Effect parts** — Only the root animation's UserData /
  Signal / Audio events are surfaced. The SDK roadmap has no entry for them.
