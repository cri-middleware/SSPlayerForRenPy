"""Runtime routing and constants for libssruntime.

This module exposes the runtime constants and dynamically delegates SSRuntime
to either the native ctypes implementation (_NativeRuntime) or the emscripten/JS
implementation (_WebRuntime) depending on the environment.
"""

import sys

# --- enums mirrored from the C-API / schema -------------------------------

RENDER_MODE_DIRECT = 0      # pre-baked world matrices (what this Player uses)
RENDER_MODE_SCENEGRAPH = 1

COORD_Y_UP = 0
COORD_Y_DOWN = 1            # Ren'Py screen orientation

ORIGIN_CENTER = 0
ORIGIN_TOP_LEFT = 1

UNIT_PIXEL = 0
UNIT_DOT = 1

# playback_direction
DIRECTION_FORWARD = 0
DIRECTION_BACKWARD = 1

# playback_style (ss_runtime_set_playback_direction's second arg)
STYLE_NORMAL = 0
STYLE_PINGPONG = 1

# --- Override Layer (per-part runtime overrides) --------------------------
# blend_op of a part *color* override — the same four operations as the
# authored PartColor blend type.
BLEND_MIX = 0
BLEND_MUL = 1
BLEND_ADD = 2
BLEND_SUB = 3

# priority_mode: keyframe-vs-override precedence, for the attributes that
# conflict with the animation (color + cell). Visibility takes none — it is a
# plain force-hide flag that always wins and is dropped on a new animation.
# Mirrors SS6's KindIgnoreAttribute (SDK: libs/ssruntime/src/core/override_layer.rs).
PRIORITY_OVERWRITE_ON_NEXT_KEYFRAME = 0   # SS6 NON: one-shot, hands back to the keyframe
PRIORITY_HOLD_UNTIL_NEXT_ANIMATION = 1    # SS6 NOW_ANIMATION: wins for this animation
PRIORITY_PERMANENT = 2                    # SS6 PERMANENT: survives animation changes

# --- Animation mixing (the track stack) -----------------------------------
# How a track folds onto the tracks below it.
TRACK_BLEND_MIX = 0
TRACK_BLEND_ADDITIVE = 1

# Where an animation laid on a track starts: from its top, or at track 0's
# phase (the same fraction of its section).
TRACK_SYNC_FREE = 0
TRACK_SYNC_START = 1

_IS_WEB = sys.platform == "emscripten"


def hash_string(s: str) -> int:
    """fnv1a-32 of ``s`` (UTF-8) — matches the Brain's ``ss_runtime_hash_string``.

    Platform-independent: needs neither the native library (absent on web) nor
    the JS binding, and is verified byte-for-byte against the Brain's hash for
    the SS6 user-shader names. Used to key user-shader names to the draw plan's
    ``PartAttributeShader.id_hash`` on both native and web (the web build has no
    ``_SS_LIB`` to call ``ss_runtime_hash_string`` through).
    """
    h = 0x811C9DC5
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


if _IS_WEB:
    from .ssruntime_web import _WebRuntime as SSRuntime
    from .ssruntime_web import load_library
else:
    from .ssruntime_native import _NativeRuntime as SSRuntime
    from .ssruntime_native import load_library
