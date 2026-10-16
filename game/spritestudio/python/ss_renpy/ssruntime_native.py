"""ctypes bindings for libssruntime ("Brain").

This is the FFI layer of the Ren'Py SSPlayer. It is intentionally free of any
``renpy`` import so it can be exercised from plain CPython (the M0 smoke test)
as well as from inside Ren'Py's bundled interpreter (M1+).

Signatures are transcribed from the generated C header
``libs/ssruntime/target/ssruntime.h`` into the ``_REQUIRED`` table — that
header is the source of truth; keep the table in sync with it.
:func:`load_library` refuses a library missing anything in ``_REQUIRED``, with
one error naming what is missing, rather than letting ctypes fail on the first.

Lifetime rules:
  * The runtime ref-counts the ``resource`` with ``Arc``, so the resource and
    its contexts may be destroyed in either order. What must stay alive is the
    ssab bytes behind a *borrowed* resource, until the resource and every
    context bound to it are gone. We keep the Python wrapper conservative:
    ``close()`` destroys the context first, then the resource.
  * SoA buffers (world matrices, local vertices, ...) are only valid until the
    next Brain call. Never retain the raw pointers across frames; copy out
    (or build a numpy view and consume it) within the same frame.
  * The FrameData / EffectDrawPlan FlatBuffers can be consumed two ways:
    ``get_frame_data``/``effect_slot_step`` copy them into owned ``bytes`` (safe
    to retain), while ``get_frame_data_view``/``effect_slot_step_view`` return a
    zero-copy read-only ``memoryview`` over the Brain's own buffer. The view is
    the hot path (it mirrors SSPlayerForUnity's zero-copy ``ByteBuffer`` over the
    native pointer): it is valid only until the next invalidating Brain call on
    the same context/slot, so parse + materialize the geometry before then and
    never stash the view across frames. ``get_frame_data`` is per-context — a
    *child* runtime's call writes a different buffer and does not invalidate the
    parent's (so the recursive instance walk is safe).
  * The ``.ssab`` resource is created with ``ss_resource_create_borrow`` by
    default: the Brain reads from our ``bytes`` for the resource's whole life, so
    we keep an owned, immutable reference alive (CPython never relocates a
    ``bytes`` object — that reference is the equivalent of Unity's
    ``GCHandle.Pinned``) and tear the resource down before dropping it.
"""

from __future__ import annotations

import ctypes as C
import os
import platform
import sys

from ss.format.SsAnimeBinary import SsAnimeBinary

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

# Override Layer: color blend_op and the color/cell priority_mode (visibility
# takes no priority). Kept in step with the same names in ss_renpy.ssruntime.
BLEND_MIX = 0
BLEND_MUL = 1
BLEND_ADD = 2
BLEND_SUB = 3

PRIORITY_OVERWRITE_ON_NEXT_KEYFRAME = 0
PRIORITY_HOLD_UNTIL_NEXT_ANIMATION = 1
PRIORITY_PERMANENT = 2

# Animation mixing: the track blend and sync values (kept in step with the
# same names in ss_renpy.ssruntime), and the C-API's "no handle" sentinel.
TRACK_BLEND_MIX = 0
TRACK_BLEND_ADDITIVE = 1
TRACK_SYNC_FREE = 0
TRACK_SYNC_START = 1
INVALID_HANDLE = 0xFFFFFFFF


# --- by-value structs for the Instance / Effect slot API ------------------
# These mirror the C structs in ``target/ssruntime.h`` *exactly* (field order
# and width). They are passed/returned BY VALUE across the FFI, so the layout
# must match; ctypes' natural alignment matches the runtime's ``#[repr(C)]``.

class ss_effect_step_result(C.Structure):
    """Return of ``ss_effect_slot_step`` (see ``ss_effect_step_result`` in the
    generated ssruntime.h).

    ``draw_plan_buf`` is a FlatBuffers ``EffectDrawPlan`` valid only until the
    next step on the same slot — copy it out immediately.
    """
    _fields_ = [
        ("visible", C.c_bool),
        ("draw_plan_buf", C.POINTER(C.c_uint8)),
        ("draw_plan_len", C.c_size_t),   # uintptr_t
    ]


class ss_effect_event_info(C.Structure):
    """Resolved per-slot Effect event (see ``ss_effect_event_info`` in the
    generated ssruntime.h)."""
    _fields_ = [
        ("event_frame", C.c_int32),
        ("start_time", C.c_int32),
        ("speed", C.c_float),
        ("independent", C.c_bool),
        ("is_synthetic_default", C.c_bool),
    ]


class ss_instance_step_result(C.Structure):
    """Return of ``ss_instance_slot_step`` (see ``ss_instance_step_result`` in
    the generated ssruntime.h).

    ``child_frame_no`` is a raw float (sub-frame precise) — write it back
    verbatim; never floor/round it for state.
    """
    _fields_ = [
        ("visible", C.c_bool),
        ("transitioned", C.c_bool),
        ("independent", C.c_bool),
        ("child_frame_no", C.c_float),
        ("child_looped", C.c_bool),
    ]


class ss_event_instance_info(C.Structure):
    """Resolved per-slot Instance event (see ``ss_event_instance_info`` in the
    generated ssruntime.h)."""
    _fields_ = [
        ("event_frame", C.c_int32),
        ("start_label_hash", C.c_uint32),
        ("start_offset", C.c_int32),
        ("end_label_hash", C.c_uint32),
        ("end_offset", C.c_int32),
        ("loop_num", C.c_int32),
        ("speed", C.c_float),
        ("independent", C.c_bool),
        ("reverse", C.c_bool),
        ("pingpong", C.c_bool),
        ("is_synthetic_default", C.c_bool),
    ]


def _arch_token() -> str:
    """Normalise ``platform.machine()`` to the arch tokens the SDK release layout
    uses: ``x86_64`` / ``arm64`` / ``arm32`` (else the raw machine string)."""
    m = platform.machine().lower()
    if m in ("x86_64", "amd64", "x64"):
        return "x86_64"
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m.startswith("armv7") or m.startswith("armv8l") \
            or m in ("arm", "armeabi", "armeabi-v7a"):
        return "arm32"
    return m or "unknown"


def _android_abi() -> str:
    """NDK / jniLibs ABI name for the host arch.

    The ``android/`` layout under ``libs`` uses the Android ABI names
    (``arm64-v8a`` / ``armeabi-v7a`` / ``x86_64``): the Android Brain ships in
    the APK's ``lib/<abi>/`` (jniLibs) and is loaded by soname (see
    :func:`load_library`), so mirroring the jniLibs names keeps staging a
    straight copy."""
    return {
        "arm64": "arm64-v8a",
        "arm32": "armeabi-v7a",
        "x86_64": "x86_64",
    }.get(_arch_token(), _arch_token())


def _is_android() -> bool:
    """True on Android, where ``sys.platform`` is otherwise ``"linux"``.

    Detected via the Android-only API added in CPython 3.7, with an env fallback
    the OS always sets — so Android routes to ``android/<abi>`` rather than the
    generic ``linux/<arch>``."""
    if hasattr(sys, "getandroidapilevel"):
        return True
    return bool(os.environ.get("ANDROID_ROOT") and os.environ.get("ANDROID_DATA"))


def _is_ios() -> bool:
    """True on iOS. Modern CPython reports ``sys.platform == "ios"``; some hosts
    still report ``"darwin"``, so an explicit ``SS_IOS`` env marker also counts."""
    return sys.platform == "ios" or bool(os.environ.get("SS_IOS"))

def platform_subdir() -> str:
    """Per-platform/arch subdirectory under the ``libs`` dir.

    Matches the layout produced by the SDK release workflow
    (``SpriteStudio-SDK/.github/workflows/release.yml``, ``package`` job → the
    dynamic-libs package), so a bundled release drop resolves without renaming:

        macos/                          (universal libssruntime.framework; no arch split)
        windows/{x86_64,arm64}          (ssruntime.dll)
        linux/{x86_64,aarch64}          (libssruntime.so)
        android/{arm64-v8a,armeabi-v7a,x86_64}    (libssruntime.so)
        ios/                            (libssruntime.xcframework — see load_library)
        web/                            (wasm — not loadable via ctypes)

    NOTE Android must be checked before the generic Linux branch: its
    ``sys.platform`` is also ``"linux"``, but its ``.so`` lives under
    ``android/<abi>`` (abi ∈ arm64-v8a / armeabi-v7a / x86_64 — the NDK/jniLibs
    names), not ``linux/<arch>``.

    64-bit ARM is ``linux/aarch64`` but ``windows/arm64`` — the release's own
    directory names — and ``spritestudio.rpy`` classifies ``linux/aarch64`` into
    the ``linux_arm`` package, so the Linux spelling cannot be normalised away.
    """
    arch = _arch_token()
    if _is_android():
        return os.path.join("android", _android_abi())
    if _is_ios():
        return "ios"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return os.path.join("windows", arch)
    return os.path.join("linux", "aarch64" if arch == "arm64" else arch)


def library_filename() -> str:
    """Loadable native-library path for the host, relative to its platform subdir.

    Usually a bare filename (matches the release dynamic libs), but on macOS the
    Brain ships as a versioned ``libssruntime.framework`` bundle, so this returns
    the bundle-relative path to the Mach-O binary inside it — ctypes dlopens that
    file directly by path.
    """
    if sys.platform.startswith("win"):
        return "ssruntime.dll"
    if sys.platform == "darwin" and not _is_ios():
        # Point at the real binary under Versions/A, NOT the top-level
        # ``libssruntime`` symlink, so it resolves even if the bundle's version
        # symlinks don't survive Ren'Py's .app packaging. dlopen by absolute path
        # ignores the framework's @rpath install_name, so no rpath setup needed.
        return os.path.join("libssruntime.framework", "Versions", "A", "libssruntime")
    # Linux and Android ship ``libssruntime.so``; iOS ships an ``.xcframework``
    # that is normally static-linked into the app (handled in load_library).
    return "libssruntime.so"


def default_library_path(base_dir: str | None = None) -> str:
    """Resolve the native library under ``base_dir``.

    Prefers the per-platform/arch layout ``<base_dir>/<platform_subdir>/<name>``
    (multi-platform distribution); falls back to a flat ``<base_dir>/<name>``
    (single-platform / dev). ``base_dir`` defaults to the ``libs`` folder next
    to this package (``<root>/libs``). Inside Ren'Py, pass the library's
    ``libs`` dir as ``base_dir``.
    """
    if base_dir is None:
        # package is at <root>/python/ss_renpy; libs is at <root>/libs
        base_dir = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "libs")
    name = library_filename()
    layered = os.path.join(base_dir, platform_subdir(), name)
    if os.path.exists(layered):
        return os.path.normpath(layered)
    flat = os.path.join(base_dir, name)
    if os.path.exists(flat):
        return os.path.normpath(flat)
    return os.path.normpath(layered)  # neither exists: report expected path


# Keep the CFUNCTYPE trampoline alive for the process lifetime; ctypes does not
# hold a reference and the callback would otherwise be collected.
_LOG_CB_TYPE = C.CFUNCTYPE(None, C.c_int, C.c_char_p)
_log_cb_ref = None


# --- the C ABI this module binds -------------------------------------------
# One ``(name, argtypes, restype)`` row per export, transcribed from the
# generated ssruntime.h. ``_REQUIRED`` is what :func:`load_library` checks
# before it binds anything. A library missing a row cannot run this player,
# and unchecked it fails in ctypes' words instead — a bare ``AttributeError``
# from ``dlsym`` that names one symbol and says nothing of why — or, for a
# symbol only a later call reaches, in the middle of a game.
#
# A new export goes in here too. A wrapper that answered for a library
# without it would keep that library playing with one feature quietly gone,
# where the load would have said which file is out of date.
#
# Nothing is bound that nothing calls: each row is one more way for the load
# to fail.
_P = C.c_void_p
_u8, _u32, _i32, _f32, _b = C.c_uint8, C.c_uint32, C.c_int32, C.c_float, C.c_bool
_str, _size = C.c_char_p, C.c_size_t
_FLOAT_SOA = [_P, C.POINTER(C.POINTER(C.c_float)), C.POINTER(_size)]
_I32_SOA = [_P, C.POINTER(C.POINTER(C.c_int32)), C.POINTER(_size)]
_U32_SOA = [_P, C.POINTER(C.POINTER(C.c_uint32)), C.POINTER(_size)]

_REQUIRED = (
    ("ss_runtime_set_log_callback", [_LOG_CB_TYPE], None),

    # resource lifecycle, and the .ssab schema version this runtime reads
    ("ss_resource_create_copy", [_str, _size], _P),
    ("ss_resource_create_borrow", [_str, _size], _P),
    ("ss_resource_destroy", [_P], None),
    ("ss_runtime_ssab_schema_version", [], _u32),

    # context lifecycle and animation selection
    ("ss_runtime_create", [], _P),
    ("ss_runtime_destroy", [_P], None),
    ("ss_runtime_bind_resource", [_P, _P], _b),
    ("ss_runtime_setup_animation", [_P, _str], _b),

    # render/coordinate configuration
    ("ss_runtime_set_render_mode", [_P, _u8], None),
    ("ss_runtime_set_coordinate_system", [_P, _i32], None),
    ("ss_runtime_set_origin", [_P, _i32], None),
    ("ss_runtime_set_unit", [_P, _i32], None),

    # frame data (FlatBuffers) + SoA getters
    ("ss_runtime_get_frame_data",
     [_P, _f32, C.POINTER(C.POINTER(C.c_ubyte)), C.POINTER(_size)], None),
    ("ss_runtime_get_world_matrices", _FLOAT_SOA, None),
    ("ss_runtime_get_local_uvs", _FLOAT_SOA, None),
    ("ss_runtime_get_cell_meta", _FLOAT_SOA, None),
    ("ss_runtime_get_local_vertices", _FLOAT_SOA, None),
    ("ss_runtime_get_shape_vertices", _FLOAT_SOA, None),
    ("ss_runtime_get_shape_vertex_box_coords", _FLOAT_SOA, None),
    ("ss_runtime_get_mesh_vertices_x", _FLOAT_SOA, None),
    ("ss_runtime_get_mesh_vertices_y", _FLOAT_SOA, None),
    ("ss_runtime_get_mesh_uvs", _FLOAT_SOA, None),
    ("ss_runtime_get_shape_vertex_counts", _I32_SOA, None),
    ("ss_runtime_get_mesh_indices", _I32_SOA, None),
    ("ss_runtime_get_mesh_vertex_offsets", _U32_SOA, None),
    ("ss_runtime_get_mesh_index_offsets", _U32_SOA, None),

    # playback control
    ("ss_runtime_update", [_P, _f32], _f32),
    ("ss_runtime_play", [_P], None),
    ("ss_runtime_play_with_start_frame", [_P, _f32], None),
    ("ss_runtime_pause", [_P], None),
    ("ss_runtime_resume", [_P], None),
    ("ss_runtime_stop", [_P], None),
    ("ss_runtime_set_frame_no", [_P, _f32], None),
    ("ss_runtime_set_loop_count", [_P, C.c_int], None),
    ("ss_runtime_set_frame_rate", [_P, C.c_int], None),
    ("ss_runtime_set_speed_scale", [_P, _f32], None),
    ("ss_runtime_set_playback_direction", [_P, C.c_int, C.c_int], None),
    ("ss_runtime_set_animation_section", [_P, C.c_int, C.c_int], None),
    ("ss_runtime_set_skip_frames", [_P, _b], None),

    # state getters. ss_runtime_is_finished is "every configured loop has
    # played": sticky, cleared by the next play/setup, never raised by stop().
    # ss_runtime_is_playing_forward is the effective direction (the Backward
    # setting and the ping-pong leg; a speed sign stops rather than reverses).
    ("ss_runtime_get_frame_no", [_P], _f32),
    ("ss_runtime_get_speed_scale", [_P], _f32),
    ("ss_runtime_just_looped", [_P], _b),
    ("ss_runtime_is_playing", [_P], _b),
    ("ss_runtime_is_pausing", [_P], _b),
    ("ss_runtime_is_clock_playing", [_P], _b),
    ("ss_runtime_is_clock_pausing", [_P], _b),
    ("ss_runtime_is_stack_in_motion", [_P], _b),
    ("ss_runtime_is_finished", [_P], _b),
    ("ss_runtime_is_playing_forward", [_P], _b),
    ("ss_runtime_get_start_frame", [_P], _i32),
    ("ss_runtime_get_end_frame", [_P], _i32),
    ("ss_runtime_get_frame_rate", [_P], _i32),
    ("ss_runtime_get_remaining_loops", [_P], _i32),
    ("ss_runtime_get_playback_direction", [_P], _i32),
    ("ss_runtime_get_playback_style", [_P], _i32),
    ("ss_runtime_get_skip_frames", [_P], _b),

    # events
    ("ss_runtime_get_passed_event_count", [_P], _i32),
    ("ss_runtime_get_passed_event_index", [_P, _i32], _i32),
    ("ss_runtime_get_passed_event_source_handle", [_P, _i32], _u32),

    # animation mixing: the track stack and its sources
    ("ss_runtime_set_track_animation", [_P, _u32, _str], _b),
    ("ss_runtime_get_track_count", [_P], _u32),
    ("ss_runtime_clear_track", [_P, _u32], _b),
    ("ss_runtime_set_track_alpha", [_P, _u32, _f32], _b),
    ("ss_runtime_get_track_alpha", [_P, _u32], _f32),
    ("ss_runtime_set_track_blend", [_P, _u32, _u32], _b),
    ("ss_runtime_get_track_blend", [_P, _u32], _u32),
    ("ss_runtime_set_track_sync", [_P, _u32, _u32], _b),
    ("ss_runtime_get_track_sync", [_P, _u32], _u32),
    ("ss_runtime_set_track_frame", [_P, _u32, _f32], _b),
    ("ss_runtime_get_track_frame", [_P, _u32], _f32),
    ("ss_runtime_set_track_speed", [_P, _u32, _f32], _b),
    ("ss_runtime_get_track_speed", [_P, _u32], _f32),
    ("ss_runtime_set_track_frame_rate", [_P, _u32, C.c_int], _b),
    ("ss_runtime_get_track_frame_rate", [_P, _u32], _i32),
    ("ss_runtime_set_track_skip_frames", [_P, _u32, _b], _b),
    ("ss_runtime_get_track_skip_frames", [_P, _u32], _b),
    ("ss_runtime_set_track_playback_direction", [_P, _u32, C.c_int, C.c_int], _b),
    ("ss_runtime_get_track_playback_direction", [_P, _u32], _i32),
    ("ss_runtime_get_track_playback_style", [_P, _u32], _i32),
    ("ss_runtime_set_track_loop_count", [_P, _u32, C.c_int], _b),
    ("ss_runtime_get_track_loop_count", [_P, _u32], _i32),
    ("ss_runtime_is_track_finished", [_P, _u32], _b),
    ("ss_runtime_track_just_looped", [_P, _u32], _b),
    ("ss_runtime_set_track_outgoing_event_threshold", [_P, _u32, _f32], _b),
    ("ss_runtime_get_track_outgoing_event_threshold", [_P, _u32], _f32),
    ("ss_runtime_crossfade", [_P, _u32, _str, _f32], _b),
    ("ss_runtime_fade_track", [_P, _u32, _f32, _f32], _b),
    ("ss_runtime_get_track_fade_progress", [_P, _u32], _f32),
    ("ss_runtime_cancel_track_fade", [_P, _u32], _b),
    ("ss_runtime_get_track_main_source", [_P, _u32], _u32),
    ("ss_runtime_add_track_source", [_P, _u32, _str, _f32], _u32),
    ("ss_runtime_set_source_weight", [_P, _u32, _f32], _b),
    ("ss_runtime_get_source_weight", [_P, _u32], _f32),
    ("ss_runtime_set_source_frame", [_P, _u32, _f32], _b),
    ("ss_runtime_get_source_frame", [_P, _u32], _f32),
    ("ss_runtime_set_source_event_threshold", [_P, _u32, _f32], _b),
    ("ss_runtime_get_source_event_threshold", [_P, _u32], _f32),
    ("ss_runtime_get_source_animation_index", [_P, _u32], _i32),

    # hashing helper (texture/animation name -> u32 fnv1a)
    ("ss_runtime_hash_string", [_str], _u32),

    # Override Layer: Color / Cell / Visibility, applied by the Brain on the
    # *resolved* pose so an override wins over both the keyframe and any
    # blend. Parts are addressed by the positional part index.
    ("ss_runtime_find_part_index", [_P, _str], _i32),
    ("ss_runtime_set_part_visibility_override",
     [_P, _u32, C.c_ubyte, C.c_ubyte], _b),
    ("ss_runtime_clear_part_visibility_override", [_P, _u32], _b),
    ("ss_runtime_set_part_color_override",
     [_P, _u32, C.c_ubyte, _u32, C.c_ubyte], _b),
    ("ss_runtime_set_part_color_override_corners",
     [_P, _u32, C.c_ubyte, C.POINTER(C.c_uint32), C.c_ubyte], _b),
    ("ss_runtime_clear_part_color_override", [_P, _u32], _b),
    ("ss_runtime_set_part_cell_override",
     [_P, _u32, _u32, _u32, C.c_ubyte], _b),
    ("ss_runtime_clear_part_cell_override", [_P, _u32], _b),
    ("ss_runtime_clear_all_part_overrides", [_P], _b),

    # Instance / Effect slots. Effect slots bind to a *resource* + effect-name
    # hash; instance slots are stateless and step against a *child context*
    # per call. The active-event getters resolve the per-slot event off the
    # parent context (slot_index = the part index from the draw plan).
    ("ss_effect_slot_create", [_P, _u32, _u32], _P),
    ("ss_effect_slot_destroy", [_P], None),
    ("ss_effect_slot_reset", [_P], None),
    ("ss_effect_slot_step",
     [_P, ss_effect_event_info, _f32, _f32, _f32, _b, _b, _u8, _b],
     ss_effect_step_result),
    ("ss_effect_slot_is_independent", [_P], _b),
    ("ss_instance_slot_create", [], _P),
    ("ss_instance_slot_destroy", [_P], None),
    ("ss_instance_slot_reset", [_P], None),
    ("ss_instance_slot_step",
     [_P, ss_event_instance_info, _P, _f32, _f32, _b],
     ss_instance_step_result),
    ("ss_instance_slot_is_independent", [_P], _b),
    ("ss_runtime_get_active_event_instance", [_P, _u32], ss_event_instance_info),
    ("ss_runtime_get_active_effect_event", [_P, _u32], ss_effect_event_info),
)


def _missing_symbols(lib: C.CDLL) -> list[str]:
    """The ``_REQUIRED`` exports ``lib`` lacks, in table order; empty when it
    can run this player."""
    return [name for name, _args, _res in _REQUIRED if not hasattr(lib, name)]


def _mismatch_message(where: str, missing: list[str]) -> str:
    shown = ", ".join(missing[:12])
    if len(missing) > 12:
        shown += f", and {len(missing) - 12} more"
    return (
        f"The SpriteStudio runtime at {where} does not match this player's "
        f"bindings: it lacks {len(missing)} of the {len(_REQUIRED)} functions "
        f"they call ({shown}). This normally means game/spritestudio/libs/ is "
        "older than the .rpy and .py files beside it. Replace "
        "game/spritestudio/ as a whole, from a single release; when you build "
        "from source, rebuild or redownload the runtime.")


def _declare(lib: C.CDLL) -> None:
    """Attach argtypes/restype to every bound export. Call after
    :func:`_missing_symbols` came back empty."""
    for name, args, res in _REQUIRED:
        fn = getattr(lib, name)
        fn.argtypes = args
        fn.restype = res


def load_library(path: str | None = None, base_dir: str | None = None,
                 *, log: bool = False) -> C.CDLL:
    """Load libssruntime, declare signatures, and optionally route logs.

    Pass ``path`` for an explicit library file, or ``base_dir`` to resolve it
    via :func:`default_library_path` (per-platform/arch layout). The returned
    ``CDLL`` is cached on the module so repeated calls reuse it.

    Raises :class:`RuntimeError` naming the missing functions when the library
    lacks any this player calls (see ``_REQUIRED``), before anything is bound.

    Platform notes (see the bundle layout in :func:`platform_subdir`):
      * **Web (WASM)** cannot be loaded through ctypes at all — that target needs
        a separate integration, so we fail fast with a clear message.
      * **iOS** ships the runtime as an ``.xcframework`` that is normally
        static-linked into the app, so its symbols live in the main image; when
        no standalone library file is present we load the process itself
        (``CDLL(None)``) instead of a path.
    """
    global _LIB
    load_target = path
    if path is None:
        if _is_android():
            # On Android the Brain ships in the APK's lib/<abi>/ (jniLibs), which
            # the installer extracts to the app's read-only nativeLibraryDir — the
            # only place the dynamic linker will dlopen from (W^X since API 29). So
            # load by soname and let the linker resolve it there; ``base_dir`` (the
            # in-APK game tree) is not a real filesystem path and is not loadable.
            load_target = library_filename()   # "libssruntime.so"
        else:
            resolved = default_library_path(base_dir)
            if _is_ios() and not os.path.exists(resolved):
                load_target = None      # CDLL(None) -> statically-linked symbols
            else:
                load_target = resolved
    lib = C.CDLL(load_target)
    missing = _missing_symbols(lib)
    if missing:
        raise RuntimeError(_mismatch_message(
            load_target or "the app's own image (statically linked)", missing))
    _declare(lib)
    if log:
        _install_log_callback(lib)
    _LIB = lib
    return lib


_LIB: C.CDLL | None = None


def _install_log_callback(lib: C.CDLL) -> None:
    global _log_cb_ref

    def _cb(level: int, msg) -> None:
        text = msg.decode("utf-8", "replace") if msg else ""
        print(f"[ssruntime:{level}] {text}", file=sys.stderr)

    _log_cb_ref = _LOG_CB_TYPE(_cb)
    lib.ss_runtime_set_log_callback(_log_cb_ref)


def _refusal(lib: C.CDLL, data: bytes):
    """Why ``data`` must not reach ``ss_resource_create_*``, or None when it may.

    The runtime trusts its input. Bytes that are not a ``.ssab`` are read out of
    bounds, which can abort the whole process — a zero-length buffer does — and
    the one check it makes, the schema version, it reports only as a NULL with
    no reason, since the constructors take no context to record one on. So both
    are checked here, where a refusal is a Python exception that says why. The
    runtime reads a pack only when its version equals the runtime's own, and
    this follows that rule; were the runtime to accept a range, a pack it could
    read would be refused here, so the two must move together."""
    if not SsAnimeBinary.SsAnimeBinaryBufferHasIdentifier(data, 0):
        return "not a .ssab pack (missing the 'SSAB' FlatBuffers identifier)"
    try:
        got = int(SsAnimeBinary.GetRootAs(data, 0).Version())
    except Exception:  # noqa: BLE001 — a header that does not parse is the finding
        return "not a .ssab pack (its header does not parse)"
    reads = int(lib.ss_runtime_ssab_schema_version())
    if got == reads:
        return None
    if got < reads:
        fix = "It was converted by an older converter: convert its .sspj again."
    else:
        fix = ("It is newer than this runtime: replace game/spritestudio/ with "
               "the release that converted it, or convert its .sspj again "
               "with this one.")
    return (f"this .ssab is schema version {got} and the SpriteStudio runtime "
            f"reads version {reads}. {fix}")


def _readonly_view(ptr, n):
    """Read-only ``memoryview`` over a Brain-owned buffer — **no copy**.

    The Python analogue of SSPlayerForUnity's zero-copy path (a ``ByteBuffer``
    pointed straight at the native pointer). ``ptr`` is a ctypes pointer, ``n``
    the byte length. The view aliases the Brain's memory and is valid only until
    the next invalidating Brain call (see the module-level lifetime rules) — the
    caller MUST finish parsing/materializing before then and must not retain it.
    Returns an owned empty view for a NULL/empty buffer (kept truthy-false).
    """
    if not ptr or n <= 0:
        return memoryview(b"")
    arr = (C.c_ubyte * n).from_address(C.cast(ptr, C.c_void_p).value)
    mv = memoryview(arr)
    try:
        return mv.toreadonly()        # Py 3.8+ (Ren'Py 8 / modern CPython)
    except AttributeError:            # pragma: no cover - legacy interpreters
        return mv


class _NativeRuntime:
    """One animation context bound to one resource (.ssab).

    Use as a context manager or call :meth:`close` explicitly. Resources are
    bound with the zero-copy ``borrow`` strategy by default (see
    :meth:`load_ssab_bytes`).
    """

    def __init__(self, lib: C.CDLL | None = None):
        self._lib = lib or _LIB
        if self._lib is None:
            self._lib = load_library()
        self._ctx = self._lib.ss_runtime_create()
        if not self._ctx:
            raise RuntimeError("ss_runtime_create failed")
        self._res = None
        self._ssab_bytes = None  # kept alive for diagnostics / metadata parsing

    # -- setup ------------------------------------------------------------
    def configure(self, *, render_mode=RENDER_MODE_DIRECT,
                  coordinate_system=COORD_Y_DOWN, origin=ORIGIN_CENTER,
                  unit=UNIT_PIXEL):
        L, ctx = self._lib, self._ctx
        L.ss_runtime_set_render_mode(ctx, render_mode)
        L.ss_runtime_set_coordinate_system(ctx, coordinate_system)
        L.ss_runtime_set_origin(ctx, origin)
        L.ss_runtime_set_unit(ctx, unit)
        return self

    def load_ssab_bytes(self, data: bytes, *, borrow: bool = True):
        """Bind ``data`` to the context as the animation resource.

        ``borrow=True`` (default) uses ``ss_resource_create_borrow``: the Brain
        keeps a pointer into ``data`` and reads from it for the resource's whole
        lifetime (zero-copy, mirroring SSPlayerForUnity's pinned-``byte[]``
        borrow). ``data`` therefore becomes the backing store — we keep an owned,
        immutable reference (``self._ssab_bytes``) alive until the resource is
        destroyed, and the bytes must never be mutated. CPython does not relocate
        a ``bytes`` object, so holding the reference is the equivalent of Unity's
        ``GCHandle.Pinned``; no explicit pin is required. ``borrow=False`` falls
        back to ``ss_resource_create_copy`` (the Brain owns its own copy).

        Safe re-load: the *previous* resource is destroyed only **after** the new
        one is bound, so the old borrow source is never freed while still
        referenced — the single-threaded analogue of Unity's
        ``destroy resource → free pin`` ordering.

        Bytes that are not a ``.ssab``, or a pack of a schema version the
        runtime does not read, raise RuntimeError saying which before the
        runtime sees them (see :func:`_refusal`), and leave the previous
        resource bound.
        """
        L = self._lib
        data = bytes(data)  # ensure an owned, immutable buffer (stable address)
        refusal = _refusal(L, data)
        if refusal:
            raise RuntimeError(refusal)
        prev_res, prev_bytes = self._res, self._ssab_bytes
        self._ssab_bytes = data  # retain: this IS the borrow's backing store
        create = (L.ss_resource_create_borrow if borrow
                  else L.ss_resource_create_copy)
        self._res = create(data, len(data))
        if not self._res:
            self._res, self._ssab_bytes = prev_res, prev_bytes  # restore
            raise RuntimeError("ss_resource_create failed")
        if not L.ss_runtime_bind_resource(self._ctx, self._res):
            # Bind failed: destroy the resource we just created (else it leaks)
            # and restore the previous handle + its backing bytes, which the
            # assignment above already overwrote. Without the restore,
            # ``self._ssab_bytes`` drops the only reference to ``prev_bytes``
            # while the context may still borrow it via ``prev_res`` ->
            # use-after-free.
            L.ss_resource_destroy(self._res)
            self._res, self._ssab_bytes = prev_res, prev_bytes
            raise RuntimeError("ss_runtime_bind_resource failed")
        # New resource is bound and live; only now release the old borrow source.
        if prev_res:
            L.ss_resource_destroy(prev_res)
        return self

    def load_ssab_file(self, path: str):
        with open(path, "rb") as fh:
            return self.load_ssab_bytes(fh.read())

    def setup_animation(self, name: str) -> bool:
        return bool(self._lib.ss_runtime_setup_animation(
            self._ctx, name.encode("utf-8")))

    # -- playback ---------------------------------------------------------
    def play(self):
        self._lib.ss_runtime_play(self._ctx)
        return self

    def pause(self):
        """Hold playback on the current frame. Idempotent, and ignored while
        nothing is playing."""
        self._lib.ss_runtime_pause(self._ctx)

    def resume(self):
        """Lift a :meth:`pause`, carrying on from the same frame. Idempotent,
        and a no-op on a stopped animation -- ``play`` heads out, so it cannot
        serve as a resume."""
        self._lib.ss_runtime_resume(self._ctx)

    def stop(self):
        self._lib.ss_runtime_stop(self._ctx)

    def set_loop_count(self, loop_count: int):
        self._lib.ss_runtime_set_loop_count(self._ctx, loop_count)
        return self

    def set_speed_scale(self, rate: float):
        self._lib.ss_runtime_set_speed_scale(self._ctx, rate)

    def set_frame_no(self, frame: float):
        self._lib.ss_runtime_set_frame_no(self._ctx, frame)

    def play_with_start_frame(self, frame: float):
        """Start playback from ``frame`` (``play(startFrame)``)."""
        self._lib.ss_runtime_play_with_start_frame(self._ctx, float(frame))
        return self

    def set_frame_rate(self, fps: int):
        self._lib.ss_runtime_set_frame_rate(self._ctx, int(fps))

    def set_animation_section(self, start: int, end: int):
        """Limit playback/loop to ``[start, end]`` (``set_animation_section``)."""
        self._lib.ss_runtime_set_animation_section(self._ctx, int(start), int(end))

    def set_playback_direction(self, direction: int, style: int = STYLE_NORMAL):
        """``direction`` = DIRECTION_FORWARD/BACKWARD; ``style`` = STYLE_NORMAL/PINGPONG."""
        self._lib.ss_runtime_set_playback_direction(
            self._ctx, int(direction), int(style))

    def set_skip_frames(self, skip: bool) -> None:
        """Toggle frame skipping — the runtime's two advance modes.

        On (the default) is *Timed*: ``update`` advances by the exact elapsed
        time, so playback keeps real-time pace and a long delta skips frames.
        Off is *Fixed*: the delta is accumulated and the head advances by
        **exactly one frame per update**, so no frame is ever skipped and a
        stall stretches the animation instead of dropping it
        (``libs/ssruntime/src/core/playback_controller.rs``). Either way the
        frames crossed are still reported, so events do not go missing."""
        self._lib.ss_runtime_set_skip_frames(self._ctx, bool(skip))

    def update(self, dt_seconds: float) -> float:
        """Advance by ``dt_seconds`` **seconds**; returns current frame (float).

        NOTE: the underlying C-API ``ss_runtime_update`` takes **milliseconds**.
        Ren'Py hands us ``st``/``at`` in seconds, so this wrapper converts; use
        :meth:`update_ms` for the raw ms call.
        """
        return self._lib.ss_runtime_update(self._ctx, dt_seconds * 1000.0)

    def update_ms(self, dt_ms: float) -> float:
        """Raw passthrough to the C-API: advance by ``dt_ms`` milliseconds."""
        return self._lib.ss_runtime_update(self._ctx, dt_ms)

    # -- state ------------------------------------------------------------
    @property
    def frame_no(self) -> float:
        return self._lib.ss_runtime_get_frame_no(self._ctx)

    @property
    def speed_scale(self) -> float:
        """The speed in effect, as a multiple of :attr:`frame_rate`.

        What ``set_animation_speed`` *stored*, not what it was handed: a zero or
        negative rate clamps to ``0.0`` (a stop -- reverse playback is
        ``set_playback_direction``'s business), so a host reading this back sees
        the stop it actually got instead of assuming it got reverse playback.
        """
        return self._lib.ss_runtime_get_speed_scale(self._ctx)

    @property
    def is_playing(self) -> bool:
        return bool(self._lib.ss_runtime_is_playing(self._ctx))

    @property
    def is_pausing(self) -> bool:
        return bool(self._lib.ss_runtime_is_pausing(self._ctx))

    @property
    def is_clock_playing(self) -> bool:
        """Whether the character's clock runs (or is held by pause).

        Set by play, cleared by stop and a successful setup_animation; unlike
        :attr:`is_playing` it outlives track 0 finishing."""
        return bool(self._lib.ss_runtime_is_clock_playing(self._ctx))

    @property
    def is_clock_pausing(self) -> bool:
        """Whether pause holds the character's clock; implies
        :attr:`is_clock_playing`."""
        return bool(self._lib.ss_runtime_is_clock_pausing(self._ctx))

    @property
    def is_stack_in_motion(self) -> bool:
        """Whether the track stack moves the pose on a running clock for a
        reason other than track 0's own animation: a fade on any track, or a
        source other than track 0's main one playing at a speed and weight
        above 0 on a track that is heard. Does not read the clock; combine it
        with :attr:`is_clock_playing` and :attr:`is_clock_pausing`."""
        return bool(self._lib.ss_runtime_is_stack_in_motion(self._ctx))

    @property
    def is_finished(self) -> bool:
        """True once every configured loop has played.

        A sticky state, not a pulse: it stays true until the next play/setup, so
        callers wanting a one-shot notification take its rising edge. Never true
        under an infinite loop count, nor after a commanded stop()."""
        return bool(self._lib.ss_runtime_is_finished(self._ctx))

    @property
    def just_looped(self) -> bool:
        """True if the last :meth:`update` crossed a loop boundary (per-update)."""
        return bool(self._lib.ss_runtime_just_looped(self._ctx))

    @property
    def is_playing_forward(self) -> bool:
        """True when the head is advancing forward on the timeline.

        Accounts for the Backward direction setting and the current ping-pong
        leg (outbound/return). The speed sign needs no check: a negative speed
        stops the playhead rather than reversing it."""
        return bool(self._lib.ss_runtime_is_playing_forward(self._ctx))

    @property
    def playback_direction(self) -> int:
        """The *configured* direction (DIRECTION_FORWARD / DIRECTION_BACKWARD).

        The setting, not the instantaneous heading — on a ping-pong return leg
        this still reads FORWARD while :attr:`is_playing_forward` reads False."""
        return int(self._lib.ss_runtime_get_playback_direction(self._ctx))

    @property
    def playback_style(self) -> int:
        """The configured style (STYLE_NORMAL / STYLE_PINGPONG)."""
        return int(self._lib.ss_runtime_get_playback_style(self._ctx))

    @property
    def skip_frames(self) -> bool:
        """Whether frame skipping is on (the runtime default); see
        :meth:`set_skip_frames`."""
        return bool(self._lib.ss_runtime_get_skip_frames(self._ctx))

    @property
    def frame_rate(self) -> int:
        return int(self._lib.ss_runtime_get_frame_rate(self._ctx))

    @property
    def start_frame(self) -> int:
        return int(self._lib.ss_runtime_get_start_frame(self._ctx))

    @property
    def end_frame(self) -> int:
        return int(self._lib.ss_runtime_get_end_frame(self._ctx))

    @property
    def total_frames(self) -> int:
        """Frame count of the current section (``end - start + 1``)."""
        return max(0, self.end_frame - self.start_frame + 1)

    @property
    def remaining_loops(self) -> int:
        return int(self._lib.ss_runtime_get_remaining_loops(self._ctx))

    # -- events (see ss_renpy.events) -------------------------------------
    def passed_event_count(self) -> int:
        """Number of timeline events the last :meth:`update` passed through."""
        return int(self._lib.ss_runtime_get_passed_event_count(self._ctx))

    def passed_event_index(self, i: int) -> int:
        """Index of the ``i``-th passed event into the animation's events vector.

        Resolve it with :class:`ss_renpy.events.EventResolver`.
        """
        return int(self._lib.ss_runtime_get_passed_event_index(self._ctx, i))

    def passed_event_source_handle(self, i: int):
        """Handle of the source whose animation fired the ``i``-th passed
        event, or None when there is no such event."""
        return self._mix_handle("ss_runtime_get_passed_event_source_handle", i)

    # -- animation mixing (the track stack; see ss_renpy.player) ----------
    # Thin passthroughs over the ss_runtime_*track* / *source* C-API. Its
    # "no value" sentinels (NaN, -1, the invalid handle) come back as None and
    # the setters as a bool.
    def _mix(self, symbol, *args):
        return getattr(self._lib, symbol)(self._ctx, *args)

    def _mix_ok(self, symbol, *args) -> bool:
        return bool(self._mix(symbol, *args))

    def _mix_float(self, symbol, *args):
        v = self._mix(symbol, *args)
        return None if v != v else float(v)

    def _mix_int(self, symbol, *args, none=-1):
        v = self._mix(symbol, *args)
        return None if v == none else int(v)

    def _mix_handle(self, symbol, *args):
        return self._mix_int(symbol, *args, none=INVALID_HANDLE)

    def set_track_animation(self, track: int, name: str) -> bool:
        return self._mix_ok("ss_runtime_set_track_animation", track,
                            name.encode("utf-8"))

    def track_count(self) -> int:
        return int(self._mix("ss_runtime_get_track_count"))

    def clear_track(self, track: int) -> bool:
        return self._mix_ok("ss_runtime_clear_track", track)

    def set_track_alpha(self, track: int, alpha: float) -> bool:
        return self._mix_ok("ss_runtime_set_track_alpha", track, alpha)

    def track_alpha(self, track: int):
        return self._mix_float("ss_runtime_get_track_alpha", track)

    def set_track_blend(self, track: int, blend: int) -> bool:
        return self._mix_ok("ss_runtime_set_track_blend", track, blend)

    def track_blend(self, track: int):
        return self._mix_handle("ss_runtime_get_track_blend", track)

    def set_track_sync(self, track: int, sync: int) -> bool:
        return self._mix_ok("ss_runtime_set_track_sync", track, sync)

    def track_sync(self, track: int):
        return self._mix_handle("ss_runtime_get_track_sync", track)

    def set_track_frame(self, track: int, frame: float) -> bool:
        return self._mix_ok("ss_runtime_set_track_frame", track, frame)

    def track_frame(self, track: int):
        return self._mix_float("ss_runtime_get_track_frame", track)

    def set_track_speed(self, track: int, speed: float) -> bool:
        return self._mix_ok("ss_runtime_set_track_speed", track, speed)

    def track_speed(self, track: int):
        return self._mix_float("ss_runtime_get_track_speed", track)

    def set_track_frame_rate(self, track: int, fps: int) -> bool:
        return self._mix_ok("ss_runtime_set_track_frame_rate", track, fps)

    def track_frame_rate(self, track: int):
        return self._mix_int("ss_runtime_get_track_frame_rate", track)

    def set_track_skip_frames(self, track: int, skip: bool) -> bool:
        return self._mix_ok("ss_runtime_set_track_skip_frames", track, skip)

    def track_skip_frames(self, track: int) -> bool:
        # The C-API reads a track that does not exist as False; the caller
        # asks track_count first.
        return self._mix_ok("ss_runtime_get_track_skip_frames", track)

    def set_track_playback_direction(self, track: int, direction: int,
                                     style: int = STYLE_NORMAL) -> bool:
        return self._mix_ok("ss_runtime_set_track_playback_direction", track,
                            direction, style)

    def track_playback_direction(self, track: int):
        return self._mix_int("ss_runtime_get_track_playback_direction", track)

    def track_playback_style(self, track: int):
        return self._mix_int("ss_runtime_get_track_playback_style", track)

    def set_track_loop_count(self, track: int, count: int) -> bool:
        return self._mix_ok("ss_runtime_set_track_loop_count", track, count)

    def track_loop_count(self, track: int):
        # 0 is "no animation": a count reads back positive, or -1 forever.
        return self._mix_int("ss_runtime_get_track_loop_count", track, none=0)

    def is_track_finished(self, track: int) -> bool:
        return self._mix_ok("ss_runtime_is_track_finished", track)

    def track_just_looped(self, track: int) -> bool:
        return self._mix_ok("ss_runtime_track_just_looped", track)

    def set_track_outgoing_event_threshold(self, track: int,
                                           threshold: float) -> bool:
        return self._mix_ok("ss_runtime_set_track_outgoing_event_threshold",
                            track, threshold)

    def track_outgoing_event_threshold(self, track: int):
        return self._mix_float("ss_runtime_get_track_outgoing_event_threshold",
                               track)

    def crossfade(self, track: int, name: str, duration_ms: float) -> bool:
        return self._mix_ok("ss_runtime_crossfade", track,
                            name.encode("utf-8"), duration_ms)

    def fade_track(self, track: int, target_alpha: float,
                   duration_ms: float) -> bool:
        return self._mix_ok("ss_runtime_fade_track", track, target_alpha,
                            duration_ms)

    def track_fade_progress(self, track: int):
        return self._mix_float("ss_runtime_get_track_fade_progress", track)

    def cancel_track_fade(self, track: int) -> bool:
        return self._mix_ok("ss_runtime_cancel_track_fade", track)

    def track_main_source(self, track: int):
        return self._mix_handle("ss_runtime_get_track_main_source", track)

    def add_track_source(self, track: int, name: str, weight: float):
        return self._mix_handle("ss_runtime_add_track_source", track,
                                name.encode("utf-8"), weight)

    def set_source_weight(self, handle: int, weight: float) -> bool:
        return self._mix_ok("ss_runtime_set_source_weight", handle, weight)

    def source_weight(self, handle: int):
        return self._mix_float("ss_runtime_get_source_weight", handle)

    def set_source_frame(self, handle: int, frame: float) -> bool:
        return self._mix_ok("ss_runtime_set_source_frame", handle, frame)

    def source_frame(self, handle: int):
        return self._mix_float("ss_runtime_get_source_frame", handle)

    def set_source_event_threshold(self, handle: int, threshold: float) -> bool:
        return self._mix_ok("ss_runtime_set_source_event_threshold", handle,
                            threshold)

    def source_event_threshold(self, handle: int):
        return self._mix_float("ss_runtime_get_source_event_threshold", handle)

    def source_animation_index(self, handle: int):
        """Index into the pack's animations of the one ``handle`` plays."""
        return self._mix_int("ss_runtime_get_source_animation_index", handle)

    # -- frame data -------------------------------------------------------
    def _frame_data_ptr(self, frame_no):
        """Evaluate ``frame_no`` and return ``(ptr, len)`` for its FrameData FB.

        Side effect: also (re)populates this context's SoA buffers (world
        matrices, vertices, UVs, cell meta) — they share the same snapshot
        (ssruntime.h: "written by ss_runtime_get_frame_data"). The returned
        pointer is valid only until the next ``get_frame_data``/``update`` on
        this context; pure SoA getters do not invalidate it.
        """
        ptr = C.POINTER(C.c_ubyte)()
        length = C.c_size_t()
        self._lib.ss_runtime_get_frame_data(
            self._ctx, frame_no, C.byref(ptr), C.byref(length))
        return ptr, length.value

    def get_frame_data(self, frame_no: float) -> bytes:
        """Return the FrameData FlatBuffer for ``frame_no`` as a fresh bytes.

        The Brain returns a pointer valid only until the next call; we copy it
        out immediately so the caller can parse and retain it at leisure. On the
        per-frame render path prefer :meth:`get_frame_data_view` to skip the copy.
        """
        ptr, n = self._frame_data_ptr(frame_no)
        if not ptr or n == 0:
            return b""
        return C.string_at(ptr, n)

    def get_frame_data_view(self, frame_no: float):
        """Zero-copy read-only ``memoryview`` of the FrameData FlatBuffer.

        Valid only until the next invalidating Brain call on **this** context
        (next ``get_frame_data``/``update``/slot-step). Parse and materialize the
        draw plan (``framedata.iter_draw_plan`` / ``build_*``) before then, and
        do NOT retain it across frames — copy out (``bytes(view)`` or a small
        snapshot) anything a later query needs. A *child* runtime's
        ``get_frame_data`` writes a separate buffer and does not invalidate this
        one, so the recursive instance walk is safe. Mirrors SSPlayerForUnity's
        zero-copy ``ConsumeFrameData``.
        """
        ptr, n = self._frame_data_ptr(frame_no)
        return _readonly_view(ptr, n)

    def _soa_float(self, getter):
        ptr = C.POINTER(C.c_float)()
        n = C.c_size_t()
        getter(self._ctx, C.byref(ptr), C.byref(n))
        return ptr, n.value

    def _soa_int32(self, getter):
        ptr = C.POINTER(C.c_int32)()
        n = C.c_size_t()
        getter(self._ctx, C.byref(ptr), C.byref(n))
        return ptr, n.value

    def _soa_uint32(self, getter):
        ptr = C.POINTER(C.c_uint32)()
        n = C.c_size_t()
        getter(self._ctx, C.byref(ptr), C.byref(n))
        return ptr, n.value

    def world_matrices(self):
        """(ptr, count_floats) for the world-matrix SoA buffer (16/part)."""
        return self._soa_float(self._lib.ss_runtime_get_world_matrices)

    def local_vertices(self):
        return self._soa_float(self._lib.ss_runtime_get_local_vertices)

    def local_uvs(self):
        return self._soa_float(self._lib.ss_runtime_get_local_uvs)

    def cell_meta(self):
        return self._soa_float(self._lib.ss_runtime_get_cell_meta)

    # -- Mesh(deform) SoA buffers -----------------------------------------
    # Pre-computed WORLD vertices (coordinate system already applied), part-
    # local 0-based indices, and CSR offset arrays (length num_parts + 1). UVs
    # are interleaved [u, v, ...] at offset vertex_offset*2. Empty (len 0) under
    # RenderMode::SceneGraph — this Player uses Direct, so they are populated.
    def mesh_vertices_x(self):
        return self._soa_float(self._lib.ss_runtime_get_mesh_vertices_x)

    def mesh_vertices_y(self):
        return self._soa_float(self._lib.ss_runtime_get_mesh_vertices_y)

    def mesh_uvs(self):
        return self._soa_float(self._lib.ss_runtime_get_mesh_uvs)

    def mesh_indices(self):
        return self._soa_int32(self._lib.ss_runtime_get_mesh_indices)

    def mesh_vertex_offsets(self):
        return self._soa_uint32(self._lib.ss_runtime_get_mesh_vertex_offsets)

    def mesh_index_offsets(self):
        return self._soa_uint32(self._lib.ss_runtime_get_mesh_index_offsets)

    # -- Shape SoA buffers (Shape-kind parts) -----------------------------
    # Procedural shape geometry (Rectangle/Triangle/Star/Arrow). Fixed stride
    # of 12 vertices/part (24 floats): ``shape_vertices`` are LOCAL, post-pivot,
    # post-coord-system (multiply by the world matrix, like local_vertices);
    # ``shape_vertex_box_coords`` are the matching normalized bbox coords
    # ((0,0)=LT .. (1,1)=RB) for per-vertex PartColor interpolation. Only the
    # first ``shape_vertex_counts()[part]`` slots are valid (0 for non-shape
    # parts). Shape parts carry no texture — the fill is the PartColor.
    def shape_vertices(self):
        return self._soa_float(self._lib.ss_runtime_get_shape_vertices)

    def shape_vertex_box_coords(self):
        return self._soa_float(self._lib.ss_runtime_get_shape_vertex_box_coords)

    def shape_vertex_counts(self):
        return self._soa_int32(self._lib.ss_runtime_get_shape_vertex_counts)

    # -- Override Layer (per-part runtime overrides) ----------------------
    # Thin wrappers over the ``ss_runtime_*_override`` C-API. The Brain applies
    # them on the *resolved* pose, so an override wins over both the keyframe
    # and any blend; it also owns the table and its whole lifecycle (a new
    # animation drops visibility + non-Permanent color/cell; a new resource
    # drops everything), so this wrapper keeps no copy.
    #
    # Every method returns False when the call is rejected — unknown part index,
    # blend_op >= 4, priority_mode >= 3, unresolvable cell.
    @property
    def supports_overrides(self) -> bool:
        """Whether the loaded library has the Override Layer: always, since
        load_library refuses one without it. Kept so both bridges answer it."""
        return True

    def find_part_index(self, part_name: str) -> int:
        """The Brain's own name -> part index lookup; -1 when not found.

        The Player normally resolves names off the pack metadata instead (same
        index space, and it works identically on web); this is the C-API's
        equivalent, kept for cross-checking.
        """
        return int(self._lib.ss_runtime_find_part_index(
            self._ctx, part_name.encode("utf-8")))

    def set_part_visibility_override(self, part: int, force: int,
                                     cascade: bool = False) -> bool:
        """``force``: 0 = clear/revert to the animation, 1 = force-hide.
        ``cascade`` propagates the force-hide to the part's descendants."""
        return bool(self._lib.ss_runtime_set_part_visibility_override(
            self._ctx, int(part), int(force), 1 if cascade else 0))

    def clear_part_visibility_override(self, part: int) -> bool:
        return bool(self._lib.ss_runtime_clear_part_visibility_override(
            self._ctx, int(part)))

    def set_part_color_override(self, part: int, blend_op: int, rgba: int,
                                priority: int = PRIORITY_HOLD_UNTIL_NEXT_ANIMATION) -> bool:
        """``rgba`` is packed ``0xRRGGBBAA`` in the same 8-bit sRGB space as the
        authored PartColor — the Brain pre-multiplies alpha itself, so pass the
        colour as authored. Fills all four corners."""
        return bool(self._lib.ss_runtime_set_part_color_override(
            self._ctx, int(part), int(blend_op), int(rgba) & 0xFFFFFFFF,
            int(priority)))

    def set_part_color_override_corners(self, part: int, blend_op: int,
                                        corners_rgba,
                                        priority: int = PRIORITY_HOLD_UNTIL_NEXT_ANIMATION) -> bool:
        """Four distinct corners, in the runtime's ``lt, rt, lb, rb`` order."""
        corners = list(corners_rgba)
        if len(corners) != 4:
            return False
        buf = (C.c_uint32 * 4)(*[int(c) & 0xFFFFFFFF for c in corners])
        return bool(self._lib.ss_runtime_set_part_color_override_corners(
            self._ctx, int(part), int(blend_op), buf, int(priority)))

    def clear_part_color_override(self, part: int) -> bool:
        return bool(self._lib.ss_runtime_clear_part_color_override(
            self._ctx, int(part)))

    def set_part_cell_override(self, part: int, cellmap_name_hash: int,
                               cell_name_hash: int,
                               priority: int = PRIORITY_HOLD_UNTIL_NEXT_ANIMATION) -> bool:
        """Point a part at a different cell. Hashes are fnv1a-32 of the cellmap
        name (without ``.ssce``) and the cell name; ``(0, 0)`` reverts to the
        animation. The cell is resolved now, so an unknown name returns False."""
        return bool(self._lib.ss_runtime_set_part_cell_override(
            self._ctx, int(part), int(cellmap_name_hash) & 0xFFFFFFFF,
            int(cell_name_hash) & 0xFFFFFFFF, int(priority)))

    def clear_part_cell_override(self, part: int) -> bool:
        return bool(self._lib.ss_runtime_clear_part_cell_override(
            self._ctx, int(part)))

    def clear_all_part_overrides(self) -> bool:
        return bool(self._lib.ss_runtime_clear_all_part_overrides(self._ctx))

    # -- Instance / Effect slots ------------------------------------------
    # Instance: stateless slot stepped against a *child* context per call.
    # Effect: stateful slot bound to this runtime's resource + an effect hash.
    # ``slot_index`` for the active-event getters is the part index from the
    # draw plan. See ss_renpy.instance / ss_renpy.effect for the consumers.
    @property
    def resource(self):
        """The bound resource handle (needed to create Effect slots)."""
        return self._res

    def active_event_instance(self, slot_index: int):
        """Active ``EventInstance`` for part ``slot_index`` (returns a struct)."""
        return self._lib.ss_runtime_get_active_event_instance(
            self._ctx, int(slot_index))

    def active_effect_event(self, slot_index: int):
        """Active ``EventEffect`` for part ``slot_index`` (returns a struct)."""
        return self._lib.ss_runtime_get_active_effect_event(
            self._ctx, int(slot_index))

    def instance_slot_create(self):
        return self._lib.ss_instance_slot_create()

    def instance_slot_destroy(self, slot):
        if slot:
            self._lib.ss_instance_slot_destroy(slot)

    def instance_slot_reset(self, slot):
        if slot:
            self._lib.ss_instance_slot_reset(slot)

    def instance_slot_step(self, slot, ev, child_ctx, parent_frame,
                           delta_seconds, parent_looped):
        """Drive one instance slot a tick; returns ``ss_instance_step_result``.

        ``child_ctx`` is the *child* runtime's context pointer; ``ev`` an
        :class:`ss_event_instance_info` from :meth:`active_event_instance` on
        the *parent*.
        """
        return self._lib.ss_instance_slot_step(
            slot, ev, child_ctx, float(parent_frame), float(delta_seconds),
            bool(parent_looped))

    def instance_slot_is_independent(self, slot):
        return bool(self._lib.ss_instance_slot_is_independent(slot))

    def effect_slot_create(self, effect_name_hash, seed=0):
        """Create an Effect slot bound to this runtime's resource.

        Returns a slot handle, or ``None`` on failure (effect hash not found /
        malformed effect data / no resource bound).
        """
        if not self._res:
            return None
        slot = self._lib.ss_effect_slot_create(
            self._res, int(effect_name_hash) & 0xFFFFFFFF, int(seed) & 0xFFFFFFFF)
        return slot or None

    def effect_slot_destroy(self, slot):
        if slot:
            self._lib.ss_effect_slot_destroy(slot)

    def effect_slot_reset(self, slot):
        if slot:
            self._lib.ss_effect_slot_reset(slot)

    def _effect_slot_step_raw(self, slot, ev, parent_frame, delta_seconds, fps,
                              parent_looped, y_flip, vert_stride, draw):
        return self._lib.ss_effect_slot_step(
            slot, ev, float(parent_frame), float(delta_seconds), float(fps),
            bool(parent_looped), bool(y_flip), int(vert_stride), bool(draw))

    def effect_slot_step(self, slot, ev, parent_frame, delta_seconds, fps,
                         parent_looped, y_flip=True, vert_stride=2, *, draw):
        """Advance one effect slot.

        Returns ``(visible, draw_plan_bytes)``: the ``EffectDrawPlan``
        FlatBuffer is copied out immediately (the raw pointer is valid only
        until the next call on this slot). ``ev`` is an
        :class:`ss_effect_event_info` from :meth:`active_effect_event`.
        ``y_flip=True`` / ``vert_stride=2`` suit a 2D Y-down host (Ren'Py).
        ``draw`` is whether the part is in this frame's ``draw_order``: with
        ``False`` the step moves only the effect's clock and transitions,
        builds no plan and returns not visible, and the next step with ``True``
        returns the plan an always-drawn slot would. It has no default, so no
        caller drops it by accident.
        Prefer :meth:`effect_slot_step_view` on the hot path to skip the copy.
        """
        r = self._effect_slot_step_raw(slot, ev, parent_frame, delta_seconds,
                                       fps, parent_looped, y_flip, vert_stride,
                                       draw)
        if not r.visible or not r.draw_plan_buf or r.draw_plan_len == 0:
            return (bool(r.visible), b"")
        return (True, C.string_at(r.draw_plan_buf, r.draw_plan_len))

    def effect_slot_step_view(self, slot, ev, parent_frame, delta_seconds, fps,
                              parent_looped, y_flip=True, vert_stride=2, *,
                              draw):
        """Like :meth:`effect_slot_step` but returns a zero-copy view.

        ``(visible, draw_plan_view)`` where ``draw_plan_view`` is a read-only
        ``memoryview`` aliasing the slot's internal buffer — valid only until the
        next ``step`` on the **same** slot (see ``ss_effect_step_result`` in the
        generated ssruntime.h). ``effectplan.build_effect_batches`` drains it
        into Python lists in a single pass, so per-call use is safe; never
        retain the view past that call. Mirrors SSPlayerForUnity's zero-copy
        effect ``Append``.
        """
        r = self._effect_slot_step_raw(slot, ev, parent_frame, delta_seconds,
                                       fps, parent_looped, y_flip, vert_stride,
                                       draw)
        if not r.visible or not r.draw_plan_buf or r.draw_plan_len == 0:
            return (bool(r.visible), memoryview(b""))
        return (True, _readonly_view(r.draw_plan_buf, r.draw_plan_len))

    def effect_slot_is_independent(self, slot):
        return bool(self._lib.ss_effect_slot_is_independent(slot))

    # -- lifecycle --------------------------------------------------------
    @property
    def ctx(self):
        return self._ctx

    @property
    def lib(self):
        return self._lib

    def close(self):
        if self._ctx:
            self._lib.ss_runtime_destroy(self._ctx)
            self._ctx = None
        if self._res:
            self._lib.ss_resource_destroy(self._res)
            self._res = None
        # Release the borrow's backing bytes only after the context and resource
        # that borrow it are gone (Unity frees the pin last, in its `finally`).
        self._ssab_bytes = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def __del__(self):
        try:
            self.close()
        except:
            pass

