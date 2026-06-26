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


def platform_subdir() -> str:
    """Per-platform/arch subdirectory under the ``libs`` dir.

    Layout mirrors the SSPlayerForUnity plugin convention (``<platform>/<arch>``,
    macOS universal needs no arch split). Several platforms share a filename
    (Windows x64/arm64 both ``ssruntime.dll``; Linux both ``libssruntime.so``),
    so the directory disambiguates:

        macos/                 (universal arm64+x86_64 dylib)
        windows/x86_64  windows/arm64
        linux/x86_64    linux/arm64
        # reserved (separate Ren'Py integration): android/<abi>, ios/, web/
    """
    m = platform.machine().lower()
    if m in ("x86_64", "amd64", "x64"):
        arch = "x86_64"
    elif m in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = m or "unknown"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return os.path.join("windows", arch)
    return os.path.join("linux", arch)


def library_filename() -> str:
    if sys.platform.startswith("win"):
        return "ssruntime.dll"
    if sys.platform == "darwin":
        return "libssruntime.dylib"
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

    # events
    f.ss_runtime_get_passed_event_count.argtypes = [P]
    f.ss_runtime_get_passed_event_count.restype = C.c_int32
    f.ss_runtime_get_passed_event_index.argtypes = [P, C.c_int32]
    f.ss_runtime_get_passed_event_index.restype = C.c_int32

    # hashing helper (texture/animation name -> u32 fnv1a)
    f.ss_runtime_hash_string.argtypes = [C.c_char_p]
    f.ss_runtime_hash_string.restype = C.c_uint32


def load_library(path: str | None = None, base_dir: str | None = None,
                 *, log: bool = False) -> C.CDLL:
    """Load libssruntime, declare signatures, and optionally route logs.

    Pass ``path`` for an explicit library file, or ``base_dir`` to resolve it
    via :func:`default_library_path` (per-platform/arch layout). The returned
    ``CDLL`` is cached on the module so repeated calls reuse it.
    """
    global _LIB
    if path is None:
        path = default_library_path(base_dir)
    lib = C.CDLL(path)
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


class SSRuntime:
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

    def load_ssab_bytes(self, data: bytes):
        """Create a *copy* resource from ``data`` and bind it to the context."""
        L = self._lib
        self._ssab_bytes = data  # retain (copy resource doesn't need it, but cheap)
        self._res = L.ss_resource_create_copy(data, len(data))
        if not self._res:
            raise RuntimeError("ss_resource_create_copy failed")
        if not L.ss_runtime_bind_resource(self._ctx, self._res):
            raise RuntimeError("ss_runtime_bind_resource failed")
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
    def is_end_frame_reached(self) -> bool:
        return bool(self._lib.ss_runtime_is_end_frame_reached(self._ctx))

    @property
    def is_looped(self) -> bool:
        """True if the last :meth:`update` crossed a loop boundary (per-update)."""
        return bool(self._lib.ss_runtime_is_looped(self._ctx))

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
    def get_frame_data(self, frame_no: float) -> bytes:
        """Return the FrameData FlatBuffer for ``frame_no`` as a fresh bytes.

        The Brain returns a pointer valid only until the next call; we copy it
        out immediately so the caller can parse at leisure.
        """
        ptr = C.POINTER(C.c_ubyte)()
        length = C.c_size_t()
        self._lib.ss_runtime_get_frame_data(
            self._ctx, frame_no, C.byref(ptr), C.byref(length))
        if not ptr or length.value == 0:
            return b""
        return C.string_at(ptr, length.value)

    def _soa_float(self, getter):
        ptr = C.POINTER(C.c_float)()
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

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
