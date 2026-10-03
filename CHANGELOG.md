# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and the version is the `ss_renpy` package version
(`game/spritestudio/python/ss_renpy/__init__.py`, [PEP 440](https://peps.python.org/pep-0440/),
e.g. `7.0.0b1`).

## [7.0.0b1] - Unreleased

### Added
- Initial public release: `SSPlayer` displayable for SpriteStudio playback in
  Ren'Py, auto importer, asset browser, `SSCharacter` talking sprites, and
  desktop / Android / iOS / Web export support.
- Per-part **Override Layer**: colour, cell and visibility overrides that win
  over the keyframes (`ss_set_part_color_override` /
  `ss_set_part_cell_override` / `ss_set_part_visibility_override`, their
  `ss_clear_*` counterparts, and `ss_clear_all_part_overrides`), plus
  `ss_cellmap_names` / `ss_cell_names` to discover cell-override targets.
  Overrides are restored when a saved game is loaded (one-shot
  `OverwriteOnNextKeyframe` overrides excepted, being momentary by design).
