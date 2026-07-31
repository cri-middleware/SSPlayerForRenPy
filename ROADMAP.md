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

### ☐ Run-time texture swap

Replace the texture bound to a cell map from game code, without touching the `.ssab`
(costume changes, dynamic expressions). The porting guide's *External resources and
textures* names this as the player's job, and it is distinct from the Override Layer API
(`ss_set_part_cell_override` swaps a **cell**, not the texture behind it).

- *Current state*: not available. Textures are resolved once, at load, through
  `RenPyResourceManager`.
- *Reference*: `SSPlayerForGodot`'s `set_cellmap_texture` / `get_cellmap_texture`;
  `SSPlayerForWeb` carries the same item on its roadmap.
- *Target*: a name-keyed pair on the displayable where passing `None` restores the original
  from the `.ssab` definition — looking in `cellmaps` and then `external_textures`, both of
  which `SsabMeta.texture_hash_map()` already indexes.

### ☐ Per-frame callback

An `on_frame(player, frame_no)` constructor callback, fired once per processed tick after
the frame's world matrices are final — the hook a game needs to drive its own logic off the
animation clock.

- *Current state*: not available. The attachment layer consumes the same point internally,
  so the dispatch site already exists in `render()`.
- *Reference*: `SSPlayerForGodot`'s `frame_updated` signal; `SSPlayerForWeb`'s `onFrame`.

### 🕒 Flip (`flip_h` / `flip_v`) — *low priority*

Mirror playback horizontally / vertically.

- *Current state*: not available as a player knob. Ren'Py hosts mirror the whole displayable
  instead — `at Transform(xzoom=-1.0)` — which covers the common case, so this is recorded
  for parity rather than for a gap in what creators can do.
- *Reference*: available on `SSPlayerForGodot` (`set_flip_h` / `set_flip_v`);
  `SSPlayerForWeb` lists it at the same low priority.

---

## Shared with every port

Animation blending / crossfade (`ss_runtime_crossfade`, the blend-source API) is exposed by
the runtime but implemented by no official player yet, so it is tracked in the SDK roadmap
rather than here. The same applies to Text and NineSlice parts, and to nested timeline
events inside Instance / Effect parts — see [Limitations](./docs/en/limitations.md).
