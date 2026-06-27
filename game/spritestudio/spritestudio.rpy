# SpriteStudio Player for Ren'Py — SSPlayer
#
# Renders a SpriteStudio 7 .ssab animation pack as a Creator-Defined
# Displayable (`SSPlayer`; one instance plays one .ssab, selecting an animation
# by name). The heavy lifting (frame stepping, world transforms, UVs, vertex
# colours, particle sim) is done by the native "Brain" (libssruntime) via
# ctypes; this file is only the thin Ren'Py rendering layer + the lazy
# setup/path wiring.
#
# Scope: Normal parts (per-vertex mesh — shear / free-deform exact, per-vertex
# `parts_color`, framebuffer + PartColor blend), **Instance** parts (nested
# child animations, synced or independent, recursive), **Effect** parts
# (particles), and **Mesh(deform)** parts (skinned/free-deform meshes) — all
# walked z-ordered via `ss_renpy.instance.collect_ordered` and batched by
# texture. Shape / Mask / Text / NineSlice batch kinds are still skipped (later
# milestones). The engine-independent cores are headless-verified by
# tools/verify_*.py.
#
# Timeline events (roadmap Step 4) are surfaced independently of rendering:
# UserData / Signal / Audio markers are decoded by `ss_renpy.events` and
# delivered via the optional on_* callbacks and the ss_poll_events() queue;
# finished / looped derive from runtime state. (Playing audio is the host's
# job — the Player only reports the trigger, per docs/00_limitations.)
#
# ─────────────────────────────────────────────────────────────────────────
# VERIFICATION STATUS — READ THIS
# The engine-independent render core (geometry + colour + blend math) is
# headless-verified by `tools/verify_m2.py` and `tools/render_png.py`. The
# *Ren'Py-specific* drawing below (GL blend funcs, matrixcolor conventions,
# custom mesh construction, rotation/zoom signs) could NOT be run against a
# real Ren'Py here, so each such feature sits behind a tuning knob with a safe
# fallback. Defaults keep the known-good M1 placement and layer the
# well-documented M2 features on top; flip the knobs after on-device checks.
# The "mesh" backend (true per-vertex gradients / non-parallelogram deform) is
# the documented #1 spike from renpy-cold-start.ja.md §3.2 — opt-in only.
# ─────────────────────────────────────────────────────────────────────────

init -10 python:
    import os, sys, math

    # This library lives at <gamedir>/spritestudio/ by convention. If you drop
    # it somewhere else, set `store.spritestudio_root` in an earlier init block
    # (e.g. `init -20 python: spritestudio_root = "..."`), or edit this line.
    _SS_ROOT = getattr(store, "spritestudio_root", None) or \
        os.path.join(renpy.config.gamedir, "spritestudio")
    # ss_renpy, the generated ss.* bindings, and flatbuffers all live under python/.
    _SS_PY = os.path.join(_SS_ROOT, "python")
    if _SS_PY not in sys.path:
        sys.path.insert(0, _SS_PY)

    import ss_renpy
    from ss_renpy import ssruntime, framedata, events, instance, effectplan
    from ss_renpy.effect import EffectRig
    from ss_renpy.instance import InstanceRig, collect_ordered
    from ss_renpy.ssab_meta import SsabMeta

    # Load the native library once, from spritestudio/libs/<platform-arch>/.
    _SS_LIB = ssruntime.load_library(base_dir=os.path.join(_SS_ROOT, "libs"))

    # --- Tuning knobs (set before first render) ----------------------------
    # I could not run Ren'Py to confirm its rendering conventions, so these let
    # you correct the result on your build without touching code.
    SS_ROTATE_SIGN = 1.0          # set -1.0 if rotation direction is reversed
    SS_MIRROR_AXIS = "y"          # "y" = mirror via negative yzoom, "x" = xzoom

    # Render backend:
    #   "transform" (default) — blit + Transform. Documented, robust. Adds over
    #       M1: framebuffer blend modes and uniform parts_color tint. Drops
    #       shear/free-deform back to the M1 similarity fit and renders
    #       per-vertex colour *gradients* as a flat (averaged) tint.
    #   "mesh" (default) — model-based per-vertex mesh (renpy.gl2 Mesh2) + custom
    #       shader. The only backend that reproduces shear / free-deform and the
    #       baked UV transforms (UvScale/UvTranslation/UvRotation) by sampling the
    #       full atlas with gl_texture_wrap = REPEAT. Mirrors the reference
    #       renderers. On any error it falls back per-part to the transform
    #       backend, so it can never blank the screen.
    #
    # The transform backend CANNOT represent UV scale/rotation (it crops the cell
    # rect), so parts like Basic.ssab's UvScale=2 render wrong there — hence mesh
    # is the default. Set "transform" only if the mesh backend misbehaves on your
    # GPU/Ren'Py build.
    SS_RENDER_BACKEND = "mesh"

    SS_ENABLE_BLEND = True        # apply framebuffer blend via gl_blend_func
    SS_ENABLE_PARTCOLOR = True    # apply parts_color tint (transform backend)
    SS_USE_MATRIX_TRANSFORM = False  # transform backend: true shear via 4x4

    # Timeline events (UserData / Signal / Audio). The decoder is pure-Python and
    # headless-verified (tools/verify_events.py); collecting into the poll queue
    # is cheap and always on when enabled. Optional callbacks (see the
    # displayable constructor) run *inside* render() — keep them light; for
    # control flow (jumps, sound) prefer draining ss_poll_events() from a screen.
    SS_ENABLE_EVENTS = True

    # SS framebuffer BlendType -> Ren'Py config.gl_blend_func key. Mix == normal
    # (no override). Only the keys Ren'Py ships by default are mapped; the rest
    # (Sub/Screen/Exclusion/…) need custom shaders (M2+ TODO) and are logged
    # once, then drawn with normal alpha so the part is at least visible.
    SS_BLEND_FUNC_KEY = {
        1: "multiply",   # BlendType.Mul
        2: "add",        # BlendType.Add
    }

    # PartColor shader (10_parts_color §1-4), used by the "mesh" backend. The
    # CPU reference is framedata.eval_partcolor — keep this GLSL in step with it.
    # Registered defensively: older Ren'Py without register_shader just skips it
    # (the mesh backend then falls back to the transform backend).
    if hasattr(renpy, "register_shader"):
        try:
            renpy.register_shader(
                "ss.partcolor",
                variables="""
                    uniform sampler2D tex0;
                    attribute vec2 a_tex_coord;
                    varying vec2 v_tex_coord;
                    uniform vec4 u_ss_color;   // (r,g,b,a) 0..1, a = hierarchical alpha
                    uniform vec3 u_ss_varg;    // (1+c.x*rate, c.y*rate, c.z) from §1-4-2
                """,
                vertex_300="v_tex_coord = a_tex_coord;",
                fragment_300="""
                    vec4 p = texture2D(tex0, v_tex_coord);
                    // Ren'Py GL2 textures are premultiplied-alpha (cf. the
                    // built-in renpy.alpha shader, which scales rgb AND a by
                    // opacity). Work in straight space for the PartColor formula,
                    // then re-premultiply so opacity actually dims the part.
                    vec3 s = p.a > 0.0 ? p.rgb / p.a : p.rgb;
                    // out_rgb = s*varg.x + mix(1, s, varg.z)*color*varg.y  (§1-4-3)
                    vec3 wp = mix(vec3(1.0), s, u_ss_varg.z);
                    vec3 rgb = s * u_ss_varg.x + wp * u_ss_color.rgb * u_ss_varg.y;
                    float a = p.a * u_ss_color.a;
                    gl_FragColor = vec4(rgb * a, a);
                """,
            )
        except Exception as e:
            renpy.log("ss: register_shader(ss.partcolor) failed: %r" % (e,))

        # Effect-particle shader: straight texel * (per-quad) colour. Effect
        # particle colours are RGBA 0..1 from the EffectDrawPlan (parent alpha
        # already folded in); unlike Normal parts there is no PartColor blend.
        try:
            renpy.register_shader(
                "ss.effect",
                variables="""
                    uniform sampler2D tex0;
                    attribute vec2 a_tex_coord;
                    varying vec2 v_tex_coord;
                    uniform vec4 u_ss_color;   // particle RGBA (0..1)
                """,
                vertex_300="v_tex_coord = a_tex_coord;",
                fragment_300="""
                    // Premultiplied-alpha output: tint by colour.rgb, dim by
                    // colour.a (scaling rgb too, not just alpha).
                    vec4 p = texture2D(tex0, v_tex_coord);
                    gl_FragColor = vec4(p.rgb * u_ss_color.rgb * u_ss_color.a,
                                        p.a * u_ss_color.a);
                """,
            )
        except Exception as e:
            renpy.log("ss: register_shader(ss.effect) failed: %r" % (e,))

        # Batched variants: per-vertex colour (and PartColor varg) so a whole
        # same-texture run / a whole effect batch draws in ONE mesh + ONE blit
        # (docs/07 §2, 08 §2 dynamic batching). Same fragment math as the
        # per-part shaders above, but reading varyings instead of uniforms.
        try:
            renpy.register_shader(
                "ss.partcolor_batched",
                variables="""
                    uniform sampler2D tex0;
                    attribute vec2 a_tex_coord;
                    attribute vec4 a_ss_color;
                    attribute vec3 a_ss_varg;
                    varying vec2 v_tex_coord;
                    varying vec4 v_ss_color;
                    varying vec3 v_ss_varg;
                """,
                vertex_300="""
                    v_tex_coord = a_tex_coord;
                    v_ss_color = a_ss_color;
                    v_ss_varg = a_ss_varg;
                """,
                fragment_300="""
                    vec4 p = texture2D(tex0, v_tex_coord);
                    vec3 s = p.a > 0.0 ? p.rgb / p.a : p.rgb;   // un-premultiply
                    vec3 wp = mix(vec3(1.0), s, v_ss_varg.z);
                    vec3 rgb = s * v_ss_varg.x + wp * v_ss_color.rgb * v_ss_varg.y;
                    float a = p.a * v_ss_color.a;
                    gl_FragColor = vec4(rgb * a, a);            // re-premultiply
                """,
            )
            renpy.register_shader(
                "ss.effect_batched",
                variables="""
                    uniform sampler2D tex0;
                    attribute vec2 a_tex_coord;
                    attribute vec4 a_ss_color;
                    varying vec2 v_tex_coord;
                    varying vec4 v_ss_color;
                """,
                vertex_300="""
                    v_tex_coord = a_tex_coord;
                    v_ss_color = a_ss_color;
                """,
                fragment_300="""
                    vec4 p = texture2D(tex0, v_tex_coord);
                    gl_FragColor = vec4(p.rgb * v_ss_color.rgb * v_ss_color.a,
                                        p.a * v_ss_color.a);
                """,
            )
        except Exception as e:
            renpy.log("ss: register_shader(ss.*_batched) failed: %r" % (e,))

    # SS Effect blend (EmitterState.blend_type): 0=Mix (normal), 1=Add. This is
    # a *different* enum from the framebuffer BlendType used by Normal parts.
    SS_EFFECT_BLEND_FUNC_KEY = {effectplan.FX_BLEND_ADD: "add"}

    def _ss_effect_blend_property(blend):
        if not SS_ENABLE_BLEND:
            return None
        key = SS_EFFECT_BLEND_FUNC_KEY.get(blend)
        if not key:
            return None
        table = getattr(renpy.config, "gl_blend_func", None) or {}
        val = table.get(key)
        return ("gl_blend_func", val) if val is not None else None

    # Model-based mesh backend dependencies (Ren'Py gl2). `Mesh2` is Ren'Py's
    # built-in 2D mesh (vs Mesh3 = 3D); we build one per part with explicit
    # per-vertex position + UV. Imported defensively so an older Ren'Py without
    # these simply disables the mesh backend (the transform backend still works).
    try:
        from renpy.gl2.gl2mesh2 import Mesh2 as _SS_Mesh2
        from renpy.gl2.gl2mesh import TEXTURE_LAYOUT as _SS_TEXTURE_LAYOUT
    except Exception as e:
        _SS_Mesh2 = None
        _SS_TEXTURE_LAYOUT = None
        renpy.log("ss: gl2 Mesh2 unavailable (%r); mesh backend disabled" % (e,))
    # REPEAT wrap so UVs the runtime baked past the atlas edge (UvScale/translate/
    # rotate) sample correctly — the analogue of every reference player's wrap.
    try:
        from renpy.uguu import GL_REPEAT as _SS_GL_REPEAT
        _SS_TEXTURE_WRAP = (_SS_GL_REPEAT, _SS_GL_REPEAT)
    except Exception:
        _SS_TEXTURE_WRAP = None

    # Batch draw (docs/07 §2, 08 §2): pack per-vertex colour into custom Mesh2
    # vertex layouts so a run of same-texture Normal parts — and a whole effect
    # batch's particles — go through one Mesh2 + one blit instead of one each.
    #   ss.partcolor (Normal): a_tex_coord(2) + a_ss_color(4) + a_ss_varg(3)
    #   ss.effect    (particles): a_tex_coord(2) + a_ss_color(4)
    # Built defensively: a Ren'Py without AttributeLayout.add_attribute leaves
    # the layouts None and the per-part / per-particle path is used instead.
    SS_BATCH_DRAW = True             # set False to force per-part drawing
    _SS_PC_LAYOUT = None
    _SS_FX_LAYOUT = None
    try:
        from renpy.gl2.gl2mesh import AttributeLayout as _SS_AttributeLayout
        _SS_PC_LAYOUT = _SS_AttributeLayout()
        _SS_PC_LAYOUT.add_attribute("a_tex_coord", 2)
        _SS_PC_LAYOUT.add_attribute("a_ss_color", 4)
        _SS_PC_LAYOUT.add_attribute("a_ss_varg", 3)
        _SS_FX_LAYOUT = _SS_AttributeLayout()
        _SS_FX_LAYOUT.add_attribute("a_tex_coord", 2)
        _SS_FX_LAYOUT.add_attribute("a_ss_color", 4)
    except Exception as e:
        _SS_PC_LAYOUT = None
        _SS_FX_LAYOUT = None
        renpy.log("ss: batch-draw layouts unavailable (%r); per-part draw" % (e,))

    def _ss_blend_property(blend_type):
        """Return a (key, value) for Render.add_property('gl_blend_func', …) or None."""
        if not SS_ENABLE_BLEND:
            return None
        key = SS_BLEND_FUNC_KEY.get(blend_type)
        if not key:
            return None
        table = getattr(renpy.config, "gl_blend_func", None) or {}
        val = table.get(key)
        return ("gl_blend_func", val) if val is not None else None

    def _ss_avg_color(colors):
        n = float(len(colors)) or 1.0
        return tuple(sum(c[i] for c in colors) / n for i in range(4))

    def _ss_avg_rate(mp):
        return (sum(mp.rates) / float(len(mp.rates))) if mp.rates else 0.0

    def _ss_tint_matrix(blend, color, rate):
        """Ren'Py matrixcolor implementing eval_partcolor for a *uniform* colour.

        Linear colour op out = pixel*S + O per channel (alpha S = color.a):
          Mix/Add/Sub (varg.z=0): S = varg.x,           O = color*varg.y
          Mul        (varg.z=1):  S = varg.x+color*varg.y, O = 0
        Returns a renpy Matrix or None (→ caller skips tint). The colour-matrix
        arity/convention (premultiply, row order, 5x4 vs 5x5) is version-
        dependent and unverified here, so the whole construction is guarded —
        any mismatch returns None and the part renders untinted (geometry stays
        correct).
        """
        try:
            from renpy.display.matrix import Matrix
            vx, vy, vz = framedata.partcolor_varg(blend, rate)
            r, g, b, a = color
            if vz >= 0.5:   # Mul: per-channel multiply, no offset
                sr, sg, sb = vx + r * vy, vx + g * vy, vx + b * vy
                orr = og = ob = 0.0
            else:           # Mix / Add / Sub: scalar scale + colour offset
                sr = sg = sb = vx
                orr, og, ob = r * vy, g * vy, b * vy
            # 5x4 colour matrix: rows [wr wg wb wa offset] per output channel.
            return Matrix([
                sr, 0,  0,  0,  orr,
                0,  sg, 0,  0,  og,
                0,  0,  sb, 0,  ob,
                0,  0,  0,  a,  0,
            ])
        except Exception:
            return None

    class SSPlayer(renpy.Displayable):
        """Play one SpriteStudio .ssab pack. Place it in a screen or `show` it.

            add SSPlayer("Basic.ssab") xalign 0.5 yalign 0.5

        One instance plays one .ssab; select an animation in it by name
        (constructor ``animation=`` or :meth:`ss_set_animation`). Renders Normal,
        Instance (nested child animations) and Effect (particle) parts, exposing
        a small ``ss_*`` playback / control / query API.
        """

        def __init__(self, ssab, animation=None, sprites_subdir="ss_assets",
                     loop=-1, speed=1.0, sub_frame=True,
                     on_user_data=None, on_signal=None, on_audio=None,
                     on_finished=None, on_looped=None, on_started=None,
                     aliases=None, **kwargs):
            super(SSPlayer, self).__init__(**kwargs)
            self.ssab = ssab
            self.kwargs = kwargs
            self.aliases = aliases or {}
            self._duplicatable = True
            self._available_animations = None
            
            self._initial_animation = animation
            self._initial_loop = loop

            if isinstance(animation, (list, tuple)) and len(animation) > 0:
                self._anim_queue = list(animation)
                self.animation = self._anim_queue.pop(0)
                self.loop = 1 if self._anim_queue else loop
            else:
                self._anim_queue = []
                self.animation = animation
                self.loop = loop

            self.sprites_subdir = sprites_subdir
            self.speed = speed
            # Sub-frame interpolation: when off the frame handed
            # to the Brain for *display* is floored; the playback
            # head stays a raw float either way (docs/06). By default, it is now on.
            self._sub_frame = bool(sub_frame)
            # Optional event callbacks (docs/06 §4 recommended Player API). Each
            # is invoked as cb(self, frame_index, event) for the per-part events
            # and cb(self) for started/finished/looped, guarded so a raising
            # callback can never break rendering. Prefer module-level functions /
            # store methods (lambdas/locals defeat rollback pickling).
            self.on_user_data = on_user_data
            self.on_signal = on_signal
            self.on_audio = on_audio
            self.on_finished = on_finished
            self.on_looped = on_looped
            self.on_started = on_started
            # runtime state (built lazily on first render)
            self._rt = None
            self._anim = None
            self._ssab_data = None  # retained for per-animation EventResolver rebuilds
            self._meta = None
            self._evt = None        # ss_renpy.events.EventResolver for self._anim
            self._event_queue = []  # FrameEvents awaiting ss_poll_events()
            self._was_playing = False
            self._instances = None  # ss_renpy.instance.InstanceRig (instance parts)
            self._effects = None    # ss_renpy.effect.EffectRig (effect parts)
            self._loader = None     # pack_name -> bytes, for external instance .ssab
            self._part_index = {}   # part name -> index (for the part-query API)
            self._texmap = {}
            self._texpath = {}     # texture_hash -> "sprites/foo.png"
            self._base = {}        # path -> Image()
            self._last_st = None
            self._last_wm = []      # snapshot of root world matrices (part query)
            self._last_hidden = None  # snapshot of hidden part indices (part query)
            self._warned = set()

        def __getstate__(self):
            """Drop native pointers and reconstructible caches for pickling/saves."""
            state = self.__dict__.copy()
            for k in ("_rt", "_anim", "_ssab_data", "_meta", "_evt",
                      "_instances", "_effects", "_loader", "_base",
                      "_last_st", "_last_hidden"):
                state[k] = None
            state["_event_queue"] = []
            state["_part_index"] = {}
            state["_texmap"] = {}
            state["_texpath"] = {}
            state["_last_wm"] = []
            state["_warned"] = set()
            return state

        # -- image attributes (_duplicate, _list_attributes) ---------------
        def _get_available_animations(self):
            if self._available_animations is None:
                path = os.path.join(self._SS_dir(), self.ssab)
                try:
                    with open(path, "rb") as fh:
                        data = fh.read()
                    meta = SsabMeta(data)
                    self._available_animations = meta.animation_names()
                except Exception:
                    self._available_animations = []
            return self._available_animations

        def _list_attributes(self, tag, attributes):
            """Tell Ren'Py what attributes (animations/aliases) this displayable accepts."""
            available = set(self._get_available_animations())
            available.update(self.aliases.keys())
            return list(available)

        def _duplicate(self, args):
            """Spawn a new SSPlayer instance for `show ssplayer [attributes]`."""
            if not getattr(self, "_duplicatable", True):
                return self
            if not args or not getattr(args, "args", None):
                return self

            target_anim = self.animation
            for attr in args.args:
                if attr in self.aliases:
                    target_anim = self.aliases[attr]
                elif attr in self._get_available_animations():
                    target_anim = attr

            # Return a copy configured for the new animation.
            rv = SSPlayer(
                self.ssab,
                animation=target_anim,
                sprites_subdir=self.sprites_subdir,
                loop=self.loop,
                speed=self.speed,
                sub_frame=self._sub_frame,
                on_user_data=self.on_user_data,
                on_signal=self.on_signal,
                on_audio=self.on_audio,
                on_finished=self.on_finished,
                on_looped=self.on_looped,
                on_started=self.on_started,
                aliases=self.aliases,
                **self.kwargs
            )
            rv._duplicatable = False
            return rv

        # -- lazy native setup ---------------------------------------------
        def _ensure(self):
            if self._rt is not None:
                return
            path = os.path.join(self._SS_dir(), self.ssab)
            with open(path, "rb") as fh:
                data = fh.read()
            self._ssab_data = data
            meta = SsabMeta(data)
            self._meta = meta
            self._texmap = meta.texture_hash_map()
            self._part_index = {p.name: p.index for p in meta.parts()}
            self._loader = self._make_loader()
            rt = ssruntime.SSRuntime(_SS_LIB)
            rt.configure(coordinate_system=ssruntime.COORD_Y_DOWN,
                         origin=ssruntime.ORIGIN_CENTER)
            rt.load_ssab_bytes(data)
            anim = self.animation
            if not anim:
                names = meta.animation_names()
                anim = names[0] if names else None
            if not anim or not rt.setup_animation(anim):
                raise Exception("ss: setup_animation(%r) failed in %s"
                                % (anim, self.ssab))
            rt.set_loop(self.loop)
            if self.speed != 1.0:
                rt.set_animation_speed(self.speed)
            rt.play()
            self._rt = rt
            self._anim = anim
            self.animation = anim
            self._evt = events.EventResolver(data, anim)
            self._was_playing = True
            self._build_rigs()

        def _make_loader(self):
            """Loader(pack_name)->bytes for external instance packs (docs/08 §1).

            Caches bytes and merges each loaded pack's cellmap → image-path map
            into ``self._texmap`` so child-part texture hashes resolve to PNGs in
            the same sprites dir.
            """
            cache = {}

            def load(pack_name):
                if pack_name in cache:
                    return cache[pack_name]
                p = os.path.join(self._SS_dir(), pack_name + ".ssab")
                data = b""
                try:
                    with open(p, "rb") as fh:
                        data = fh.read()
                except OSError:
                    self._warn_once(("ext", pack_name),
                                    "external instance pack %r not found "
                                    "next to %s" % (pack_name, self.ssab))
                cache[pack_name] = data
                if data:
                    try:
                        self._texmap.update(SsabMeta(data).texture_hash_map())
                    except Exception:
                        pass
                return data

            return load

        def _build_rigs(self):
            """Build the Instance/Effect rigs once for this pack (parts are
            pack-static; animation changes only reset slot state, see
            :meth:`_reset_slots`). Each is guarded so a failure disables only
            that feature, never rendering."""
            try:
                self._instances = InstanceRig(self._rt, self._meta,
                                              self._loader, _SS_LIB)
            except Exception as e:
                self._instances = None
                self._warn_once("inst-rig", "instance rig build failed: %r" % (e,))
            try:
                self._effects = EffectRig(self._rt, self._meta)
            except Exception as e:
                self._effects = None
                self._warn_once("fx-rig", "effect rig build failed: %r" % (e,))

        def _reset_slots(self):
            """Re-arm Instance/Effect slots (on replay / animation change)."""
            for rig in (self._instances, self._effects):
                if rig is not None:
                    try:
                        rig.reset()
                    except Exception:
                        pass

        def _SS_dir(self):
            return os.path.join(renpy.config.gamedir, self.sprites_subdir)

        def _texture_path(self, thash):
            path = self._texpath.get(thash)
            if path is None:
                img = self._texmap.get(thash, "")
                path = (self.sprites_subdir + "/" + img) if img else ""
                self._texpath[thash] = path
            return path

        def _base_image(self, tex_path):
            d = self._base.get(tex_path)
            if d is None:
                d = Image(tex_path)
                self._base[tex_path] = d
            return d

        def _warn_once(self, key, msg):
            if key not in self._warned:
                self._warned.add(key)
                renpy.log("ss: " + msg)

        # -- timeline events (UserData / Signal / Audio) -------------------
        def _pump_events(self):
            """Collect the events this update passed through; never raises.

            Called once per render, immediately after ``update``. Resolved
            FrameEvents are appended to the poll queue (drained by
            :meth:`ss_poll_events`) and dispatched to any callbacks. The
            finished / looped notifications are derived from runtime state:
            ``finished`` fires once on the ``is_playing`` True→False edge (works
            for finite loops *and* play-once; never fires for ``loop=-1``);
            ``looped`` fires on the per-update ``is_looped`` wrap flag.
            """
            if not SS_ENABLE_EVENTS:
                return
            try:
                if self._evt is not None and self._evt.available:
                    for fe in self._evt.collect(self._rt):
                        self._event_queue.append(fe)
                        self._dispatch_frame_events(fe)
                if self._rt.is_looped:
                    self._call_cb(self.on_looped)
                playing = self._rt.is_playing
                if self._was_playing and not playing:
                    if self._anim_queue:
                        next_anim = self._anim_queue.pop(0)
                        # Play once if queue has more, otherwise use the original loop setting
                        next_loop = 1 if self._anim_queue else self.kwargs.get("loop", -1)
                        self.ss_play(next_anim, loop=next_loop)
                    else:
                        self._call_cb(self.on_finished)
                self._was_playing = playing
            except Exception as e:
                self._warn_once("event-pump",
                                "event pump failed (%r); events disabled this "
                                "frame" % (e,))

        def _dispatch_frame_events(self, fe):
            for u in fe.users:
                self._call_cb(self.on_user_data, fe.frame_index, u)
            for s in fe.signals:
                self._call_cb(self.on_signal, fe.frame_index, s)
            for a in fe.audios:
                self._call_cb(self.on_audio, fe.frame_index, a)

        def _call_cb(self, cb, *args):
            if cb is None:
                return
            try:
                cb(self, *args)
            except Exception as e:
                self._warn_once(("cb", id(cb)),
                                "event callback raised: %r" % (e,))

        def ss_poll_events(self):
            """Drain and return the events collected since the last poll.

            Returns a list of :class:`ss_renpy.events.FrameEvents` (each with
            ``.frame_index`` and ``.users`` / ``.signals`` / ``.audios``). This is
            the rollback-safe, render-thread-safe way to consume events from a
            screen / interaction (vs the callbacks, which fire inside render()).
            """
            q = self._event_queue
            self._event_queue = []
            return q

        # -- per-frame render ----------------------------------------------
        def render(self, width, height, st, at):
            self._ensure()
            
            # Detect re-show (time went backwards)
            if self._last_st is not None and st < self._last_st:
                if isinstance(self._initial_animation, (list, tuple)) and len(self._initial_animation) > 0:
                    self._anim_queue = list(self._initial_animation)
                    next_anim = self._anim_queue.pop(0)
                    next_loop = 1 if self._anim_queue else self._initial_loop
                    self.ss_play(animation=next_anim, loop=next_loop, start_frame=0)
                else:
                    self.ss_play(animation=self._initial_animation, loop=self._initial_loop, start_frame=0)

            dt = 0.0 if self._last_st is None else max(0.0, st - self._last_st)
            self._last_st = st
            frame_no = self._rt.update(dt)           # seconds -> ms internally
            self._pump_events()                      # collect events this update
            looped = self._rt.is_looped
            # Sub-frame off (default) floors the *display* frame; the head stays
            # a raw float (docs/06). The slot steps below get the raw frame_no.
            disp = frame_no if self._sub_frame else math.floor(frame_no)
            # Zero-copy view over the Brain's FrameData buffer (no per-frame copy).
            # Valid only until the slot steps below; we snapshot what the part-
            # query API needs (matrices + hidden flags) before then.
            fb = self._rt.get_frame_data_view(disp)
            # Snapshot the root world matrices for the part-query API now (the
            # SoA pointer is transient; instance/effect steps below reuse it).
            wm, wn = self._rt.world_matrices()
            self._last_wm = list(wm[0:wn]) if (wm and wn) else []

            r = renpy.Render(width, height)
            if fb:
                fd = framedata.parse(fb)
                # Owned hidden-part snapshot for ss_is_part_hidden — taken while
                # the view is still valid (collect_ordered's slot steps below
                # invalidate this context's FrameData buffer).
                self._last_hidden = framedata.hidden_parts(fd)
                ox, oy = width / 2.0, height / 2.0   # SS center -> screen center
                # Walk Normal / Instance / Effect parts in true draw order.
                try:
                    items = collect_ordered(self._rt, fd, self._instances,
                                            self._effects, frame_no, dt, looped,
                                            self._sub_frame)
                except Exception as e:
                    self._warn_once("collect", "draw-plan walk failed (%r); "
                                    "Normal-only this frame" % (e,))
                    # collect_ordered may have stepped slots and invalidated the
                    # zero-copy view + SoA buffers; re-evaluate the frame so the
                    # Normal-only fallback reads a clean, valid snapshot.
                    fb = self._rt.get_frame_data_view(disp)
                    items = ([("mesh", mp)
                              for mp in framedata.build_mesh_parts(
                                  self._rt, framedata.parse(fb))]
                             if fb else [])
                self._draw_items(r, items, ox, oy, st, at, width, height)
            else:
                self._last_hidden = None    # no frame this tick (part query: hidden)
            renpy.redraw(self, 0)                    # keep animating
            return r

        # -- draw dispatch (batched) ---------------------------------------
        def _draw_items(self, r, items, ox, oy, st, at, width, height):
            """Draw the z-ordered renderables, batching consecutive same-texture
            Normal parts into one mesh/blit (and each effect batch likewise).

            A run breaks when the texture or framebuffer blend changes, or an
            effect batch interrupts it — preserving draw order. Falls back to
            per-part drawing when batching is unavailable / fails."""
            use_mesh = SS_RENDER_BACKEND == "mesh"
            can_batch = SS_BATCH_DRAW and use_mesh and _SS_PC_LAYOUT is not None
            run = []
            run_key = None
            for tag, payload in items:
                if tag == "mesh":
                    key = (payload.texture_hash, payload.blend_type)
                    if run and key != run_key:
                        self._flush_mesh_run(r, run, ox, oy, st, at, width,
                                             height, can_batch, use_mesh)
                        run = []
                    run_key = key
                    run.append(payload)
                else:  # "fx" — an effect particle batch
                    if run:
                        self._flush_mesh_run(r, run, ox, oy, st, at, width,
                                             height, can_batch, use_mesh)
                        run = []
                    self._draw_effect_batch(r, payload, ox, oy, st, at,
                                            width, height)
            if run:
                self._flush_mesh_run(r, run, ox, oy, st, at, width, height,
                                     can_batch, use_mesh)

        def _flush_mesh_run(self, r, run, ox, oy, st, at, width, height,
                            can_batch, use_mesh):
            if can_batch and self._draw_mesh_batch(r, run, ox, oy, st, at,
                                                   width, height):
                return
            for mp in run:
                drawn = (self._draw_mesh(r, mp, ox, oy, st, at, width, height)
                         if use_mesh else False)
                if not drawn:
                    self._draw_transform(r, mp, ox, oy, st, at, width, height)

        # -- transform backend (default, documented) -----------------------
        def _draw_transform(self, r, mp, ox, oy, st, at, width, height):
            tex = self._texture_path(mp.texture_hash)
            if not tex:
                return
            l, t, w, h = (int(round(v)) for v in mp.src_rect)
            if w <= 0 or h <= 0:
                return
            center, rot, xscale, yscale, mirror = framedata.placement_from_corners(
                mp.positions, mp.src_rect)
            if mp.use_center and mp.part_index not in self._warned:
                self._warn_once(("deform", mp.part_index),
                                "part %d free-deform; transform backend "
                                "approximates, use SS_RENDER_BACKEND='mesh'"
                                % mp.part_index)
            # The transform backend crops the cell rect, so it cannot represent a
            # baked UV scale/translation (the UV span no longer matches the cell).
            us = [u for (u, v) in mp.uvs]
            vs = [v for (u, v) in mp.uvs]
            if (abs((max(us) - min(us)) - mp.src_rect[2]) > 0.5
                    or abs((max(vs) - min(vs)) - mp.src_rect[3]) > 0.5):
                self._warn_once(("uvscale", mp.part_index),
                                "part %d has a UV scale/transform the transform "
                                "backend can't represent; use "
                                "SS_RENDER_BACKEND='mesh'" % mp.part_index)

            xzoom, yzoom = xscale, yscale
            if mirror:
                if SS_MIRROR_AXIS == "x":
                    xzoom = -xzoom
                else:
                    yzoom = -yzoom

            # parts_color: vertex alpha always carries the (pre-composed)
            # hierarchical alpha; the colour tint is applied only when present.
            avg = _ss_avg_color(mp.colors)
            kw = dict(crop=(l, t, w, h), rotate=rot * SS_ROTATE_SIGN,
                      xzoom=xzoom, yzoom=yzoom,
                      alpha=max(0.0, min(1.0, avg[3])), subpixel=True)
            if SS_ENABLE_PARTCOLOR and mp.has_partcolor:
                mtx = _ss_tint_matrix(mp.color_blend, avg, _ss_avg_rate(mp))
                if mtx is not None:
                    kw["matrixcolor"] = mtx
                elif mp.color_blend != framedata.PC_BLEND_MIX:
                    self._warn_once(("pc", mp.color_blend),
                                    "parts_color mode %d not applied in "
                                    "transform backend" % mp.color_blend)

            child = Transform(self._base_image(tex), **kw)
            cr = renpy.render(child, width, height, st, at)
            self._apply_blend(cr, mp)
            cw, ch = cr.get_size()
            # Transform pads the rotated content into a bbox and centers it,
            # so blitting at (center - bbox/2) lands the part's center on screen.
            r.blit(cr, (int(round(ox + center[0] - cw / 2.0)),
                        int(round(oy + center[1] - ch / 2.0))))

        def _apply_blend(self, cr, mp):
            prop = _ss_blend_property(mp.blend_type)
            if prop is not None:
                try:
                    cr.add_property(*prop)
                except Exception:
                    pass
            elif (SS_ENABLE_BLEND and mp.blend_type
                  and mp.blend_type not in SS_BLEND_FUNC_KEY):
                self._warn_once(("blend", mp.blend_type),
                                "framebuffer blend %s needs a custom shader; "
                                "drawn as normal" % framedata.BLEND_NAMES.get(
                                    mp.blend_type, mp.blend_type))

        # -- mesh backend (default): true per-vertex Mesh2 ------------------
        def _draw_mesh(self, r, mp, ox, oy, st, at, width, height):
            """Draw one part as a per-vertex model mesh. Returns True on success.

            Builds a ``renpy.gl2.gl2mesh2.Mesh2`` from the part's world-space
            corners (``mp.positions``) and its texture-pixel UVs normalized by the
            atlas size (``framedata.normalize_uvs``), textures it with the FULL
            atlas, and sets ``gl_texture_wrap = REPEAT`` so UVs the runtime baked
            past the atlas edge (UvScale/UvTranslation/UvRotation) wrap instead of
            clamping. This is the only backend that is shear / free-deform exact
            and honours the UV transforms — the Ren'Py-native form of what the
            the reference players do. ``parts_color`` is applied per-part
            (uniform) via the ``ss.partcolor`` shader.

            On any error returns False so the caller falls back to the transform
            backend (never blanks the screen).
            """
            if _SS_Mesh2 is None:
                return False
            try:
                tex = self._texture_path(mp.texture_hash)
                if not tex:
                    return False
                cr = renpy.render(self._base_image(tex), width, height, st, at)
                tw, th = cr.get_size()        # atlas pixel size (for UV normalize)
                if tw <= 0 or th <= 0:
                    return False

                pts = mp.positions            # 4 corners, or 5 with centre fan
                nuv = framedata.normalize_uvs(mp.uvs, tw, th)
                tris = mp.triangles

                mesh = _SS_Mesh2(_SS_TEXTURE_LAYOUT, len(pts), len(tris))
                geometry = []
                for (x, y) in pts:
                    geometry += [ox + x, oy + y]          # SS world -> screen px
                mesh.set_geometry_data(geometry)
                attributes = []
                for (u, v) in nuv:
                    attributes += [u, v]                  # a_tex_coord (may be >1)
                mesh.set_attribute_data(attributes)
                indices = []
                for tri in tris:
                    indices += [tri[0], tri[1], tri[2]]
                mesh.set_triangle_data(indices)

                rv = renpy.Render(width, height)
                rv.blit(cr, (0, 0))                       # supplies tex0 (atlas)
                rv.mesh = mesh
                if _SS_TEXTURE_WRAP is not None:
                    rv.add_property("texture_wrap_tex0", _SS_TEXTURE_WRAP)
                rv.add_shader("ss.partcolor")
                avg = _ss_avg_color(mp.colors)
                vx, vy, vz = framedata.partcolor_varg(mp.color_blend, _ss_avg_rate(mp))
                rv.add_uniform("u_ss_color", (avg[0], avg[1], avg[2], avg[3]))
                rv.add_uniform("u_ss_varg", (vx, vy, vz))
                self._apply_blend(rv, mp)
                r.blit(rv, (0, 0))            # mesh positions are already screen-space
                return True
            except Exception as e:
                self._warn_once("mesh-backend",
                                "mesh backend failed (%r); falling back to "
                                "transform backend" % (e,))
                return False

        def _draw_mesh_batch(self, r, parts, ox, oy, st, at, width, height):
            """Draw a run of same-texture Normal parts as ONE batched mesh+blit.

            All parts share one atlas (same texture_hash) and framebuffer blend.
            Per-vertex colour and the PartColor ``varg`` are packed as mesh
            attributes (``ss.partcolor_batched``), so an entire run is a single
            Mesh2 with REPEAT wrap. Returns True on success; False makes the
            caller draw the run per-part.
            """
            if _SS_PC_LAYOUT is None or _SS_Mesh2 is None or not parts:
                return False
            tex = self._texture_path(parts[0].texture_hash)
            if not tex:
                return False
            try:
                cr = renpy.render(self._base_image(tex), width, height, st, at)
                tw, th = cr.get_size()
                if tw <= 0 or th <= 0:
                    return False
                geometry = []
                attributes = []
                indices = []
                base = 0
                for mp in parts:
                    nuv = framedata.normalize_uvs(mp.uvs, tw, th)
                    for idx in range(len(mp.positions)):
                        x, y = mp.positions[idx]
                        geometry += [ox + x, oy + y]
                        u, v = nuv[idx]
                        c = mp.colors[idx]
                        vx, vy, vz = framedata.partcolor_varg(
                            mp.color_blend, mp.rates[idx])
                        attributes += [u, v, c[0], c[1], c[2], c[3], vx, vy, vz]
                    for (i, j, k) in mp.triangles:
                        indices += [base + i, base + j, base + k]
                    base += len(mp.positions)
                mesh = _SS_Mesh2(_SS_PC_LAYOUT, base, len(indices) // 3)
                mesh.set_geometry_data(geometry)
                mesh.set_attribute_data(attributes)
                mesh.set_triangle_data(indices)
                rv = renpy.Render(width, height)
                rv.blit(cr, (0, 0))
                rv.mesh = mesh
                if _SS_TEXTURE_WRAP is not None:
                    rv.add_property("texture_wrap_tex0", _SS_TEXTURE_WRAP)
                rv.add_shader("ss.partcolor_batched")
                self._apply_blend(rv, parts[0])
                r.blit(rv, (0, 0))
                return True
            except Exception as e:
                self._warn_once("mesh-batch", "batched mesh draw failed (%r); "
                                "per-part fallback" % (e,))
                return False

        # -- effect backend: particle batches ------------------------------
        def _draw_effect_batch(self, r, eb, ox, oy, st, at, width, height):
            """Draw one Effect batch (particles). Effect UVs are already
            normalized 0..1 (used directly). Preferred path: the whole batch in
            ONE mesh with per-vertex colour (``ss.effect_batched``); fallback:
            per-particle uniform-colour quads; then skip — never blanks."""
            if _SS_Mesh2 is None or not eb.positions:
                return
            tex = self._texture_path(eb.cellmap_hash)
            if not tex:
                self._warn_once(("fxtex", eb.cellmap_hash),
                                "effect cellmap hash %d unresolved" % eb.cellmap_hash)
                return
            try:
                cr = renpy.render(self._base_image(tex), width, height, st, at)
                blend_prop = _ss_effect_blend_property(eb.blend)
                if (_SS_FX_LAYOUT is not None and SS_BATCH_DRAW
                        and self._draw_fx_batched(r, eb, cr, ox, oy, width,
                                                  height, blend_prop)):
                    return
                self._draw_fx_per_particle(r, eb, cr, ox, oy, width, height,
                                           blend_prop)
            except Exception as e:
                self._warn_once("fx-draw",
                                "effect draw failed (%r); skipped" % (e,))

        def _draw_fx_batched(self, r, eb, cr, ox, oy, width, height, blend_prop):
            """All particles of ``eb`` in one Mesh2 (per-vertex colour)."""
            try:
                geometry = []
                attributes = []
                indices = []
                for idx in range(len(eb.positions)):
                    x, y = eb.positions[idx]
                    geometry += [ox + x, oy + y]
                    u, v = eb.uvs[idx]
                    c = eb.colors[idx]
                    attributes += [u, v, c[0], c[1], c[2], c[3]]
                for (i, j, k) in eb.triangles:
                    indices += [i, j, k]
                mesh = _SS_Mesh2(_SS_FX_LAYOUT, len(eb.positions),
                                 len(indices) // 3)
                mesh.set_geometry_data(geometry)
                mesh.set_attribute_data(attributes)
                mesh.set_triangle_data(indices)
                rv = renpy.Render(width, height)
                rv.blit(cr, (0, 0))
                rv.mesh = mesh
                rv.add_shader("ss.effect_batched")
                if blend_prop is not None:
                    try:
                        rv.add_property(*blend_prop)
                    except Exception:
                        pass
                r.blit(rv, (0, 0))
                return True
            except Exception as e:
                self._warn_once("fx-batch", "batched effect draw failed (%r); "
                                "per-particle fallback" % (e,))
                return False

        def _draw_fx_per_particle(self, r, eb, cr, ox, oy, width, height,
                                  blend_prop):
            """Fallback: one uniform-colour quad per particle (proven layout)."""
            tris = eb.triangles
            for q in range(len(eb.positions) // 4):
                base = q * 4
                quad_tris = tris[2 * q:2 * q + 2]
                if len(quad_tris) < 2:
                    break
                col = eb.colors[base]
                indices = []
                for (i, j, k) in quad_tris:
                    indices += [i - base, j - base, k - base]
                mesh = _SS_Mesh2(_SS_TEXTURE_LAYOUT, 4, 2)
                geometry = []
                for (x, y) in eb.positions[base:base + 4]:
                    geometry += [ox + x, oy + y]
                mesh.set_geometry_data(geometry)
                attributes = []
                for (u, v) in eb.uvs[base:base + 4]:
                    attributes += [u, v]
                mesh.set_attribute_data(attributes)
                mesh.set_triangle_data(indices)
                rv = renpy.Render(width, height)
                rv.blit(cr, (0, 0))
                rv.mesh = mesh
                rv.add_shader("ss.effect")
                rv.add_uniform("u_ss_color", (col[0], col[1], col[2], col[3]))
                if blend_prop is not None:
                    try:
                        rv.add_property(*blend_prop)
                    except Exception:
                        pass
                r.blit(rv, (0, 0))

        def visit(self):
            try:
                self._ensure()
                imgs = []
                for h in self._texmap:
                    path = self._texture_path(h)
                    if path:
                        imgs.append(self._base_image(path))
                return imgs
            except Exception:
                return []

        # -- playback / control / query API --------------------------------
        # A small ss_-prefixed, Ren'Py-idiomatic playback / control surface.
        # setAnimation/play are split (docs/06 §4): set_animation loads+poses;
        # ss_play starts.
        def _reapply_playback(self):
            # setup_animation resets loop/speed/direction to defaults (docs/06
            # §4 NOTE) — re-apply the player's settings after a switch.
            self._rt.set_loop(self.loop)
            if self.speed != 1.0:
                self._rt.set_animation_speed(self.speed)

        def ss_set_animation(self, name):
            """Load + pose animation ``name`` (does NOT start playback).

            Front-loads the heavy work — native setup, asset loading, and
            Instance child-context allocation — so a later :meth:`play` starts
            instantly with no re-allocation (docs/06 §4 setAnimation/play split).
            """
            if self._rt is None:
                if name:
                    self.animation = name      # set up straight into `name`
                self._ensure()
                return True
            if name and name != self._anim:
                if not self._rt.setup_animation(name):
                    self._warn_once(("anim", name),
                                    "setup_animation(%r) failed" % name)
                    return False
                self._anim = name
                self.animation = name
                self._reapply_playback()
                self._evt = events.EventResolver(self._ssab_data, name)
                self._reset_slots()
                renpy.redraw(self, 0)
            return True

        def ss_get_animation(self):
            return self._anim

        def ss_animation_names(self):
            self._ensure()
            return self._meta.animation_names() if self._meta else []

        def ss_play(self, animation=None, loop=None, start_frame=-1.0):
            """Start playback (optionally switching animation / loop first).

            ``start_frame >= 0`` begins at that frame; otherwise resumes from the
            section start. Re-arms Instance/Effect slots so they re-fire."""
            self._ensure()
            if animation:
                self.ss_set_animation(animation)
            if loop is not None:
                self.loop = loop
                self._rt.set_loop(loop)
            self._reset_slots()
            if start_frame is not None and start_frame >= 0:
                self._rt.play_with_start_frame(start_frame)
            else:
                self._rt.play()
            self._was_playing = True
            self._call_cb(self.on_started)
            renpy.redraw(self, 0)

        def ss_pause(self):
            # The C-API pause toggles; gate on state so this is idempotent.
            if self._rt and not self._rt.is_pausing:
                self._rt.pause()

        def ss_resume(self):
            if self._rt and self._rt.is_pausing:
                self._rt.pause()
                self._was_playing = True
                renpy.redraw(self, 0)

        def ss_stop(self):
            if self._rt:
                self._rt.stop()

        def ss_is_playing(self):
            return bool(self._rt and self._rt.is_playing)

        def ss_is_pausing(self):
            return bool(self._rt and self._rt.is_pausing)

        def ss_get_frame(self):
            return self._rt.frame_no if self._rt else 0.0

        def ss_set_frame(self, frame):
            if self._rt:
                self._rt.set_frame_no(frame)
                renpy.redraw(self, 0)

        def ss_total_frames(self):
            return self._rt.total_frames if self._rt else 0

        def ss_start_frame(self):
            return self._rt.start_frame if self._rt else 0

        def ss_end_frame(self):
            return self._rt.end_frame if self._rt else 0

        def ss_set_speed(self, speed):
            self.speed = speed
            if self._rt:
                self._rt.set_animation_speed(speed)

        def ss_get_speed(self):
            return self.speed

        def ss_set_loop(self, count):
            self.loop = count
            if self._rt:
                self._rt.set_loop(count)

        def ss_get_loop(self):
            return self.loop

        def ss_set_section(self, start, end):
            if self._rt:
                self._rt.set_animation_section(start, end)
                renpy.redraw(self, 0)

        def ss_set_playback_direction(self, direction, style=0):
            """``direction``: 0=forward, 1=reverse; ``style``: 0=normal, 1=ping-pong."""
            if self._rt:
                self._rt.set_playback_direction(direction, style)

        def ss_set_frame_rate(self, fps):
            if self._rt:
                self._rt.set_frame_rate(fps)

        def ss_get_frame_rate(self):
            return self._rt.fps if self._rt else 0

        def ss_set_sub_frame_enabled(self, enabled):
            """Toggle sub-frame interpolation (default on)."""
            self._sub_frame = bool(enabled)
            renpy.redraw(self, 0)

        def ss_is_sub_frame_enabled(self):
            return self._sub_frame

        # -- part query ----------------------------------------------------
        def ss_part_names(self):
            self._ensure()
            return list(self._part_index.keys())

        def ss_part_index(self, name):
            self._ensure()
            return self._part_index.get(name, -1)

        def ss_part_transform(self, name):
            """Player-local transform of a part on the last rendered frame, or
            ``None``: a dict with x/y (px), rotation (deg), xscale/yscale."""
            i = self.ss_part_index(name)
            base = i * 16
            if i < 0 or base + 16 > len(self._last_wm):
                return None
            m = self._last_wm[base:base + 16]
            return {
                "x": m[12], "y": m[13],
                "rotation": math.degrees(math.atan2(m[1], m[0])),
                "xscale": math.hypot(m[0], m[1]),
                "yscale": math.hypot(m[4], m[5]),
            }

        def ss_is_part_hidden(self, name):
            """Whether ``name`` is hidden on the last rendered frame."""
            i = self.ss_part_index(name)
            if i < 0 or self._last_hidden is None:
                return True
            return i in self._last_hidden

    # Back-compat alias for the pre-rename class name (README / older scripts).
    SpriteStudioDisplayable = SSPlayer
