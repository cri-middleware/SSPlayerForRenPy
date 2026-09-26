"""WebAssembly/JS bindings for libssruntime ("Brain").

This module provides `_WebRuntime`, a drop-in replacement for `_NativeRuntime`
that operates on the Web platform (Ren'Py Web) by communicating with the JS API
of the SDK's `ssruntime-ffi` wasm-bindgen build, via `renpy.emscripten`, and
`load_library`, which loads that build out of the game's own files.
"""

from __future__ import annotations

import sys
import array
import math

try:
    import emscripten
except ImportError:
    emscripten = None


def _jsnum(x) -> str:
    """Format a float as a JS-safe numeric literal.

    A bare ``nan``/``inf`` produced by an f-string is an *identifier* in JS and
    raises ReferenceError when the script is eval'd — before any in-script guard
    (e.g. ``ss_get_frame_data_b64``'s ``isFinite`` check) can run, and a JS throw
    cannot be caught across the emscripten boundary. Emitting ``NaN``/``Infinity``
    instead lets a non-finite frame/delta degrade gracefully (the Brain treats it
    as out-of-range, matching the native path) rather than crash the frame.
    """
    x = float(x)
    if x != x:
        return "NaN"
    if x == math.inf:
        return "Infinity"
    if x == -math.inf:
        return "-Infinity"
    return repr(x)


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
    import json
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
            
            // Helper functions to speed up eval boundaries
            window.ss_base64_encode = function(buffer) {
                var binary = '';
                var bytes = new Uint8Array(buffer);
                var len = bytes.byteLength;
                for (var i = 0; i < len; i++) {
                    binary += String.fromCharCode(bytes[i]);
                }
                return window.btoa(binary);
            };
            window.ss_get_frame_data_b64 = function(ctx_id, frame_no) {
                var ctx = window.ss_ctxs[ctx_id];
                // Out-of-range / NaN frame_no: the wasm-bindgen API THROWS
                // (SSRuntimeError::InvalidParameter) where the native C-API
                // silently returns a null buffer. Mirror native:
                // no frame data this tick (the frame's parts just don't draw).
                // The sub-frame Instance walk momentarily seeks past the child's
                // range edge, so without this the child throws every such tick.
                if (!isFinite(frame_no)) return "";
                try {
                    // One evaluation: `prepare_frame_data` builds the frame and
                    // returns its length, and the buffer pointer is then a pure
                    // read. The old buf/len pair each ran a full evaluation, so
                    // this tick cost the Brain twice.
                    var len = ctx.prepare_frame_data(frame_no);
                    var ptr = ctx.get_frame_data_buf();
                    if (len > 0) {
                        var u8 = new Uint8Array(window.ssruntime_wasm.memory.buffer, ptr, len);
                        return window.ss_base64_encode(u8);
                    }
                } catch (e) {
                    return "";
                }
                return "";
            };
        """)

        emscripten.run_script(f"""
            window.ss_ctxs[{self._ctx_id}] = new window.ssruntime.SSRuntimeContext();
        """)
        self._res = None
        self._ssab_bytes = None

    def configure(self, *, render_mode=0, coordinate_system=1, origin=0, unit=0):
        emscripten.run_script(f"""
            var ctx = window.ss_ctxs[{self._ctx_id}];
            ctx.set_render_mode({render_mode});
            ctx.set_coordinate_system({coordinate_system});
            ctx.set_origin({origin});
            ctx.set_unit({unit});
        """)
        return self

    def load_ssab_bytes(self, data: bytes, *, borrow: bool = True):
        self._ssab_bytes = bytes(data)

        with open("/temp_ssab.bin", "wb") as f:
            f.write(data)

        emscripten.run_script(f"""
            var u8 = FS.readFile('/temp_ssab.bin');
            var res = new window.ssruntime.SSRuntimeResource(u8);
            var success = window.ss_ctxs[{self._ctx_id}].bind_resource(res);
            if (success) {{
                // Free the PREVIOUS resource only after the new one is bound
                // (native ordering: bind new -> destroy old). Otherwise a
                // re-load on this context leaks the old SSRuntimeResource, which
                // holds a full wasm-heap copy of the previous .ssab.
                var prev = window.ss_resources[{self._ctx_id}];
                window.ss_resources[{self._ctx_id}] = res;
                if (prev) prev.free();
            }} else {{
                res.free();
            }}
            window.ss_success = success;
        """)

        success = emscripten.run_script_int("window.ss_success ? 1 : 0")
        if not success:
            raise RuntimeError("ss_runtime_bind_resource failed")
            
        self._res = True
        return self

    def load_ssab_file(self, path: str):
        with open(path, "rb") as fh:
            return self.load_ssab_bytes(fh.read())

    def setup_animation(self, name: str) -> bool:
        import json
        # The JS setup_animation THROWS on an unknown/invalid name where native
        # returns False; a JS throw cannot be caught across the emscripten
        # boundary (it aborts the frame), so catch it in JS and surface a real
        # bool. json.dumps escapes the name into a valid JS string literal — a
        # raw name containing a quote / backslash / newline would otherwise break
        # or inject into the eval'd source.
        emscripten.run_script(f"""
            try {{
                window.ss_ctxs[{self._ctx_id}].setup_animation({json.dumps(name)});
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
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].set_loop_count({loop_count});")
        return self

    def set_speed_scale(self, rate: float):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].set_speed_scale({_jsnum(rate)});")

    def set_frame_no(self, frame: float):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].set_frame_no({_jsnum(frame)});")

    def play_with_start_frame(self, frame: float):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].play_with_start_frame({_jsnum(frame)});")
        return self

    def set_frame_rate(self, fps: int):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].set_frame_rate({fps});")

    def set_animation_section(self, start: int, end: int):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].set_animation_section({start}, {end});")

    def set_playback_direction(self, direction: int, style: int = 0):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].set_playback_direction({direction}, {style});")

    def set_skip_frames(self, skip: bool) -> None:
        """Toggle frame skipping (see the native wrapper). Feature-detected:
        an older wasm build simply keeps the runtime default."""
        emscripten.run_script(
            f"(function(c){{try{{if(c.set_skip_frames)"
            f"c.set_skip_frames({'true' if skip else 'false'});}}catch(e){{}}}})"
            f"(window.ss_ctxs[{self._ctx_id}])")

    def update(self, dt_seconds: float) -> float:
        return float(emscripten.run_script_string(f"window.ss_ctxs[{self._ctx_id}].update({_jsnum(dt_seconds * 1000.0)}).toString()"))

    def update_ms(self, dt_ms: float) -> float:
        return float(emscripten.run_script_string(f"window.ss_ctxs[{self._ctx_id}].update({_jsnum(dt_ms)}).toString()"))

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
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].get_frame_rate()")

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
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].get_passed_event_index({i})")

    def get_frame_data(self, frame_no: float) -> bytes:
        s = emscripten.run_script_string(f"window.ss_get_frame_data_b64({self._ctx_id}, {_jsnum(frame_no)})")
        if s:
            import base64
            return base64.b64decode(s)
        return b""

    def get_frame_data_view(self, frame_no: float):
        return memoryview(self.get_frame_data(frame_no))

    def _soa_array(self, type_char, func_buf, func_len, mult=4):
        emscripten.run_script(f"""
            var ctx = window.ss_ctxs[{self._ctx_id}];
            var ptr = ctx.{func_buf}();
            var len = ctx.{func_len}();
            if (len > 0) {{
                var u8 = new Uint8Array(window.ssruntime_wasm.memory.buffer, ptr, len * {mult});
                FS.writeFile('/temp_soa.bin', u8);
            }} else {{
                FS.writeFile('/temp_soa.bin', new Uint8Array(0));
            }}
            window.ss_tmp_len = len;
        """)
        length = emscripten.run_script_int("window.ss_tmp_len")
        if length == 0:
            return None, 0
        try:
            with open('/temp_soa.bin', 'rb') as f:
                arr = array.array(type_char)
                arr.fromfile(f, length)
                return arr, length
        except FileNotFoundError:
            return None, 0

    def _soa_float(self, func_buf, func_len):
        return self._soa_array('f', func_buf, func_len)

    def _soa_int32(self, func_buf, func_len):
        return self._soa_array('i', func_buf, func_len)

    def _soa_uint32(self, func_buf, func_len):
        return self._soa_array('I', func_buf, func_len)

    def world_matrices(self):
        return self._soa_float("get_world_matrices_buf", "get_world_matrices_len")

    def local_vertices(self):
        return self._soa_float("get_local_vertices_buf", "get_local_vertices_len")

    def local_uvs(self):
        return self._soa_float("get_local_uvs_buf", "get_local_uvs_len")

    def cell_meta(self):
        return self._soa_float("get_cell_meta_buf", "get_cell_meta_len")

    def mesh_vertices_x(self):
        return self._soa_float("get_mesh_vertices_x_buf", "get_mesh_vertices_x_len")

    def mesh_vertices_y(self):
        return self._soa_float("get_mesh_vertices_y_buf", "get_mesh_vertices_y_len")

    def mesh_uvs(self):
        return self._soa_float("get_mesh_uvs_buf", "get_mesh_uvs_len")

    def mesh_indices(self):
        return self._soa_int32("get_mesh_indices_buf", "get_mesh_indices_len")

    def mesh_vertex_offsets(self):
        return self._soa_uint32("get_mesh_vertex_offsets_buf", "get_mesh_vertex_offsets_len")

    def mesh_index_offsets(self):
        return self._soa_uint32("get_mesh_index_offsets_buf", "get_mesh_index_offsets_len")

    def shape_vertices(self):
        return self._soa_float("get_shape_vertices_buf", "get_shape_vertices_len")

    def shape_vertex_box_coords(self):
        return self._soa_float("get_shape_vertex_box_coords_buf", "get_shape_vertex_box_coords_len")

    def shape_vertex_counts(self):
        return self._soa_int32("get_shape_vertex_counts_buf", "get_shape_vertex_counts_len")

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
        import json
        emscripten.run_script(f"""
            try {{
                window.ss_part_idx = window.ss_ctxs[{self._ctx_id}].find_part_index({json.dumps(part_name)});
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

    # Active-event fetch (state kept on the JS side; step() consumes it)
    def active_event_instance(self, slot_index: int):
        # get_active_event_instance allocates a fresh WebEventInstanceInfo on the
        # wasm heap each call, and the matching step() borrows (does not move/free)
        # it — so free the PREVIOUS one before overwriting the global, else every
        # frame leaks one object until the FinalizationRegistry runs. The prior
        # value has already been consumed by its step by the time we get here.
        # (__wbg_ptr guard avoids a double-free if it was already freed.)
        s = emscripten.run_script_string(f"""
            if (window.ss_active_ev && window.ss_active_ev.__wbg_ptr) window.ss_active_ev.free();
            window.ss_active_ev = window.ss_ctxs[{self._ctx_id}].get_active_event_instance({slot_index});
            if (!window.ss_active_ev) "null"; else "ok";
        """)
        if s == "null": return None
        return "ok"

    def active_effect_event(self, slot_index: int):
        # See active_event_instance: free the previous per-frame WebEffectEventInfo
        # before overwriting the global so playback doesn't leak one object/frame.
        s = emscripten.run_script_string(f"""
            if (window.ss_active_effect_ev && window.ss_active_effect_ev.__wbg_ptr) window.ss_active_effect_ev.free();
            window.ss_active_effect_ev = window.ss_ctxs[{self._ctx_id}].get_active_effect_event({slot_index});
            if (!window.ss_active_effect_ev) "null"; else "ok";
        """)
        if s == "null": return None
        return "ok"

    def instance_slot_create(self):
        emscripten.run_script("""
            var id = window.ss_instance_counter++;
            window.ss_instances[id] = window.ssruntime.SSRuntimeInstanceSlot.create();
            window.ss_tmp_id = id;
        """)
        return emscripten.run_script_int("window.ss_tmp_id")

    def instance_slot_destroy(self, slot):
        if slot is not None:
            emscripten.run_script(f"window.ss_instances[{slot}].free(); delete window.ss_instances[{slot}];")

    def instance_slot_reset(self, slot):
        if slot is not None:
            emscripten.run_script(f"window.ss_instances[{slot}].reset();")

    def instance_slot_step(self, slot, ev, child_ctx, parent_frame,
                           delta_seconds, parent_looped):
        c_ctx_id = child_ctx._ctx_id if hasattr(child_ctx, "_ctx_id") else child_ctx
        
        s = emscripten.run_script_string(f"""
            var js_ev = window.ss_active_ev;
            var slot = window.ss_instances[{slot}];
            var visible = slot.step(js_ev, window.ss_ctxs[{c_ctx_id}], {_jsnum(parent_frame)}, {_jsnum(delta_seconds)}, {'true' if parent_looped else 'false'});
            
            JSON.stringify({{
                visible: visible,
                transitioned: slot.transitioned(),
                independent: slot.independent ? slot.independent() : slot.is_independent(),
                child_frame_no: slot.child_frame_no(),
                child_looped: slot.child_looped()
            }});
        """)
        import json
        res = json.loads(s)
        class _InstanceStepResult: pass
        r = _InstanceStepResult()
        r.visible = res["visible"]
        r.transitioned = res["transitioned"]
        r.independent = res["independent"]
        r.child_frame_no = res["child_frame_no"]
        r.child_looped = res["child_looped"]
        return r

    def instance_slot_is_independent(self, slot):
        # Guard the getter name (it varies by wasm-bindgen version, like step()
        # at instance_slot_step) so a JS TypeError can't unwind the emscripten
        # boundary — such a throw is NOT a Python exception and could not be
        # caught by the caller.
        return emscripten.run_script_int(
            f"(function(s){{return (s.is_independent?s.is_independent():(s.independent?s.independent():false))?1:0;}})(window.ss_instances[{slot}])") == 1

    def effect_slot_create(self, effect_name_hash, seed=0):
        if not self._res:
            return None
        emscripten.run_script(f"""
            var id = window.ss_effect_counter++;
            try {{
                window.ss_effects[id] = window.ssruntime.SSRuntimeEffectSlot.create(window.ss_resources[{self._ctx_id}], {effect_name_hash}, {seed});
                window.ss_tmp_id = id;
            }} catch(e) {{
                window.ss_tmp_id = -1;
            }}
        """)
        id = emscripten.run_script_int("window.ss_tmp_id")
        return id if id != -1 else None

    def effect_slot_destroy(self, slot):
        if slot is not None:
            emscripten.run_script(f"window.ss_effects[{slot}].free(); delete window.ss_effects[{slot}];")

    def effect_slot_reset(self, slot):
        if slot is not None:
            emscripten.run_script(f"window.ss_effects[{slot}].reset();")

    def _effect_slot_step_raw(self, slot, ev, parent_frame, delta_seconds, fps,
                              parent_looped, y_flip, vert_stride):

        s = emscripten.run_script_string(f"""
            var js_ev = window.ss_active_effect_ev;
            var s = window.ss_effects[{slot}];
            var visible = s.step(js_ev, {_jsnum(parent_frame)}, {_jsnum(delta_seconds)}, {_jsnum(fps)}, {'true' if parent_looped else 'false'}, {'true' if y_flip else 'false'}, {vert_stride});

            if (visible) {{
                var ptr = s.get_draw_plan_buf();
                var len = s.get_draw_plan_len();
                if (len > 0) {{
                    var u8 = new Uint8Array(window.ssruntime_wasm.memory.buffer, ptr, len);
                    JSON.stringify({{visible: true, len: len, b64: window.ss_base64_encode(u8)}});
                }} else {{
                    JSON.stringify({{visible: true, len: len, b64: ""}});
                }}
            }} else {{
                JSON.stringify({{visible: false}});
            }}
        """)

        import json
        res = json.loads(s)

        class _EffectStepResult: pass
        r = _EffectStepResult()
        r.visible = res["visible"]
        if r.visible:
            if res["len"] > 0:
                import base64
                data = base64.b64decode(res["b64"])
                r.draw_plan_buf = True
                r.draw_plan_len = len(data)
                self._last_effect_data = data
            else:
                r.draw_plan_buf = False
                r.draw_plan_len = 0
                self._last_effect_data = b""
        else:
            r.draw_plan_buf = False
            r.draw_plan_len = 0
            self._last_effect_data = b""
        return r

    def effect_slot_step(self, slot, ev, parent_frame, delta_seconds, fps,
                         parent_looped, y_flip=True, vert_stride=2):
        r = self._effect_slot_step_raw(slot, ev, parent_frame, delta_seconds, fps, parent_looped, y_flip, vert_stride)
        if not r.visible or r.draw_plan_len == 0:
            return (False, b"")
        return (True, self._last_effect_data)

    def effect_slot_step_view(self, slot, ev, parent_frame, delta_seconds, fps,
                              parent_looped, y_flip=True, vert_stride=2):
        r = self._effect_slot_step_raw(slot, ev, parent_frame, delta_seconds, fps, parent_looped, y_flip, vert_stride)
        if not r.visible or r.draw_plan_len == 0:
            return (False, memoryview(b""))
        return (True, memoryview(self._last_effect_data))

    def effect_slot_is_independent(self, slot):
        # Guard the getter name so a JS TypeError can't unwind the emscripten
        # boundary uncatchably (see instance_slot_is_independent).
        return emscripten.run_script_int(
            f"(function(s){{return (s.is_independent?s.is_independent():(s.independent?s.independent():false))?1:0;}})(window.ss_effects[{slot}])") == 1

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
            """)
        self._res = None
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
