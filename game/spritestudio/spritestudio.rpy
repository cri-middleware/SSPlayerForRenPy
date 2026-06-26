# SpriteStudio Player for Ren'Py — M2 (full-fidelity Normal rendering)
#
# Renders a SpriteStudio 7 .ssab animation as a Creator-Defined Displayable.
# The heavy lifting (frame stepping, world transforms, UVs, vertex colours) is
# done by the native "Brain" (libssruntime) via ctypes; this file is only the
# thin Ren'Py rendering layer + the lazy setup/path wiring.
#
# Scope (M2): the Normal draw-batch kind, rendered from the per-vertex mesh the
# Brain emits (`framedata.build_mesh_parts`): shear / free-deform-exact world
# geometry, per-vertex `parts_color`, the framebuffer blend modes, and the
# PartColor blend modes (Mix/Mul/Add/Sub). Mesh / Effect / Mask / Shape /
# Instance / Text / NineSlice batch kinds are still skipped (M3/M4).
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
    from ss_renpy import ssruntime, framedata
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
    #       full atlas with gl_texture_wrap = REPEAT. Mirrors the Godot/Web/Unity
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
                    // out_rgb = pixel*varg.x + mix(1, pixel, varg.z)*color*varg.y  (§1-4-3)
                    vec3 wp = mix(vec3(1.0), p.rgb, u_ss_varg.z);
                    vec3 rgb = p.rgb * u_ss_varg.x + wp * u_ss_color.rgb * u_ss_varg.y;
                    gl_FragColor = vec4(rgb, p.a * u_ss_color.a);
                """,
            )
        except Exception as e:
            renpy.log("ss: register_shader(ss.partcolor) failed: %r" % (e,))

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

    class SpriteStudioDisplayable(renpy.Displayable):
        """Play one .ssab animation. Place it in a screen or `show` it.

            add SpriteStudioDisplayable("Basic.ssab") xalign 0.5 yalign 0.5
        """

        def __init__(self, ssab, animation=None, sprites_subdir="sprites",
                     loop=-1, speed=1.0, **kwargs):
            super(SpriteStudioDisplayable, self).__init__(**kwargs)
            self.ssab = ssab
            self.animation = animation
            self.sprites_subdir = sprites_subdir
            self.loop = loop
            self.speed = speed
            # runtime state (built lazily on first render)
            self._rt = None
            self._anim = None
            self._texmap = {}
            self._texpath = {}     # texture_hash -> "sprites/foo.png"
            self._base = {}        # path -> Image()
            self._last_st = None
            self._warned = set()

        # -- lazy native setup ---------------------------------------------
        def _ensure(self):
            if self._rt is not None:
                return
            path = os.path.join(self._SS_dir(), self.ssab)
            with open(path, "rb") as fh:
                data = fh.read()
            meta = SsabMeta(data)
            self._texmap = meta.texture_hash_map()
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

        # -- per-frame render ----------------------------------------------
        def render(self, width, height, st, at):
            self._ensure()
            dt = 0.0 if self._last_st is None else max(0.0, st - self._last_st)
            self._last_st = st
            frame_no = self._rt.update(dt)           # seconds -> ms internally
            fb = self._rt.get_frame_data(frame_no)

            r = renpy.Render(width, height)
            if fb:
                fd = framedata.parse(fb)
                parts = framedata.build_mesh_parts(self._rt, fd)
                ox, oy = width / 2.0, height / 2.0   # SS center -> screen center
                use_mesh = SS_RENDER_BACKEND == "mesh"
                for mp in parts:
                    drawn = False
                    if use_mesh:
                        drawn = self._draw_mesh(r, mp, ox, oy, st, at, width, height)
                    if not drawn:
                        self._draw_transform(r, mp, ox, oy, st, at, width, height)
            renpy.redraw(self, 0)                    # keep animating
            return r

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
            Godot/Web/Unity players do. ``parts_color`` is applied per-part
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

        def visit(self):
            return []

        # -- minimal playback API (callable from Ren'Py script) ------------
        def ss_play(self, animation=None, loop=-1):
            self._ensure()
            if animation and animation != self._anim:
                self._rt.setup_animation(animation)
                self._anim = animation
            self._rt.set_loop(loop)
            self._rt.play()
            renpy.redraw(self, 0)

        def ss_pause(self):
            if self._rt:
                self._rt.pause()

        def ss_set_frame(self, frame):
            if self._rt:
                self._rt.set_frame_no(frame)
                renpy.redraw(self, 0)
