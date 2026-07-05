"""ctypes bindings for libssruntime ("Brain").

This is the FFI layer of the Ren'Py SSPlayer. It is intentionally free of any
``renpy`` import so it can be exercised from plain CPython (the M0 smoke test)
as well as from inside Ren'Py's bundled interpreter (M1+).

Signatures are transcribed from the generated C header
``libs/ssruntime/target/ssruntime.h`` — that header is the source of truth;
keep ``argtypes``/``restype`` in sync with it.

Lifetime rules (see ``docs/00_limitations``):
  * A bound ``resource`` must outlive every ``context`` it is bound to.
    Internally the runtime ref-counts with ``Arc``, so destroying the resource
    handle early is safe *as long as* contexts are destroyed/reset too. We keep
    the Python wrapper conservative: ``close()`` destroys the context first,
    then the resource.
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
PLAY_FORWARD = 0
PLAY_REVERSE = 1

# playback_style (ss_runtime_set_playback_direction's second arg)
STYLE_NORMAL = 0
STYLE_PINGPONG = 1


# --- by-value structs for the Instance / Effect slot API ------------------
# These mirror the C structs in ``target/ssruntime.h`` *exactly* (field order
# and width). They are passed/returned BY VALUE across the FFI, so the layout
# must match; ctypes' natural alignment matches the runtime's ``#[repr(C)]``.

class ss_effect_step_result(C.Structure):
    """Return of ``ss_effect_slot_step`` (ssruntime.h §27-37).

    ``draw_plan_buf`` is a FlatBuffers ``EffectDrawPlan`` valid only until the
    next step on the same slot — copy it out immediately.
    """
    _fields_ = [
        ("visible", C.c_bool),
        ("draw_plan_buf", C.POINTER(C.c_uint8)),
        ("draw_plan_len", C.c_size_t),   # uintptr_t
    ]


class ss_effect_event_info(C.Structure):
    """Resolved per-slot Effect event (ssruntime.h §48-58)."""
    _fields_ = [
        ("event_frame", C.c_int32),
        ("start_time", C.c_int32),
        ("speed", C.c_float),
        ("independent", C.c_bool),
        ("is_synthetic_default", C.c_bool),
    ]


class ss_instance_step_result(C.Structure):
    """Return of ``ss_instance_slot_step`` (ssruntime.h §66-72).

    ``child_frame_no`` is a raw float (sub-frame precise) — write it back
    verbatim; never floor/round it for state (docs/08 §3).
    """
    _fields_ = [
        ("visible", C.c_bool),
        ("transitioned", C.c_bool),
        ("independent", C.c_bool),
        ("child_frame_no", C.c_float),
        ("child_looped", C.c_bool),
    ]


class ss_event_instance_info(C.Structure):
    """Resolved per-slot Instance event (ssruntime.h §87-104)."""
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

    The ``android/`` layout under ``libs`` now uses the Android ABI names
    (``arm64-v8a`` / ``armeabi-v7a`` / ``x86_64``) rather than the SDK arch
    tokens, because the Android Brain ships in the APK's ``lib/<abi>/`` (jniLibs)
    and is loaded by soname (see :func:`load_library`) — it is no longer
    dlopen'd from the game tree — so mirroring the jniLibs names keeps the
    staging step a straight copy."""
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

        macos/                          (universal dylib; no arch split)
        windows/x86_64                  (ssruntime.dll)
        linux/x86_64                    (libssruntime.so)
        android/{arm64-v8a,armeabi-v7a,x86_64}    (libssruntime.so)
        ios/                            (libssruntime.xcframework — see load_library)
        web/                            (wasm — not loadable via ctypes)

    NOTE Android must be checked before the generic Linux branch: its
    ``sys.platform`` is also ``"linux"``, but its ``.so`` lives under
    ``android/<abi>`` (abi ∈ arm64-v8a / armeabi-v7a / x86_64 — the NDK/jniLibs
    names), not ``linux/<arch>``.
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
    return os.path.join("linux", arch)


def library_filename() -> str:
    """Shared-library filename for the host (matches the release dynamic libs)."""
    if sys.platform.startswith("win"):
        return "ssruntime.dll"
    if sys.platform == "darwin" and not _is_ios():
        return "libssruntime.dylib"
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


def _declare(lib: C.CDLL) -> None:
    """Attach argtypes/restype to every function we use. void* -> c_void_p."""
    P = C.c_void_p
    f = lib

    f.ss_runtime_set_log_callback.argtypes = [_LOG_CB_TYPE]
    f.ss_runtime_set_log_callback.restype = None

    # resource lifecycle
    f.ss_resource_create_copy.argtypes = [C.c_char_p, C.c_size_t]
    f.ss_resource_create_copy.restype = P
    f.ss_resource_create_borrow.argtypes = [C.c_char_p, C.c_size_t]
    f.ss_resource_create_borrow.restype = P
    f.ss_resource_destroy.argtypes = [P]
    f.ss_resource_destroy.restype = None

    # context lifecycle
    f.ss_runtime_create.argtypes = []
    f.ss_runtime_create.restype = P
    f.ss_runtime_destroy.argtypes = [P]
    f.ss_runtime_destroy.restype = None
    f.ss_runtime_reset.argtypes = [P]
    f.ss_runtime_reset.restype = None
    f.ss_runtime_bind_resource.argtypes = [P, P]
    f.ss_runtime_bind_resource.restype = C.c_bool

    # animation selection
    f.ss_runtime_setup_animation.argtypes = [P, C.c_char_p]
    f.ss_runtime_setup_animation.restype = C.c_bool
    f.ss_runtime_setup_animation_by_hash.argtypes = [P, C.c_uint32]
    f.ss_runtime_setup_animation_by_hash.restype = C.c_bool

    # render/coordinate configuration
    f.ss_runtime_set_render_mode.argtypes = [P, C.c_uint8]
    f.ss_runtime_set_render_mode.restype = None
    f.ss_runtime_get_render_mode.argtypes = [P]
    f.ss_runtime_get_render_mode.restype = C.c_uint8
    f.ss_context_set_coordinate_system.argtypes = [P, C.c_int32]
    f.ss_context_set_coordinate_system.restype = None
    f.ss_context_set_origin.argtypes = [P, C.c_int32]
    f.ss_context_set_origin.restype = None
    f.ss_context_set_unit.argtypes = [P, C.c_int32]
    f.ss_context_set_unit.restype = None

    # frame data (FlatBuffers) + SoA getters
    f.ss_runtime_get_frame_data.argtypes = [
        P, C.c_float, C.POINTER(C.POINTER(C.c_ubyte)), C.POINTER(C.c_size_t)]
    f.ss_runtime_get_frame_data.restype = None
    for name in (
        "ss_runtime_get_world_matrices",
        "ss_runtime_get_local_uvs",
        "ss_runtime_get_cell_meta",
        "ss_runtime_get_local_vertices",
        "ss_runtime_get_shape_vertices",
        "ss_runtime_get_shape_vertex_box_coords",
        "ss_runtime_get_mesh_vertices_x",
        "ss_runtime_get_mesh_vertices_y",
        "ss_runtime_get_mesh_uvs",
    ):
        fn = getattr(f, name)
        fn.argtypes = [P, C.POINTER(C.POINTER(C.c_float)), C.POINTER(C.c_size_t)]
        fn.restype = None
    f.ss_runtime_get_shape_vertex_counts.argtypes = [
        P, C.POINTER(C.POINTER(C.c_int32)), C.POINTER(C.c_size_t)]
    f.ss_runtime_get_mesh_indices.argtypes = [
        P, C.POINTER(C.POINTER(C.c_int32)), C.POINTER(C.c_size_t)]
    for name in ("ss_runtime_get_mesh_vertex_offsets",
                 "ss_runtime_get_mesh_index_offsets"):
        fn = getattr(f, name)
        fn.argtypes = [P, C.POINTER(C.POINTER(C.c_uint32)), C.POINTER(C.c_size_t)]
        fn.restype = None

    # playback control
    f.ss_runtime_update.argtypes = [P, C.c_float]
    f.ss_runtime_update.restype = C.c_float
    f.ss_runtime_play.argtypes = [P]
    f.ss_runtime_play.restype = None
    f.ss_runtime_play_with_start_frame.argtypes = [P, C.c_float]
    f.ss_runtime_play_with_start_frame.restype = None
    f.ss_runtime_pause.argtypes = [P]
    f.ss_runtime_pause.restype = None
    f.ss_runtime_stop.argtypes = [P]
    f.ss_runtime_stop.restype = None
    f.ss_runtime_set_frame_no.argtypes = [P, C.c_float]
    f.ss_runtime_set_frame_no.restype = None
    f.ss_runtime_next_frame.argtypes = [P]
    f.ss_runtime_prev_frame.argtypes = [P]
    f.ss_runtime_set_loop.argtypes = [P, C.c_int]
    f.ss_runtime_set_loop.restype = None
    f.ss_runtime_set_frame_rate.argtypes = [P, C.c_int]
    f.ss_runtime_set_frame_rate.restype = None
    f.ss_runtime_set_animation_speed.argtypes = [P, C.c_float]
    f.ss_runtime_set_animation_speed.restype = None
    f.ss_runtime_set_playback_direction.argtypes = [P, C.c_int, C.c_int]
    f.ss_runtime_set_playback_direction.restype = None
    f.ss_runtime_set_animation_section.argtypes = [P, C.c_int, C.c_int]
    f.ss_runtime_set_animation_section.restype = None

    # state getters
    f.ss_runtime_get_frame_no.argtypes = [P]
    f.ss_runtime_get_frame_no.restype = C.c_float
    for name in ("ss_runtime_is_end_frame_reached", "ss_runtime_is_looped",
                 "ss_runtime_is_playing", "ss_runtime_is_pausing"):
        fn = getattr(f, name)
        fn.argtypes = [P]
        fn.restype = C.c_bool
    for name in ("ss_runtime_get_start_frame", "ss_runtime_get_end_frame",
                 "ss_runtime_get_fps", "ss_runtime_get_loops",
                 "ss_runtime_get_remain_loops"):
        fn = getattr(f, name)
        fn.argtypes = [P]
        fn.restype = C.c_int32
    # Effective playback direction (forward incl. ping-pong leg + Backward
    # setting; the *speed-sign* is NOT folded in — the caller compares it, see
    # docs/00 "オーディオの逆再生非対応"). Optional: older prebuilt runtimes may not
    # export it, so bind tolerantly and let the wrapper assume forward when
    # absent.
    try:
        f.ss_runtime_is_playing_forward.argtypes = [P]
        f.ss_runtime_is_playing_forward.restype = C.c_bool
    except AttributeError:
        pass

    # events
    f.ss_runtime_get_passed_event_count.argtypes = [P]
    f.ss_runtime_get_passed_event_count.restype = C.c_int32
    f.ss_runtime_get_passed_event_index.argtypes = [P, C.c_int32]
    f.ss_runtime_get_passed_event_index.restype = C.c_int32

    # hashing helper (texture/animation name -> u32 fnv1a)
    f.ss_runtime_hash_string.argtypes = [C.c_char_p]
    f.ss_runtime_hash_string.restype = C.c_uint32

    # --- Instance / Effect slot API (docs/08, ssruntime.h §484-602) --------
    # Effect slots bind to a *resource* + effect-name hash; instance slots are
    # stateless and step against a *child context* per call. The active-event
    # getters resolve the per-slot event off the parent context (slot_index =
    # the part index from the draw plan).
    f.ss_effect_slot_create.argtypes = [P, C.c_uint32, C.c_uint32]
    f.ss_effect_slot_create.restype = P
    f.ss_effect_slot_destroy.argtypes = [P]
    f.ss_effect_slot_destroy.restype = None
    f.ss_effect_slot_reset.argtypes = [P]
    f.ss_effect_slot_reset.restype = None
    f.ss_effect_slot_step.argtypes = [
        P, ss_effect_event_info, C.c_float, C.c_float, C.c_float,
        C.c_bool, C.c_bool, C.c_uint8]
    f.ss_effect_slot_step.restype = ss_effect_step_result
    f.ss_effect_slot_get_seed.argtypes = [P]
    f.ss_effect_slot_get_seed.restype = C.c_uint32
    f.ss_effect_slot_is_independent.argtypes = [P]
    f.ss_effect_slot_is_independent.restype = C.c_bool

    f.ss_instance_slot_create.argtypes = []
    f.ss_instance_slot_create.restype = P
    f.ss_instance_slot_destroy.argtypes = [P]
    f.ss_instance_slot_destroy.restype = None
    f.ss_instance_slot_reset.argtypes = [P]
    f.ss_instance_slot_reset.restype = None
    f.ss_instance_slot_step.argtypes = [
        P, ss_event_instance_info, P, C.c_float, C.c_float, C.c_float, C.c_bool]
    f.ss_instance_slot_step.restype = ss_instance_step_result
    f.ss_instance_slot_is_independent.argtypes = [P]
    f.ss_instance_slot_is_independent.restype = C.c_bool

    f.ss_runtime_get_active_event_instance.argtypes = [P, C.c_uint32]
    f.ss_runtime_get_active_event_instance.restype = ss_event_instance_info
    f.ss_runtime_get_active_effect_event.argtypes = [P, C.c_uint32]
    f.ss_runtime_get_active_effect_event.restype = ss_effect_event_info


def load_library(path: str | None = None, base_dir: str | None = None,
                 *, log: bool = False) -> C.CDLL:
    """Load libssruntime, declare signatures, and optionally route logs.

    Pass ``path`` for an explicit library file, or ``base_dir`` to resolve it
    via :func:`default_library_path` (per-platform/arch layout). The returned
    ``CDLL`` is cached on the module so repeated calls reuse it.

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

    Mirrors the minimal lifecycle in the cold-start guide §5. Use as a context
    manager or call :meth:`close` explicitly. The ``copy`` resource strategy is
    the default and recommended path for v1.
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
        L.ss_context_set_coordinate_system(ctx, coordinate_system)
        L.ss_context_set_origin(ctx, origin)
        L.ss_context_set_unit(ctx, unit)
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
        """
        L = self._lib
        data = bytes(data)  # ensure an owned, immutable buffer (stable address)
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
            # and restore the previous handle + its backing bytes, which :455
            # already overwrote. Without the restore, ``self._ssab_bytes`` drops
            # the only reference to ``prev_bytes`` while the context may still
            # borrow it via ``prev_res`` -> use-after-free. (The happy path is
            # unchanged; this only runs on the rare bind failure.)
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
        self._lib.ss_runtime_pause(self._ctx)

    def stop(self):
        self._lib.ss_runtime_stop(self._ctx)

    def set_loop(self, loops: int):
        self._lib.ss_runtime_set_loop(self._ctx, loops)
        return self

    def set_animation_speed(self, rate: float):
        self._lib.ss_runtime_set_animation_speed(self._ctx, rate)

    def set_frame_no(self, frame: float):
        self._lib.ss_runtime_set_frame_no(self._ctx, frame)

    def play_with_start_frame(self, frame: float):
        """Start playback from ``frame`` (docs/06 §1, ``play(startFrame)``)."""
        self._lib.ss_runtime_play_with_start_frame(self._ctx, float(frame))
        return self

    def set_frame_rate(self, fps: int):
        self._lib.ss_runtime_set_frame_rate(self._ctx, int(fps))

    def set_animation_section(self, start: int, end: int):
        """Limit playback/loop to ``[start, end]`` (docs/06 §4 set_animation_section)."""
        self._lib.ss_runtime_set_animation_section(self._ctx, int(start), int(end))

    def set_playback_direction(self, direction: int, style: int = STYLE_NORMAL):
        """``direction`` = PLAY_FORWARD/REVERSE; ``style`` = STYLE_NORMAL/PINGPONG."""
        self._lib.ss_runtime_set_playback_direction(
            self._ctx, int(direction), int(style))

    def update(self, dt_seconds: float) -> float:
        """Advance by ``dt_seconds`` **seconds**; returns current frame (float).

        NOTE: the underlying C-API ``ss_runtime_update`` takes **milliseconds**
        (see ``docs/06_playback_control`` — the cold-start guide §5/§6.2 wrongly
        says seconds). Ren'Py hands us ``st``/``at`` in seconds, so this wrapper
        takes seconds and converts. Use :meth:`update_ms` for the raw ms call.
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
    def is_playing(self) -> bool:
        return bool(self._lib.ss_runtime_is_playing(self._ctx))

    @property
    def is_pausing(self) -> bool:
        return bool(self._lib.ss_runtime_is_pausing(self._ctx))

    @property
    def is_end_frame_reached(self) -> bool:
        return bool(self._lib.ss_runtime_is_end_frame_reached(self._ctx))

    @property
    def is_looped(self) -> bool:
        """True if the last :meth:`update` crossed a loop boundary (per-update)."""
        return bool(self._lib.ss_runtime_is_looped(self._ctx))

    @property
    def is_playing_forward(self) -> bool:
        """True when the head is advancing forward on the timeline.

        Accounts for the Backward direction setting and the current ping-pong
        leg (往路/復路) but NOT the animation-speed sign — callers that support a
        negative speed must XOR that in (docs/00). Assumes forward when the
        native runtime does not export the query (older builds)."""
        fn = getattr(self._lib, "ss_runtime_is_playing_forward", None)
        if fn is None:
            return True
        try:
            return bool(fn(self._ctx))
        except Exception:
            return True

    @property
    def fps(self) -> int:
        return int(self._lib.ss_runtime_get_fps(self._ctx))

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
    def remain_loops(self) -> int:
        return int(self._lib.ss_runtime_get_remain_loops(self._ctx))

    # -- events (see ss_renpy.events) -------------------------------------
    def passed_event_count(self) -> int:
        """Number of timeline events the last :meth:`update` passed through."""
        return int(self._lib.ss_runtime_get_passed_event_count(self._ctx))

    def passed_event_index(self, i: int) -> int:
        """Index of the ``i``-th passed event into the animation's events vector.

        Resolve it with :class:`ss_renpy.events.EventResolver`.
        """
        return int(self._lib.ss_runtime_get_passed_event_index(self._ctx, i))

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

    # -- Mesh(deform) SoA buffers (docs/08 §4) ----------------------------
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

    # -- Instance / Effect slots (docs/08 "Instance / Effect") ------------
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

    def instance_slot_step(self, slot, ev, child_ctx, previous_child_frame,
                           parent_frame, delta_seconds, parent_looped):
        """Drive one instance slot a tick; returns ``ss_instance_step_result``.

        ``child_ctx`` is the *child* runtime's context pointer; ``ev`` an
        :class:`ss_event_instance_info` from :meth:`active_event_instance` on
        the *parent*. ``previous_child_frame`` is the child's raw float head
        before this tick (loop-edge detection only) — never floor it.
        """
        return self._lib.ss_instance_slot_step(
            slot, ev, child_ctx, float(previous_child_frame),
            float(parent_frame), float(delta_seconds), bool(parent_looped))

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
                              parent_looped, y_flip, vert_stride):
        return self._lib.ss_effect_slot_step(
            slot, ev, float(parent_frame), float(delta_seconds), float(fps),
            bool(parent_looped), bool(y_flip), int(vert_stride))

    def effect_slot_step(self, slot, ev, parent_frame, delta_seconds, fps,
                         parent_looped, y_flip=True, vert_stride=2):
        """Advance one effect slot (docs/08 §2).

        Returns ``(visible, draw_plan_bytes)``: the ``EffectDrawPlan``
        FlatBuffer is copied out immediately (the raw pointer is valid only
        until the next call on this slot). ``ev`` is an
        :class:`ss_effect_event_info` from :meth:`active_effect_event`.
        ``y_flip=True`` / ``vert_stride=2`` suit a 2D Y-down host (Ren'Py).
        Prefer :meth:`effect_slot_step_view` on the hot path to skip the copy.
        """
        r = self._effect_slot_step_raw(slot, ev, parent_frame, delta_seconds,
                                       fps, parent_looped, y_flip, vert_stride)
        if not r.visible or not r.draw_plan_buf or r.draw_plan_len == 0:
            return (bool(r.visible), b"")
        return (True, C.string_at(r.draw_plan_buf, r.draw_plan_len))

    def effect_slot_step_view(self, slot, ev, parent_frame, delta_seconds, fps,
                              parent_looped, y_flip=True, vert_stride=2):
        """Like :meth:`effect_slot_step` but returns a zero-copy view.

        ``(visible, draw_plan_view)`` where ``draw_plan_view`` is a read-only
        ``memoryview`` aliasing the slot's internal buffer — valid only until the
        next ``step`` on the **same** slot (ssruntime.h §27-37).
        ``effectplan.build_effect_batches`` drains it into Python lists in a
        single pass, so per-call use is safe; never retain the view past that
        call. Mirrors SSPlayerForUnity's zero-copy effect ``Append``.
        """
        r = self._effect_slot_step_raw(slot, ev, parent_frame, delta_seconds,
                                       fps, parent_looped, y_flip, vert_stride)
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

