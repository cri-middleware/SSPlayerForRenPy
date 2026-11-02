"""WebAssembly/JS bindings for libssruntime ("Brain").

This module provides `_WebRuntime`, a drop-in replacement for `_NativeRuntime`
that operates on the Web platform (Ren'Py Web) by communicating with the JS API
of the SDK's `ssruntime-ffi` wasm-bindgen build, via Ren'Py's `emscripten` module, and
`load_library`, which loads that build out of the game's own files.

What a frame hands back — the FrameData FlatBuffer, the SoA buffers, an
effect's draw plan — crosses as one copy from the Brain's wasm memory straight
into arrays this module owns, at the address ``array.buffer_info`` gives. A
string crossing (base64, or a file on the emscripten FS) costs more than the
Brain's own evaluation of the frame.
"""

from __future__ import annotations

import sys
import array
import json
import math

try:
    import emscripten
except ImportError:
    emscripten = None

# Every Python value spliced into a script goes through int(), _jsnum, _jsstr
# or "true"/"false" first, the coercions the native bridge's ctypes argtypes
# make. A bare True / None / nan is an undefined identifier in JS, and the
# ReferenceError aborts the frame where native would have coerced or raised.


def _jsnum(x) -> str:
    """Format a float as a JS-safe numeric literal.

    A bare ``nan``/``inf`` produced by an f-string is an *identifier* in JS and
    raises ReferenceError when the script is eval'd — before any in-script guard
    can run, and a JS throw cannot be caught across the emscripten boundary.
    Emitting ``NaN``/``Infinity`` instead lets a non-finite frame/delta degrade
    gracefully (the Brain treats it as out-of-range, matching the native path)
    rather than crash the frame.
    """
    x = float(x)
    if x != x:
        return "NaN"
    if x == math.inf:
        return "Infinity"
    if x == -math.inf:
        return "-Infinity"
    return repr(x)


def _jsstr(s) -> str:
    """Format a str as a JS string literal.

    ``json.dumps`` escapes quotes, backslashes and line breaks, and every
    non-ASCII character as well, so a name can neither end the literal early
    nor inject into the eval'd source. Anything but a str raises, as the native
    bridge's ``name.encode()`` does, instead of reaching the Brain as ``null``.
    """
    if not isinstance(s, str):
        raise TypeError("expected a str, not %s" % type(s).__name__)
    return json.dumps(s)


# The SoA buffers a frame copies across, in the order of ``ss_bufs[id].soa``:
# the JS getter stem (``<stem>_buf`` / ``<stem>_len``, both in elements of
# 4 bytes) and the array typecode the Python side reads them with.
_SOA = (
    ("get_world_matrices", "f"),
    ("get_local_vertices", "f"),
    ("get_local_uvs", "f"),
    ("get_cell_meta", "f"),
    ("get_mesh_vertices_x", "f"),
    ("get_mesh_vertices_y", "f"),
    ("get_mesh_uvs", "f"),
    ("get_mesh_indices", "i"),
    ("get_mesh_vertex_offsets", "I"),
    ("get_mesh_index_offsets", "I"),
    ("get_shape_vertices", "f"),
    ("get_shape_vertex_box_coords", "f"),
    ("get_shape_vertex_counts", "i"),
)

# Per-frame calls take their numbers through ``args`` (a float64 array this
# side owns) rather than spliced into the source: V8 caches an eval by its
# source, so a source that stays the same frame after frame is not compiled
# again. args[0..2] are a call's inputs, args[3] the result of an update.
_JS_HELPERS = ("window.ss_soa_stems = [%s];\n"
               % ", ".join("'%s'" % stem for stem, _ in _SOA)) + """
    if (!window.ss_bufs) window.ss_bufs = {};

    // Copy the frame ss_bufs[id].lens describes into the registered buffers.
    // A buffer too small for its part is skipped and reported (false); Python
    // grows it and calls this again — the pointers are pure reads, so the
    // frame is not evaluated a second time.
    window.ss_copy_frame = function (id) {
        var b = window.ss_bufs[id], c = window.ss_ctxs[id], n = b.lens;
        var heap = Module.HEAPU8, mem = window.ssruntime_wasm.memory.buffer;
        var fits = true;
        if (n[0] > 0) {
            if (n[0] <= b.frame[1]) heap.set(new Uint8Array(mem, c.get_frame_data_buf(), n[0]), b.frame[0]);
            else fits = false;
        }
        var stems = window.ss_soa_stems;
        for (var i = 0; i < stems.length; i++) {
            var bytes = n[i + 1] * 4;
            if (bytes > 0) {
                if (bytes <= b.soa[i][1]) heap.set(new Uint8Array(mem, c[stems[i] + '_buf'](), bytes), b.soa[i][0]);
                else fits = false;
            }
        }
        return fits;
    };

    // Evaluate the frame at args[0] and copy it across. Returns the lengths,
    // "frame,soa0,soa1,...", with a leading '!' when a buffer was too small.
    window.ss_frame = function (id) {
        var b = window.ss_bufs[id], c = window.ss_ctxs[id];
        var frame_no = Module.HEAPF64[b.args >> 3], len = 0;
        // Out-of-range / NaN frame_no: the wasm-bindgen API THROWS
        // (SSRuntimeError::InvalidParameter) where the native C-API
        // silently returns a null buffer. Mirror native:
        // no frame data this tick (the frame's parts just don't draw).
        // The sub-frame Instance walk momentarily seeks past the child's
        // range edge, so without this the child throws every such tick.
        if (isFinite(frame_no)) {
            // `prepare_frame_data` is the one evaluation; the buffer
            // pointers and lengths read after it are pure reads.
            try { len = c.prepare_frame_data(frame_no); } catch (e) { len = 0; }
        }
        var n = [len], stems = window.ss_soa_stems;
        for (var i = 0; i < stems.length; i++) n.push(c[stems[i] + '_len']());
        b.lens = n;
        return (window.ss_copy_frame(id) ? '' : '!') + n.join(',');
    };

    window.ss_update = function (id) {
        var o = window.ss_bufs[id].args >> 3, a = Module.HEAPF64;
        a[o + 3] = window.ss_ctxs[id].update(a[o]);
    };

    // The step fetches the parent's active event itself and frees it once
    // the step, which only borrows it, returns.
    window.ss_instance_step = function (id, part, slot, child, looped) {
        var o = window.ss_bufs[id].args >> 3, a = Module.HEAPF64;
        var ev = window.ss_ctxs[id].get_active_event_instance(part);
        var s = window.ss_instances[slot];
        var visible = s.step(ev, window.ss_ctxs[child], a[o], a[o + 1], looped === 1);
        ev.free();
        // The getter's name varies by wasm-bindgen version.
        var independent = s.independent ? s.independent() : s.is_independent();
        // The speed rides along so reading it costs no eval of its own; a
        // build without the getter reads 1, the speed before any step.
        return (visible ? 1 : 0) + ',' + (s.transitioned() ? 1 : 0) + ',' +
            (independent ? 1 : 0) + ',' + s.child_frame_no() + ',' + (s.child_looped() ? 1 : 0) +
            ',' + (s.get_speed ? s.get_speed() : 1);
    };

    // The draw plan's length once copied, 0 for none, or -length when the
    // registered buffer is too small for it.
    window.ss_copy_plan = function (id, slot) {
        var b = window.ss_bufs[id], s = window.ss_effects[slot];
        var len = s.get_draw_plan_len();
        if (len <= 0) return 0;
        if (len > b.plan[1]) return -len;
        Module.HEAPU8.set(new Uint8Array(window.ssruntime_wasm.memory.buffer, s.get_draw_plan_buf(), len), b.plan[0]);
        return len;
    };

    window.ss_effect_step = function (id, part, slot, looped, y_flip, stride, draw) {
        var o = window.ss_bufs[id].args >> 3, a = Module.HEAPF64;
        var ev = window.ss_ctxs[id].get_active_effect_event(part);
        var s = window.ss_effects[slot];
        var visible = s.step(ev, a[o], a[o + 1], a[o + 2], looped === 1, y_flip === 1, stride, draw === 1);
        ev.free();
        return visible ? window.ss_copy_plan(id, slot) : 0;
    };
"""

_EMPTY_VIEW = memoryview(b"")


def _room_for(typecode: str, count: int) -> array.array:
    """A fresh array of ``count`` elements and half as many again, so a buffer
    that creeps up frame by frame does not grow on every one of them."""
    return array.array(typecode,
                       bytes(array.array(typecode).itemsize * (count + count // 2)))


class _InstanceStepResult:
    """One Instance slot step: the fields of the native ``ss_instance_step_result``."""

    __slots__ = ("visible", "transitioned", "independent", "child_frame_no",
                 "child_looped")

    def __init__(self, visible, transitioned, independent, child_frame_no,
                 child_looped):
        self.visible = visible
        self.transitioned = transitioned
        self.independent = independent
        self.child_frame_no = child_frame_no
        self.child_looped = child_looped


def load_library(path=None, base_dir=None, *, timeout=10.0):
    """Load the Brain's wasm-bindgen module out of the game's own files.

    ``path`` is the folder holding ``ssruntime.js`` and ``ssruntime_bg.wasm``;
    ``base_dir`` resolves it the way the native loader does, as ``<base_dir>/web``.
    Both files ship inside ``game.zip`` and so are on the emscripten filesystem,
    where the page can read them but a browser ``import`` cannot: the glue is
    imported from a Blob URL and handed the wasm bytes, which is what spares the
    exported ``index.html`` any edit and the export any extra file. Every binding
    below reaches the module through ``window.ssruntime`` / ``window.ssruntime_wasm``.

    The import is asynchronous, so this sleeps until it settles — a few
    milliseconds — and returns ``True`` once the module is live: there is no
    Python-side handle, the module lives on ``window``. A failure raises, as the
    native loader's does, rather than leave the first player to hit a JS
    ``TypeError`` that cannot be caught across the emscripten boundary.
    """
    import time
    web_dir = path or (base_dir.rstrip("/") + "/web")
    emscripten.run_script(f"""
        if (!window.ss_runtime_state) {{
            window.ss_runtime_state = 'loading';
            (async function () {{
                // An emscripten FS error carries only a name and an errno, so
                // the message says which step failed as well as how.
                var step = 'reading ssruntime.js';
                try {{
                    var dir = {json.dumps(web_dir)};
                    var js = FS.readFile(dir + '/ssruntime.js', {{ encoding: 'utf8' }});
                    step = 'reading ssruntime_bg.wasm';
                    var wasm = FS.readFile(dir + '/ssruntime_bg.wasm');
                    step = 'importing ssruntime.js';
                    var url = URL.createObjectURL(new Blob([js], {{ type: 'text/javascript' }}));
                    var ss;
                    try {{ ss = await import(url); }} finally {{ URL.revokeObjectURL(url); }}
                    step = 'instantiating ssruntime_bg.wasm';
                    window.ssruntime_wasm = await ss.default({{ module_or_path: wasm }});
                    window.ssruntime = ss;
                    window.ss_runtime_state = 'ready';
                }} catch (e) {{
                    var why = (e && e.message) ||
                        (e && e.errno !== undefined ? e.name + ' errno ' + e.errno : String(e));
                    window.ss_runtime_state = 'failed ' + step + ': ' + why;
                }}
            }})();
        }}
    """)
    # A reload re-runs init in the same page and finds the module already live.
    deadline = time.time() + timeout
    state = emscripten.run_script_string("window.ss_runtime_state")
    while state == "loading" and time.time() < deadline:
        emscripten.sleep(0)
        state = emscripten.run_script_string("window.ss_runtime_state")
    if state != "ready":
        raise RuntimeError("ss: cannot load the web runtime from %s — %s"
                           % (web_dir, state if state != "loading" else
                              "still loading after %gs" % timeout))
    return True


class _WebRuntime:
    """One animation context bound to one resource (.ssab) via JS/WASM.

    This class mirrors the interface of `_NativeRuntime` but uses Ren'Py's
    `emscripten` module to call the SSPlayerForWeb JavaScript API.
    """

    _handle_counter = 0

    def __init__(self, lib=None):
        if emscripten is None:
            raise RuntimeError("emscripten module is missing. Are you running on web?")

        self._ctx_id = _WebRuntime._handle_counter
        _WebRuntime._handle_counter += 1

        # Initialize Javascript side storage if not exists
        emscripten.run_script("""
            if (!window.ss_ctxs) window.ss_ctxs = {};
            if (!window.ss_resources) window.ss_resources = {};
            if (!window.ss_instances) window.ss_instances = {};
            if (!window.ss_effects) window.ss_effects = {};
            // Slot ids start at 1: the consumers (instance.py / effect.py) test
            // slot handles with truthiness (`if not slot`, `any(slots)`), so a
            // 0-based id would drop — and never free — the first slot created.
            if (!window.ss_instance_counter) window.ss_instance_counter = 1;
            if (!window.ss_effect_counter) window.ss_effect_counter = 1;
        """ + _JS_HELPERS)

        emscripten.run_script(f"""
            window.ss_ctxs[{self._ctx_id}] = new window.ssruntime.SSRuntimeContext();
        """)
        self._res = None
        self._frame_rate = None
        # Instance slot -> the speed its last step drove the child at.
        self._slot_speed = {}

        # Where every per-frame copy lands. Each buffer starts empty and is
        # replaced, never resized, when a frame needs more: a view handed out
        # earlier keeps the old array alive, and _register_buffers tells JS the
        # new address before anything is copied into it.
        self._args = array.array("d", bytes(8 * 4))
        self._frame_buf = array.array("B")
        self._soa = [array.array(typecode) for _, typecode in _SOA]
        self._soa_len = [0] * len(_SOA)
        self._plan_buf = array.array("B")
        self._register_buffers()
        self._js_update = "window.ss_update(%d)" % self._ctx_id
        self._js_frame = "window.ss_frame(%d)" % self._ctx_id

    def _register_buffers(self):
        """Hand JS the address and size in bytes of each buffer it copies into."""
        def at(a):
            return "[%d, %d]" % (a.buffer_info()[0], len(a) * a.itemsize)
        emscripten.run_script(
            "var prev = window.ss_bufs[%d] || {};"
            "window.ss_bufs[%d] = {args: %d, frame: %s, soa: [%s], plan: %s,"
            " lens: prev.lens};"
            % (self._ctx_id, self._ctx_id, self._args.buffer_info()[0],
               at(self._frame_buf), ", ".join(at(a) for a in self._soa),
               at(self._plan_buf)))

    def configure(self, *, render_mode=0, coordinate_system=1, origin=0, unit=0):
        # The JS coordinate-system / origin / unit setters take an enum and
        # throw on anything but 0 or 1, where the C-API reads 1 as Y-down /
        # top-left / normalized and any other value as the other one. Fold
        # the same way, so a stray value configures what native would.
        emscripten.run_script(f"""
            var ctx = window.ss_ctxs[{self._ctx_id}];
            ctx.set_render_mode({int(render_mode)});
            ctx.set_coordinate_system({1 if int(coordinate_system) == 1 else 0});
            ctx.set_origin({1 if int(origin) == 1 else 0});
            ctx.set_unit({1 if int(unit) == 1 else 0});
        """)
        return self

    def load_ssab_bytes(self, data: bytes, *, borrow: bool = True):
        """Bind ``data`` to the context as the animation resource.

        The pack is read straight out of this heap at the address
        ``array.buffer_info`` gives, as a frame is written into it, and the
        Brain keeps a copy of its own: ``borrow`` has no effect here, and
        nothing outlives the call on this side — no file on the emscripten
        FS, no second copy of the pack held here.

        A pack the Brain rejects — a schema-version mismatch, or bytes it
        cannot parse — raises RuntimeError with the Brain's reason, as the
        native bridge raises, and leaves the previous resource bound. The
        constructor throws on such a pack, so the throw is caught in the
        script: one that escaped would abort the frame instead.
        """
        buf = array.array("B", data)
        addr, n = buf.buffer_info()
        err = emscripten.run_script_string(f"""
            (function (ctx) {{
                var res;
                try {{
                    res = new window.ssruntime.SSRuntimeResource(
                        Module.HEAPU8.subarray({addr}, {addr + n}));
                }} catch (e) {{
                    return 'ss_resource_create failed: ' + ((e && e.message) || String(e));
                }}
                var bound = false;
                try {{ bound = ctx.bind_resource(res); }} catch (e) {{}}
                if (!bound) {{
                    res.free();
                    return 'ss_runtime_bind_resource failed';
                }}
                // Free the previous resource only once the new one is bound
                // (bind new, then destroy old, as native does): a re-load
                // that skipped it would leak the old pack's wasm-heap copy.
                var prev = window.ss_resources[{self._ctx_id}];
                window.ss_resources[{self._ctx_id}] = res;
                if (prev) prev.free();
                return '';
            }})(window.ss_ctxs[{self._ctx_id}])
        """)
        if err:
            raise RuntimeError(err)

        self._frame_rate = None
        self._res = True
        return self

    def load_ssab_file(self, path: str):
        with open(path, "rb") as fh:
            return self.load_ssab_bytes(fh.read())

    def setup_animation(self, name: str) -> bool:
        # The JS setup_animation THROWS on an unknown/invalid name where native
        # returns False; a JS throw cannot be caught across the emscripten
        # boundary (it aborts the frame), so catch it in JS and surface a real
        # bool.
        literal = _jsstr(name)
        self._frame_rate = None
        emscripten.run_script(f"""
            try {{
                window.ss_ctxs[{self._ctx_id}].setup_animation({literal});
                window.ss_setup_ok = true;
            }} catch (e) {{
                window.ss_setup_ok = false;
            }}
        """)
        return emscripten.run_script_int("window.ss_setup_ok ? 1 : 0") == 1

    def play(self):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].play();")
        return self

    def pause(self):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].pause();")

    def resume(self):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].resume();")

    def stop(self):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].stop();")

    def set_loop_count(self, loop_count: int):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].set_loop_count({int(loop_count)});")
        return self

    def set_speed_scale(self, rate: float):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].set_speed_scale({_jsnum(rate)});")

    def set_frame_no(self, frame: float):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].set_frame_no({_jsnum(frame)});")

    def play_with_start_frame(self, frame: float):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].play_with_start_frame({_jsnum(frame)});")
        return self

    def set_frame_rate(self, fps: int):
        fps = int(fps)
        self._frame_rate = None
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].set_frame_rate({fps});")

    def set_animation_section(self, start: int, end: int) -> bool:
        # The JS setter THROWS on a section it refuses where native returns
        # False; caught in JS, as setup_animation's is.
        return emscripten.run_script_int(
            f"(function(c){{try{{c.set_animation_section({int(start)}, {int(end)});"
            f"return 1;}}catch(e){{return 0;}}}})(window.ss_ctxs[{self._ctx_id}])") == 1

    def set_playback_direction(self, direction: int, style: int = 0):
        # WebPlaybackDirection / WebPlaybackStyle throw on anything but 0 or
        # 1; the C-API reads any non-zero as backward / ping-pong, so fold to
        # match.
        emscripten.run_script(
            f"window.ss_ctxs[{self._ctx_id}].set_playback_direction("
            f"{1 if int(direction) else 0}, {1 if int(style) else 0});")

    def set_skip_frames(self, skip: bool) -> None:
        """Toggle frame skipping (see the native wrapper). Feature-detected:
        an older wasm build simply keeps the runtime default."""
        emscripten.run_script(
            f"(function(c){{try{{if(c.set_skip_frames)"
            f"c.set_skip_frames({'true' if skip else 'false'});}}catch(e){{}}}})"
            f"(window.ss_ctxs[{self._ctx_id}])")

    def update(self, dt_seconds: float) -> float:
        return self.update_ms(dt_seconds * 1000.0)

    def update_ms(self, dt_ms: float) -> float:
        self._args[0] = dt_ms
        emscripten.run_script(self._js_update)
        return self._args[3]

    @property
    def frame_no(self) -> float:
        return float(emscripten.run_script_string(f"window.ss_ctxs[{self._ctx_id}].get_frame_no().toString()"))

    @property
    def speed_scale(self) -> float:
        """See :attr:`ss_renpy.ssruntime_native.SSRuntime.speed_scale`."""
        return float(emscripten.run_script_string(f"window.ss_ctxs[{self._ctx_id}].get_speed_scale().toString()"))

    @property
    def is_playing(self) -> bool:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].is_playing() ? 1 : 0") == 1

    @property
    def is_pausing(self) -> bool:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].is_pausing() ? 1 : 0") == 1

    @property
    def is_clock_playing(self) -> bool:
        """See the native wrapper. Feature-detected -> False on a build
        without the query, as the native wrapper reads it."""
        return self._mode_getter("is_clock_playing", 0) == 1

    @property
    def is_clock_pausing(self) -> bool:
        """See the native wrapper. Feature-detected -> False when absent."""
        return self._mode_getter("is_clock_pausing", 0) == 1

    @property
    def is_stack_in_motion(self) -> bool:
        """See the native wrapper. Feature-detected -> False when absent."""
        return self._mode_getter("is_stack_in_motion", 0) == 1

    @property
    def is_finished(self) -> bool:
        """True once every configured loop has played.

        Mirrors the native backend: a sticky state, so callers take its rising
        edge. Feature-detected in JS — it replaced the withdrawn
        ``is_end_frame_reached``, so a wasm build that predates it would throw a
        TypeError on every frame, and a JS throw cannot be caught across the
        emscripten boundary (it aborts the frame rather than raising in Python).
        Absent -> False, matching the native wrapper: completion never fires,
        but playback survives."""
        return emscripten.run_script_int(
            f"(function(c){{try{{return (c.is_finished && c.is_finished())?1:0;}}"
            f"catch(e){{return 0;}}}})(window.ss_ctxs[{self._ctx_id}])") == 1

    @property
    def just_looped(self) -> bool:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].just_looped() ? 1 : 0") == 1

    @property
    def is_playing_forward(self) -> bool:
        """Whether the head advances forward (direction + ping-pong leg).

        Feature-detected like is_finished above: an older wasm build may not
        export it, and the resulting JS TypeError would be uncatchable. Absent
        -> True (assume forward), matching the native wrapper."""
        return emscripten.run_script_int(
            f"(function(c){{try{{return (!c.is_playing_forward || "
            f"c.is_playing_forward())?1:0;}}catch(e){{return 1;}}}})"
            f"(window.ss_ctxs[{self._ctx_id}])") == 1

    @property
    def playback_direction(self) -> int:
        """Configured direction (0 = forward, 1 = reverse); see the native
        wrapper. Feature-detected -> 0 on a build without the query."""
        return self._mode_getter("get_playback_direction", 0)

    @property
    def playback_style(self) -> int:
        """Configured style (0 = normal, 1 = ping-pong); -> 0 when absent."""
        return self._mode_getter("get_playback_style", 0)

    @property
    def skip_frames(self) -> bool:
        """Whether frame skipping is on (the runtime default) -> True when
        the query is absent."""
        return self._mode_getter("get_skip_frames", 1) == 1

    def _mode_getter(self, method: str, default: int) -> int:
        """Read an optional playback-mode query off the JS context.

        Feature-detected like is_playing_forward above: calling a method an
        older wasm build does not export raises an uncatchable JS TypeError,
        so the guard runs inside the script and returns ``default`` instead."""
        return emscripten.run_script_int(
            f"(function(c){{try{{return c.{method}?"
            f"(c.{method}()|0):{default};}}catch(e){{return {default};}}}})"
            f"(window.ss_ctxs[{self._ctx_id}])")

    @property
    def frame_rate(self) -> int:
        """Kept between calls: every Effect part reads it every frame, and the
        Brain changes it only through a new resource, setup_animation and
        set_frame_rate, each of which drops it here."""
        if self._frame_rate is None:
            self._frame_rate = emscripten.run_script_int(
                f"window.ss_ctxs[{self._ctx_id}].get_frame_rate()")
        return self._frame_rate

    @property
    def start_frame(self) -> int:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].get_start_frame()")

    @property
    def end_frame(self) -> int:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].get_end_frame()")

    @property
    def total_frames(self) -> int:
        return max(0, self.end_frame - self.start_frame + 1)

    @property
    def remaining_loops(self) -> int:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].get_remaining_loops()")

    def passed_event_count(self) -> int:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].get_passed_event_count()")

    def passed_event_index(self, i: int) -> int:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].get_passed_event_index({int(i)})")

    def passed_event_source_handle(self, i: int):
        """See the native wrapper. None on a build without the export."""
        return self._mix_handle("get_passed_event_source_handle(%d)" % int(i))

    # -- animation mixing (the track stack) -------------------------------
    # Mirrors _NativeRuntime's wrappers. The wasm-bindgen setters THROW where
    # the C-API returns false, its getters return undefined where the C-API
    # returns a sentinel, and an older build may not export them at all; a JS
    # throw cannot be caught across the emscripten boundary, so every call runs
    # inside a try in JS and comes back as a bool, or a value / None.
    def _mix_set(self, js_call: str) -> bool:
        return emscripten.run_script_int(
            f"(function(c){{try{{c.{js_call};return 1;}}catch(e){{return 0;}}}})"
            f"(window.ss_ctxs[{self._ctx_id}])") == 1

    def _mix_get(self, js_call: str):
        """The call's value as a float (a bool for a bool), or None.

        Numbers cross as String(v) rather than JSON: JSON writes Infinity --
        the outgoing event threshold's default -- as null."""
        s = emscripten.run_script_string(
            f"(function(c){{try{{var v=c.{js_call};"
            f"return (v===undefined||v===null)?'':String(v);}}"
            f"catch(e){{return '';}}}})(window.ss_ctxs[{self._ctx_id}])")
        if s in ("", "NaN"):
            return None
        if s in ("true", "false"):
            return s == "true"
        return float(s)

    def _mix_int(self, js_call: str):
        v = self._mix_get(js_call)
        return None if v is None else int(v)

    def _mix_handle(self, js_call: str):
        v = self._mix_int(js_call)
        return None if v is None or v == 0xFFFFFFFF else v

    def set_track_animation(self, track: int, name: str) -> bool:
        call = "set_track_animation(%d, %s)" % (int(track), _jsstr(name))
        self._frame_rate = None     # track 0's animation may change
        return self._mix_set(call)

    def track_count(self) -> int:
        return self._mix_int("get_track_count()") or 0

    def clear_track(self, track: int) -> bool:
        return self._mix_set("clear_track(%d)" % int(track))

    def set_track_alpha(self, track: int, alpha: float) -> bool:
        return self._mix_set("set_track_alpha(%d, %s)" % (int(track), _jsnum(alpha)))

    def track_alpha(self, track: int):
        return self._mix_get("get_track_alpha(%d)" % int(track))

    def set_track_blend(self, track: int, blend: int) -> bool:
        return self._mix_set("set_track_blend(%d, %d)" % (int(track), int(blend)))

    def track_blend(self, track: int):
        return self._mix_int("get_track_blend(%d)" % int(track))

    def set_track_sync(self, track: int, sync: int) -> bool:
        return self._mix_set("set_track_sync(%d, %d)" % (int(track), int(sync)))

    def track_sync(self, track: int):
        return self._mix_int("get_track_sync(%d)" % int(track))

    def set_track_frame(self, track: int, frame: float) -> bool:
        return self._mix_set("set_track_frame(%d, %s)" % (int(track), _jsnum(frame)))

    def track_frame(self, track: int):
        return self._mix_get("get_track_frame(%d)" % int(track))

    def set_track_speed(self, track: int, speed: float) -> bool:
        return self._mix_set("set_track_speed(%d, %s)" % (int(track), _jsnum(speed)))

    def track_speed(self, track: int):
        return self._mix_get("get_track_speed(%d)" % int(track))

    def set_track_frame_rate(self, track: int, fps: int) -> bool:
        self._frame_rate = None
        return self._mix_set("set_track_frame_rate(%d, %d)" % (int(track), int(fps)))

    def track_frame_rate(self, track: int):
        return self._mix_int("get_track_frame_rate(%d)" % int(track))

    def set_track_skip_frames(self, track: int, skip: bool) -> bool:
        return self._mix_set("set_track_skip_frames(%d, %s)"
                             % (int(track), "true" if skip else "false"))

    def track_skip_frames(self, track: int) -> bool:
        return bool(self._mix_get("get_track_skip_frames(%d)" % int(track)))

    def set_track_playback_direction(self, track: int, direction: int,
                                     style: int = 0) -> bool:
        # WebPlaybackDirection / WebPlaybackStyle are 0 / 1 in JS; the C-API
        # reads any non-zero as backward / ping-pong, so fold to match.
        return self._mix_set("set_track_playback_direction(%d, %d, %d)"
                             % (int(track), 1 if int(direction) else 0,
                                1 if int(style) else 0))

    def track_playback_direction(self, track: int):
        return self._mix_int("get_track_playback_direction(%d)" % int(track))

    def track_playback_style(self, track: int):
        return self._mix_int("get_track_playback_style(%d)" % int(track))

    def set_track_loop_count(self, track: int, count: int) -> bool:
        return self._mix_set("set_track_loop_count(%d, %d)" % (int(track), int(count)))

    def track_loop_count(self, track: int):
        return self._mix_int("get_track_loop_count(%d)" % int(track))

    def is_track_finished(self, track: int) -> bool:
        return bool(self._mix_get("is_track_finished(%d)" % int(track)))

    def track_just_looped(self, track: int) -> bool:
        return bool(self._mix_get("track_just_looped(%d)" % int(track)))

    def set_track_outgoing_event_threshold(self, track: int,
                                           threshold: float) -> bool:
        return self._mix_set("set_track_outgoing_event_threshold(%d, %s)"
                             % (int(track), _jsnum(threshold)))

    def track_outgoing_event_threshold(self, track: int):
        return self._mix_get("get_track_outgoing_event_threshold(%d)" % int(track))

    def crossfade(self, track: int, name: str, duration_ms: float) -> bool:
        call = ("crossfade(%d, %s, %s)"
                % (int(track), _jsstr(name), _jsnum(duration_ms)))
        self._frame_rate = None     # track 0's animation may change
        return self._mix_set(call)

    def fade_track(self, track: int, target_alpha: float,
                   duration_ms: float) -> bool:
        return self._mix_set("fade_track(%d, %s, %s)"
                             % (int(track), _jsnum(target_alpha), _jsnum(duration_ms)))

    def track_fade_progress(self, track: int):
        return self._mix_get("get_track_fade_progress(%d)" % int(track))

    def cancel_track_fade(self, track: int) -> bool:
        return self._mix_set("cancel_track_fade(%d)" % int(track))

    def track_main_source(self, track: int):
        return self._mix_handle("get_track_main_source(%d)" % int(track))

    def add_track_source(self, track: int, name: str, weight: float):
        return self._mix_handle("add_track_source(%d, %s, %s)"
                                % (int(track), _jsstr(name), _jsnum(weight)))

    def set_source_weight(self, handle: int, weight: float) -> bool:
        return self._mix_set("set_source_weight(%d, %s)" % (int(handle), _jsnum(weight)))

    def source_weight(self, handle: int):
        return self._mix_get("get_source_weight(%d)" % int(handle))

    def set_source_frame(self, handle: int, frame: float) -> bool:
        return self._mix_set("set_source_frame(%d, %s)" % (int(handle), _jsnum(frame)))

    def source_frame(self, handle: int):
        return self._mix_get("get_source_frame(%d)" % int(handle))

    def set_source_event_threshold(self, handle: int, threshold: float) -> bool:
        return self._mix_set("set_source_event_threshold(%d, %s)"
                             % (int(handle), _jsnum(threshold)))

    def source_event_threshold(self, handle: int):
        return self._mix_get("get_source_event_threshold(%d)" % int(handle))

    def source_animation_index(self, handle: int):
        return self._mix_int("get_source_animation_index(%d)" % int(handle))

    def get_frame_data(self, frame_no: float) -> bytes:
        return bytes(self.get_frame_data_view(frame_no))

    def get_frame_data_view(self, frame_no: float):
        """Read-only view of the FrameData FlatBuffer, valid until the next call.

        The same eval copies the frame's SoA buffers across, so the SoA
        accessors below read this frame's copy and make no call of their own.
        """
        self._args[0] = frame_no
        lens = emscripten.run_script_string(self._js_frame)
        if lens[0] == "!":
            lens = [int(n) for n in lens[1:].split(",")]
            self._make_room(lens)
            emscripten.run_script("window.ss_copy_frame(%d)" % self._ctx_id)
        else:
            lens = [int(n) for n in lens.split(",")]
        self._soa_len = lens[1:]
        if not lens[0]:
            return _EMPTY_VIEW
        return memoryview(self._frame_buf)[:lens[0]].toreadonly()

    def _make_room(self, lens):
        """Replace each buffer the frame did not fit, and register the new ones."""
        if lens[0] > len(self._frame_buf):
            self._frame_buf = _room_for("B", lens[0])
        for i, n in enumerate(lens[1:]):
            if n > len(self._soa[i]):
                self._soa[i] = _room_for(_SOA[i][1], n)
        self._register_buffers()

    def _soa_at(self, i):
        """``(array, count)`` for SoA buffer ``i`` of the last frame copied, or
        ``(None, 0)``. The array may hold more than ``count`` elements; like
        the native pointer, only the first ``count`` are this frame's."""
        n = self._soa_len[i]
        return (self._soa[i], n) if n else (None, 0)

    def world_matrices(self):
        return self._soa_at(0)

    def world_matrices_snapshot(self):
        """This frame's world matrices as an ``array('f')`` the caller owns;
        the buffer behind :meth:`world_matrices` is reused every frame."""
        wm, n = self._soa_at(0)
        return wm[:n] if n else array.array("f")

    def local_vertices(self):
        return self._soa_at(1)

    def local_uvs(self):
        return self._soa_at(2)

    def cell_meta(self):
        return self._soa_at(3)

    def mesh_vertices_x(self):
        return self._soa_at(4)

    def mesh_vertices_y(self):
        return self._soa_at(5)

    def mesh_uvs(self):
        return self._soa_at(6)

    def mesh_indices(self):
        return self._soa_at(7)

    def mesh_vertex_offsets(self):
        return self._soa_at(8)

    def mesh_index_offsets(self):
        return self._soa_at(9)

    def shape_vertices(self):
        return self._soa_at(10)

    def shape_vertex_box_coords(self):
        return self._soa_at(11)

    def shape_vertex_counts(self):
        return self._soa_at(12)

    @property
    def resource(self):
        return self._res

    @property
    def ctx(self):
        """Child-context identity for the Instance walk (mirrors _NativeRuntime.ctx).

        Native returns the raw context pointer; on web the equivalent handle is
        the JS-side ``window.ss_ctxs`` key. ``instance_slot_step`` accepts either
        a runtime with ``_ctx_id`` or a bare id, so returning the id is enough
        (without this, ``SSInternalPlayer.ctx`` raises AttributeError and nested
        Instance animations never step)."""
        return self._ctx_id

    # -- Override Layer (per-part runtime overrides) ----------------------
    # Mirrors _NativeRuntime's wrappers over the ss_runtime_*_override C-API.
    # The wasm-bindgen setters THROW on rejection where the C-API returns false,
    # and a JS throw cannot be caught across the emscripten boundary (it aborts
    # the frame) — so every call is wrapped in JS and surfaces a real bool, the
    # same shape as setup_animation above.
    def _override_call(self, js_call: str) -> bool:
        emscripten.run_script(f"""
            try {{
                window.ss_ctxs[{self._ctx_id}].{js_call};
                window.ss_override_ok = true;
            }} catch (e) {{
                window.ss_override_ok = false;
            }}
        """)
        return emscripten.run_script_int("window.ss_override_ok ? 1 : 0") == 1

    @property
    def supports_overrides(self) -> bool:
        """Whether the loaded wasm build exports the Override Layer at all."""
        return emscripten.run_script_int(
            f"(window.ss_ctxs[{self._ctx_id}].clear_all_part_overrides "
            f"? 1 : 0)") == 1

    def find_part_index(self, part_name: str) -> int:
        literal = _jsstr(part_name)
        emscripten.run_script(f"""
            try {{
                window.ss_part_idx = window.ss_ctxs[{self._ctx_id}].find_part_index({literal});
            }} catch (e) {{
                window.ss_part_idx = -1;
            }}
        """)
        return emscripten.run_script_int("window.ss_part_idx")

    def set_part_visibility_override(self, part: int, force: int,
                                     cascade: bool = False) -> bool:
        return self._override_call(
            "set_part_visibility_override(%d, %d, %s)"
            % (int(part), int(force), "true" if cascade else "false"))

    def clear_part_visibility_override(self, part: int) -> bool:
        return self._override_call(
            "clear_part_visibility_override(%d)" % int(part))

    def set_part_color_override(self, part: int, blend_op: int, rgba: int,
                                priority: int = 1) -> bool:
        return self._override_call(
            "set_part_color_override(%d, %d, %d, %d)"
            % (int(part), int(blend_op), int(rgba) & 0xFFFFFFFF, int(priority)))

    def set_part_color_override_corners(self, part: int, blend_op: int,
                                        corners_rgba, priority: int = 1) -> bool:
        corners = list(corners_rgba)
        if len(corners) != 4:
            return False
        # The binding takes a &[u32]; wasm-bindgen wants a real typed array.
        return self._override_call(
            "set_part_color_override_corners(%d, %d, new Uint32Array([%s]), %d)"
            % (int(part), int(blend_op),
               ", ".join(str(int(c) & 0xFFFFFFFF) for c in corners),
               int(priority)))

    def clear_part_color_override(self, part: int) -> bool:
        return self._override_call("clear_part_color_override(%d)" % int(part))

    def set_part_cell_override(self, part: int, cellmap_name_hash: int,
                               cell_name_hash: int, priority: int = 1) -> bool:
        return self._override_call(
            "set_part_cell_override(%d, %d, %d, %d)"
            % (int(part), int(cellmap_name_hash) & 0xFFFFFFFF,
               int(cell_name_hash) & 0xFFFFFFFF, int(priority)))

    def clear_part_cell_override(self, part: int) -> bool:
        return self._override_call("clear_part_cell_override(%d)" % int(part))

    def clear_all_part_overrides(self) -> bool:
        return self._override_call("clear_all_part_overrides()")

    def active_event_instance(self, slot_index: int):
        """The ``ev`` to hand :meth:`instance_slot_step`: here, the part index.

        The step's own eval fetches the event and frees it once the step,
        which only borrows it, returns — one eval per part fewer, and no wasm
        object left on ``window`` between the two calls."""
        return slot_index

    def active_effect_event(self, slot_index: int):
        """The ``ev`` to hand an effect step: here, the part index (see
        :meth:`active_event_instance`)."""
        return slot_index

    def instance_slot_create(self):
        emscripten.run_script("""
            var id = window.ss_instance_counter++;
            window.ss_instances[id] = window.ssruntime.SSRuntimeInstanceSlot.create();
            window.ss_tmp_id = id;
        """)
        return emscripten.run_script_int("window.ss_tmp_id")

    def instance_slot_destroy(self, slot):
        if slot is not None:
            self._slot_speed.pop(slot, None)
            emscripten.run_script("window.ss_instances[%d].free(); delete window.ss_instances[%d];"
                                  % (slot, slot))

    def instance_slot_reset(self, slot):
        if slot is not None:
            emscripten.run_script("window.ss_instances[%d].reset();" % slot)

    def instance_slot_step(self, slot, ev, child_ctx, parent_frame,
                           delta_seconds, parent_looped):
        c_ctx_id = child_ctx._ctx_id if hasattr(child_ctx, "_ctx_id") else child_ctx
        self._args[0] = parent_frame
        self._args[1] = delta_seconds
        r = emscripten.run_script_string(
            "window.ss_instance_step(%d, %d, %d, %d, %d)"
            % (self._ctx_id, ev, slot, c_ctx_id, 1 if parent_looped else 0)
        ).split(",")
        self._slot_speed[slot] = float(r[5])
        return _InstanceStepResult(r[0] == "1", r[1] == "1", r[2] == "1",
                                   float(r[3]), r[4] == "1")

    def instance_slot_get_speed(self, slot):
        """See :meth:`ss_renpy.ssruntime_native.SSRuntime.instance_slot_get_speed`.
        Kept from the last :meth:`instance_slot_step`, which reads it."""
        return self._slot_speed.get(slot, 1.0)

    def instance_slot_is_independent(self, slot):
        # Guard the getter name (it varies by wasm-bindgen version, like step()
        # at instance_slot_step) so a JS TypeError can't unwind the emscripten
        # boundary — such a throw is NOT a Python exception and could not be
        # caught by the caller.
        return emscripten.run_script_int(
            "(function(s){return (s.is_independent?s.is_independent():(s.independent?s.independent():false))?1:0;})(window.ss_instances[%d])"
            % slot) == 1

    def effect_slot_create(self, effect_name_hash, seed=0):
        if not self._res:
            return None
        emscripten.run_script(f"""
            var id = window.ss_effect_counter++;
            try {{
                window.ss_effects[id] = window.ssruntime.SSRuntimeEffectSlot.create(window.ss_resources[{self._ctx_id}], {int(effect_name_hash) & 0xFFFFFFFF}, {int(seed) & 0xFFFFFFFF});
                window.ss_tmp_id = id;
            }} catch(e) {{
                window.ss_tmp_id = -1;
            }}
        """)
        id = emscripten.run_script_int("window.ss_tmp_id")
        return id if id != -1 else None

    def effect_slot_destroy(self, slot):
        if slot is not None:
            emscripten.run_script("window.ss_effects[%d].free(); delete window.ss_effects[%d];"
                                  % (slot, slot))

    def effect_slot_reset(self, slot):
        if slot is not None:
            emscripten.run_script("window.ss_effects[%d].reset();" % slot)

    def effect_slot_step(self, slot, ev, parent_frame, delta_seconds, fps,
                         parent_looped, y_flip=True, vert_stride=2, *, draw):
        visible, plan = self.effect_slot_step_view(
            slot, ev, parent_frame, delta_seconds, fps, parent_looped,
            y_flip, vert_stride, draw=draw)
        return (visible, bytes(plan))

    def effect_slot_step_view(self, slot, ev, parent_frame, delta_seconds, fps,
                              parent_looped, y_flip=True, vert_stride=2, *,
                              draw):
        """``(visible, plan)``: a read-only view of the EffectDrawPlan, valid
        until the next effect step on this runtime — any slot of it, where the
        native view lasts until the next step of the same slot."""
        self._args[0] = parent_frame
        self._args[1] = delta_seconds
        self._args[2] = fps
        n = emscripten.run_script_int(
            "window.ss_effect_step(%d, %d, %d, %d, %d, %d, %d)"
            % (self._ctx_id, ev, slot, 1 if parent_looped else 0,
               1 if y_flip else 0, int(vert_stride), 1 if draw else 0))
        if n < 0:
            self._plan_buf = _room_for("B", -n)
            self._register_buffers()
            n = emscripten.run_script_int(
                "window.ss_copy_plan(%d, %d)" % (self._ctx_id, slot))
        if n <= 0:
            return (False, _EMPTY_VIEW)
        return (True, memoryview(self._plan_buf)[:n].toreadonly())

    def effect_slot_is_independent(self, slot):
        # Guard the getter name so a JS TypeError can't unwind the emscripten
        # boundary uncatchably (see instance_slot_is_independent).
        return emscripten.run_script_int(
            "(function(s){return (s.is_independent?s.is_independent():(s.independent?s.independent():false))?1:0;})(window.ss_effects[%d])"
            % slot) == 1

    def close(self):
        if hasattr(self, '_ctx_id') and emscripten:
            emscripten.run_script(f"""
                if (window.ss_ctxs && window.ss_ctxs[{self._ctx_id}]) {{
                    window.ss_ctxs[{self._ctx_id}].free();
                    delete window.ss_ctxs[{self._ctx_id}];
                }}
                if (window.ss_resources && window.ss_resources[{self._ctx_id}]) {{
                    window.ss_resources[{self._ctx_id}].free();
                    delete window.ss_resources[{self._ctx_id}];
                }}
                // The addresses point into this object's arrays, which go with it.
                if (window.ss_bufs) delete window.ss_bufs[{self._ctx_id}];
            """)
        self._res = None

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
