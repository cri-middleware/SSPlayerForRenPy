# SpriteStudio Player for Ren'Py

Plays SpriteStudio animations in Ren'Py 8. This folder goes into your project's `game/` directory as it is.

It holds the Ren'Py scripts (`*.rpy`), the Python bridge in `python/`, the native libraries in `libs/`, the licences, and the documentation in `docs/`. Neither this README nor `docs/` ends up in a game you build: `spritestudio.rpy` leaves them out of the distribution.

`docs/` is the documentation of the release this folder came from, so it describes the player these scripts and libraries actually are. The online documentation is built from the latest release and can be ahead of this copy.

## Where to look

| To find out | Read |
| --- | --- |
| Where this folder and the `.ssab` files go | [docs/setup.md](docs/setup.md) |
| How to show an animation with `show ringo wait1`, as a standing image or talking character, or in a screen | [docs/usage.md](docs/usage.md) |
| How to control playback from Python, follow or override a part, replace a texture, and react to events | [docs/usage.md](docs/usage.md), sections 4 to 8 |
| How to turn `.sspj` projects into `.ssab` | [docs/import.md](docs/import.md) |
| How to build the game for desktop, Android, iOS and the web | [docs/export.md](docs/export.md) |
| What is not supported | [docs/limitations.md](docs/limitations.md) |
| How to rebuild the native library or customise the player | [docs/build.md](docs/build.md) |

Links between the pages work offline. The screenshots and videos they refer to are not included; they are in the online documentation, <https://cri-middleware.github.io/SSPlayerForRenPy/> (Japanese: <https://cri-middleware.github.io/SSPlayerForRenPy/ja/>).

The licence is `LICENSE.md`; `THIRD_PARTY_NOTICES.md` holds the notices of the bundled libraries.
