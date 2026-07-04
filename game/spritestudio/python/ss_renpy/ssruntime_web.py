"""WebAssembly/JS bindings for libssruntime ("Brain").

This module provides `_WebRuntime`, a drop-in replacement for `_NativeRuntime`
that operates on the Web platform (Ren'Py Web) by communicating with the JS API
exported by the `SSPlayerForWeb` WASM wrapper, via `renpy.emscripten`.
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
                // silently returns a null buffer (SDK docs/06). Mirror native:
                // no frame data this tick (the frame's parts just don't draw).
                // The sub-frame Instance walk momentarily seeks past the child's
                // range edge, so without this the child throws every such tick.
                if (!isFinite(frame_no)) return "";
                try {
                    var ptr = ctx.get_frame_data_buf(frame_no);
                    var len = ctx.get_frame_data_len(frame_no);
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

    def stop(self):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].stop();")

    def set_loop(self, loops: int):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].set_loop({loops});")
        return self

    def set_animation_speed(self, rate: float):
        emscripten.run_script(f"window.ss_ctxs[{self._ctx_id}].set_animation_speed({_jsnum(rate)});")

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

    def update(self, dt_seconds: float) -> float:
        return float(emscripten.run_script_string(f"window.ss_ctxs[{self._ctx_id}].update({_jsnum(dt_seconds * 1000.0)}).toString()"))

    def update_ms(self, dt_ms: float) -> float:
        return float(emscripten.run_script_string(f"window.ss_ctxs[{self._ctx_id}].update({_jsnum(dt_ms)}).toString()"))

    @property
    def frame_no(self) -> float:
        return float(emscripten.run_script_string(f"window.ss_ctxs[{self._ctx_id}].get_frame_no().toString()"))

    @property
    def is_playing(self) -> bool:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].is_playing() ? 1 : 0") == 1

    @property
    def is_pausing(self) -> bool:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].is_pausing() ? 1 : 0") == 1

    @property
    def is_end_frame_reached(self) -> bool:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].is_end_frame_reached() ? 1 : 0") == 1

    @property
    def is_looped(self) -> bool:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].is_looped() ? 1 : 0") == 1

    @property
    def is_playing_forward(self) -> bool:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].is_playing_forward() ? 1 : 0") == 1

    @property
    def fps(self) -> int:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].get_fps()")

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
    def remain_loops(self) -> int:
        return emscripten.run_script_int(f"window.ss_ctxs[{self._ctx_id}].get_remain_loops()")

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

    # Return value parsing helpers
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

    def instance_slot_step(self, slot, ev, child_ctx, previous_child_frame,
                           parent_frame, delta_seconds, parent_looped):
        c_ctx_id = child_ctx._ctx_id if hasattr(child_ctx, "_ctx_id") else child_ctx
        
        s = emscripten.run_script_string(f"""
            var js_ev = window.ss_active_ev;
            var slot = window.ss_instances[{slot}];
            var visible = slot.step(js_ev, window.ss_ctxs[{c_ctx_id}], {_jsnum(previous_child_frame)}, {_jsnum(parent_frame)}, {_jsnum(delta_seconds)}, {'true' if parent_looped else 'false'});
            
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
        return emscripten.run_script_int(f"window.ss_instances[{slot}].is_independent() ? 1 : 0") == 1

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
        return emscripten.run_script_int(f"window.ss_effects[{slot}].is_independent() ? 1 : 0") == 1

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
