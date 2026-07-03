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
# (particles), **Mesh(deform)** parts (skinned/free-deform meshes), and
# **Shape** parts (textureless procedural polygons — rect/triangle/star/arrow,
# filled by the PartColor) — all walked z-ordered via
# `ss_renpy.instance.collect_ordered` and batched by texture (shapes share the
# hash-0 / white-tex batch). Mask/clipping is handled by the mask section below;
# Text / NineSlice batch kinds are still skipped (later milestones). The
# engine-independent cores are headless-verified by tools/verify_*.py.
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
    import os, sys, math, time

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
    from ss_renpy import ssruntime, framedata, events, instance, effectplan, resolver, mask
    from ss_renpy.effect import EffectRig
    from ss_renpy.instance import InstanceRig, collect_ordered
    from ss_renpy.ssab_meta import SsabMeta
    from ss_renpy.player import SSInternalPlayer
    from ss_renpy.resource import ResourceManager

    # Load the native library once, from spritestudio/libs/<platform-arch>/.
    _SS_LIB = ssruntime.load_library(base_dir=os.path.join(_SS_ROOT, "libs"))

    # --- Opt-in render profiler (in-engine) --------------------------------
    # Run the game with env SS_PROFILE=1 to log the per-frame split between the
    # engine-independent geometry build (collect_ordered) and the Ren'Py draw
    # path (_draw_items: Mesh2 build + blit + shader). Headless tools can't time
    # the GPU/Mesh2 side, so this is the way to see whether geometry or drawing
    # dominates a real frame. Zero overhead when off (a couple of bool checks).
    SS_PROFILE = os.environ.get("SS_PROFILE", "") not in ("", "0", "false", "False")
    _ss_prof = {"n": 0, "geom": 0.0, "draw": 0.0, "total": 0.0, "drawn": 0}

    def _ss_prof_tick(geom, draw, total, drew):
        p = _ss_prof
        p["n"] += 1
        p["geom"] += geom
        p["draw"] += draw
        p["total"] += total
        p["drawn"] += 1 if drew else 0
        if p["n"] >= 120:
            n = p["n"]
            print("[SSPlayer] %d frames | geom %.3fms | draw %.3fms | total "
                  "%.3fms | rebuilt %d/%d" % (n, p["geom"] / n * 1000.0,
                  p["draw"] / n * 1000.0, p["total"] / n * 1000.0, p["drawn"], n))
            p.update(n=0, geom=0.0, draw=0.0, total=0.0, drawn=0)

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
    # Mask / clipping (09_mask). Needs the mesh backend + custom shaders +
    # offscreen Render-to-texture; set False to draw masked parts plainly
    # (geometry stays correct, the mask is simply not applied). The coverage
    # bitmap is sized to the writers' world bbox × the supersample factor, capped
    # at this long edge (px). The mask edge is a hard 1-bit test (no AA), so its
    # sharpness is limited by the coverage resolution: SUPERSAMPLE > 1 renders the
    # coverage above the bbox's world-pixel size so a scaled / high-DPI (Retina)
    # display doesn't show blocky stair-steps along the mask boundary. 2 suits a
    # 2× Retina display; raise it if the player is scaled up further.
    SS_ENABLE_MASK = True
    SS_MASK_COVERAGE_MAX_DIM = 2048
    SS_MASK_COVERAGE_SUPERSAMPLE = 2.0
    # RESERVED (no longer wired): the replay shader used to average a 4-tap grid
    # for edge AA, but that made it an outer×inner loop (up to 96 unrolled
    # texture-sampling iterations) that Metal/ANGLE could not reliably compile, so
    # the replay is now single-tap and the mask edge is antialiased solely by
    # SS_MASK_COVERAGE_SUPERSAMPLE. Kept defined so existing overrides don't error.
    SS_MASK_ANTIALIAS = True

    # Timeline events (UserData / Signal / Audio). The decoder is pure-Python and
    # headless-verified (tools/verify_events.py); collecting into the poll queue
    # is cheap and always on when enabled. Optional callbacks (see the
    # displayable constructor) run *inside* render() — keep them light; for
    # control flow (jumps, sound) prefer draining ss_poll_events() from a screen.
    SS_ENABLE_EVENTS = True

    # Register premultiplied gl_blend_func entries for the SS framebuffer
    # BlendTypes Ren'Py doesn't ship. Ren'Py's gl_blend_func gives the same raw
    # glBlendFuncSeparate/glBlendEquationSeparate access WebGL has, so we mirror
    # SSPlayerForWeb's applyBlend (spec §7) EXACTLY — Screen / Invert / Exclusion
    # included (Godot's 4-mode CanvasItemMaterial can't express those). Tuple is
    # (rgb_eq, rgb_src, rgb_dst, alpha_eq, alpha_src, alpha_dst); the alpha half
    # is always normal "over" so coverage/alpha composites correctly. All factors
    # act on PREMULTIPLIED src (Ren'Py GL2), matching WebGL's premultiplied path.
    _SS_BLEND_REGISTERED = False
    try:
        from renpy.uguu import (
            GL_FUNC_ADD, GL_FUNC_REVERSE_SUBTRACT, GL_ONE, GL_ZERO,
            GL_ONE_MINUS_SRC_ALPHA, GL_DST_COLOR, GL_ONE_MINUS_DST_COLOR,
            GL_ONE_MINUS_SRC_COLOR)
        _bf = renpy.config.gl_blend_func
        _A = (GL_FUNC_ADD, GL_ONE, GL_ONE_MINUS_SRC_ALPHA)   # alpha eq, src, dst
        _bf["ss_mul"]       = (GL_FUNC_ADD, GL_DST_COLOR, GL_ONE_MINUS_SRC_ALPHA) + _A
        _bf["ss_add"]       = (GL_FUNC_ADD, GL_ONE, GL_ONE) + _A
        _bf["ss_sub"]       = (GL_FUNC_REVERSE_SUBTRACT, GL_ONE, GL_ONE) + _A
        _bf["ss_screen"]    = (GL_FUNC_ADD, GL_ONE_MINUS_DST_COLOR, GL_ONE) + _A
        _bf["ss_invert"]    = (GL_FUNC_ADD, GL_ONE_MINUS_DST_COLOR, GL_ZERO) + _A
        _bf["ss_exclusion"] = (GL_FUNC_ADD, GL_ONE_MINUS_DST_COLOR, GL_ONE_MINUS_SRC_COLOR) + _A
        _SS_BLEND_REGISTERED = True
    except Exception as e:
        renpy.log("ss: custom gl_blend_func registration failed (%r); "
                  "Mul/Add via built-ins, other modes -> Mix" % (e,))

    # SS framebuffer BlendType -> gl_blend_func key. Mix (0) == normal (no
    # override). Mirrors SSPlayerForWeb applyBlend: the "2" / alpha variants that
    # have no GPU-native form fall back the same way (Mulalpha/Mul2 -> Mul,
    # Screen2 -> Screen); Div2 (9) / Overlay2 (11) have no equivalent -> Mix.
    SS_BLEND_FUNC_KEY = {
        1: "ss_mul" if _SS_BLEND_REGISTERED else "multiply",   # Mul
        2: "ss_add" if _SS_BLEND_REGISTERED else "add",        # Add
        3: "ss_sub",                                           # Sub
        4: "ss_mul",                                           # Mulalpha -> Mul
        5: "ss_screen",                                        # Screen
        6: "ss_exclusion",                                     # Exclusion
        7: "ss_invert",                                        # Invert
        8: "ss_mul",                                           # Mul2 -> Mul
        10: "ss_screen",                                       # Screen2 -> Screen
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

        # -- Mask / clipping (09_mask §3-2, coverage-bitmap hybrid) ----------
        # Two shaders implement the spec's stencil over an offscreen coverage:
        #
        #   ss.mask_write   — rasterizes ONE writer into the coverage bitmap.
        #       Cuts out by the part's texture alpha vs the per-frame threshold
        #       (255-mask)/255 (a textureless shape passes threshold<0 = whole
        #       geometry), then writes its pre-encoded bit colour with alpha 1 so
        #       an *additive* blend ORs disjoint writer bits into the RGB
        #       channels (8 bits x 3 = 24 writers).
        #
        #   ss.partcolor_mask — ss.partcolor_batched (PER-VERTEX colour) + the
        #       stencil REPLAY. Each masked target computes its coverage UV from
        #       a_position (Live2D's mask pattern), samples the coverage (nearest,
        #       emulated by snapping the
        #       UV to texel centres — Ren'Py has no per-texture nearest filter),
        #       replays the writers in draw order and discards by the inside/
        #       outside test. All in float math: Ren'Py shaders are GLSL ES 1.00
        #       / 120 with NO integer bitwise ops, so `~s & 0xFF` -> `255 - s`,
        #       `s + 1 & 0xFF` -> `mod(s + 1, 256)`, and the bit test is
        #       `mod(floor(byte / exp2(b)), 2)`. The loop is a constant 24 with an
        #       early `break` (ES 1.00 forbids uniform/while loop bounds).
        #
        # mask_meta[i] = (writer_rank, op_invert, is_clipping, _); the writer's
        # bit is the array index i itself (channel i/8, bit i%8).
        try:
            renpy.register_shader(
                "ss.mask_write",
                variables="""
                    uniform sampler2D tex0;
                    attribute vec2 a_tex_coord;
                    varying vec2 v_tex_coord;
                    uniform vec3 u_bit_color;   // bit value in one RGB channel
                    uniform float u_threshold;  // (255-mask)/255, <0 = no cutout
                """,
                vertex_300="v_tex_coord = a_tex_coord;",
                fragment_300="""
                    if (u_threshold >= 0.0) {
                        // Premultiplied atlas: .a is the true (un-multiplied)
                        // alpha, so the cutout is a straight alpha compare.
                        if (texture2D(tex0, v_tex_coord).a <= u_threshold)
                            discard;
                    }
                    // Additive blend ORs disjoint bits; alpha 1 keeps the bit.
                    gl_FragColor = vec4(u_bit_color, 1.0);
                """,
            )
            renpy.register_shader(
                "ss.partcolor_mask",
                variables="""
                    uniform sampler2D tex0;
                    uniform sampler2D tex1;     // coverage bitmap
                    attribute vec4 a_position;  // for the coverage UV (Live2D-style)
                    attribute vec2 a_tex_coord;
                    attribute vec4 a_ss_color;  // PER-VERTEX PartColor (not uniform)
                    attribute vec3 a_ss_varg;   // PER-VERTEX PartColor varg
                    varying vec2 v_tex_coord;
                    varying vec4 v_ss_color;
                    varying vec3 v_ss_varg;
                    uniform vec2 u_mask_origin;  // screen px of bbox min
                    uniform vec2 u_mask_size;    // bbox size (world px)
                    uniform vec2 u_cov_size;     // coverage tex px (nearest snap)
                    uniform int u_mask_count;
                    uniform float u_mask_rank;
                    uniform float u_mask_inside;     // 1 = draw inside, 0 = outside
                    uniform vec4 u_mask_meta[24];    // (rank, op_invert, clip, _)
                    varying vec2 v_mask_uv;
                """,
                vertex_300="""
                    v_tex_coord = a_tex_coord;
                    v_ss_color = a_ss_color;
                    v_ss_varg = a_ss_varg;
                    v_mask_uv = (a_position.xy - u_mask_origin) / u_mask_size;
                """,
                # NOTE: everything that references a uniform/varying MUST live in
                # this fragment_NNN part — Ren'Py only declares variables it sees
                # *here* (it does not scan fragment_functions), so the replay is
                # inlined. SINGLE-TAP (hardened): the earlier 4-tap rotated-grid AA
                # made this an outer×inner loop = up to 4×24 = 96 unrolled
                # iterations (ES 1.00 / GLSL 120 must unroll constant loops), each
                # with a texture sample — too large for reliable Metal/ANGLE
                # compilation. Now one tap; the mask edge is antialiased instead by
                # SS_MASK_COVERAGE_SUPERSAMPLE (coverage rendered above bbox px).
                # This mirrors Godot's ss_library_fs.glsl ss_mask_passes() exactly,
                # float-emulated (no integer bitwise ops in ES 1.00): the writer's
                # bit lives in coverage channel i/8 bit i%8 (mod/exp2 test), invert
                # is `255 - s`, increment is `mod(s + 1, 256)`.
                fragment_300="""
                    if (u_mask_count > 0) {
                        bool inside = u_mask_inside > 0.5;
                        vec2 uv = v_mask_uv;
                        if (uv.x < 0.0 || uv.x > 1.0 ||
                            uv.y < 0.0 || uv.y > 1.0) {
                            // bbox-outside == no writer covers it (§3-2): a
                            // visible-inside target discards, an outside target
                            // draws.
                            if (inside) discard;
                        } else {
                            // snap to texel centre -> nearest sampling (the
                            // coverage packs writer bits; linear filtering would
                            // corrupt the per-bit decode).
                            vec2 cuv = (floor(uv * u_cov_size) + 0.5) / u_cov_size;
                            vec4 cov = texture2D(tex1, cuv);
                            float stencil = 0.0;
                            for (int i = 0; i < 24; i++) {
                                if (i >= u_mask_count) break;
                                vec4 m = u_mask_meta[i];
                                bool clip = m.z > 0.5;
                                bool active = clip ? (u_mask_rank > m.x)
                                                   : (u_mask_rank < m.x);
                                if (!active) continue;
                                float fi = float(i);
                                float chan = floor(fi / 8.0);
                                float b = fi - chan * 8.0;
                                float cval = (chan < 0.5) ? cov.r
                                           : (chan < 1.5) ? cov.g : cov.b;
                                float byte = floor(cval * 255.0 + 0.5);
                                if (mod(floor(byte / exp2(b)), 2.0) < 0.5)
                                    continue;
                                if (m.y > 0.5) stencil = 255.0 - stencil; // invert
                                else stencil = mod(stencil + 1.0, 256.0); // incr
                            }
                            bool masked = stencil >= 0.5;
                            if (masked != inside) discard;               // §2-4
                        }
                    }
                    // ss.partcolor colour math (premultiplied in/out), PER-VERTEX
                    // (v_ss_color/v_ss_varg) so a gradient / shape fill masks with
                    // its true per-vertex colour — not a flat average.
                    vec4 p = texture2D(tex0, v_tex_coord);
                    vec3 s = p.a > 0.0 ? p.rgb / p.a : p.rgb;
                    vec3 wp = mix(vec3(1.0), s, v_ss_varg.z);
                    vec3 rgb = s * v_ss_varg.x + wp * v_ss_color.rgb * v_ss_varg.y;
                    float a = p.a * v_ss_color.a;
                    gl_FragColor = vec4(rgb * a, a);
                """,
            )
        except Exception as e:
            renpy.log("ss: register_shader(ss.mask_*) failed: %r" % (e,))

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

    def _ss_gl_blend(key):
        """Raw ('gl_blend_func', value) for a config key (e.g. 'add'), or None.

        Unlike :func:`_ss_blend_property` this is not gated by SS_ENABLE_BLEND —
        the mask coverage *requires* additive blending to OR writer bits.
        """
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

    # --- Asset loading (archive / .rpa aware) + dev discovery -------------
    # .ssab packs and their external-instance packs are read through Ren'Py's
    # loader, so they work whether shipped loose or inside a .rpa archive
    # (textures already load via Image, which is archive-aware). Paths are
    # gamedir-relative, e.g. "ss_assets/Ringo/Ringo.ssab".
    def _ss_open_bytes(rel):
        """Read a gamedir-relative file as bytes via Ren'Py's loader (.rpa-safe)."""
        predicting = getattr(renpy.display.predict, "predicting", False)
        if predicting:
            renpy.display.predict.predicting = False
        try:
            f = renpy.loader.load(rel)
            try:
                return f.read()
            finally:
                f.close()
        finally:
            if predicting:
                renpy.display.predict.predicting = True

    def _ss_renpy_pack_reader(base_rel):
        """Reader for external-instance packs: <base_rel>/<pack>.ssab via loader."""
        def read(pack_name):
            rel = (base_rel + "/" + pack_name + ".ssab") if base_rel \
                else (pack_name + ".ssab")
            try:
                return _ss_open_bytes(rel)
            except Exception:
                return b""
        return read

    # The dev asset browser (ss_browser.rpy) discovers packs through this index;
    # it enumerates via renpy.list_files so archived packs are listed too.
    # Override the scanned roots with `define ss_asset_dirs = [...]`. Built lazily
    # and cached; rebuilt each dev reload (the library lives in one init block).
    _SS_INDEX = None

    def _ss_get_index():
        global _SS_INDEX
        if _SS_INDEX is None:
            roots = [r.replace("\\", "/").strip("/")
                     for r in (getattr(store, "ss_asset_dirs", None) or ["ss_assets"])]
            rels = []
            for p in renpy.list_files():
                rp = p.replace("\\", "/")
                if rp.endswith(".ssab") and any(
                        rp == r or rp.startswith(r + "/") for r in roots):
                    rels.append(rp)
            _SS_INDEX = resolver.build_index(rels, _ss_open_bytes)
        return _SS_INDEX

    def ss_list_assets():
        """Dev/discovery helper: {pack_name: [animation, ...]} for each pack."""
        idx = _ss_get_index()
        return {r.stem: list(r.anim_names)
                for r in idx.records() if r.is_primary}

    class RenPyResourceManager(ResourceManager):
        """Ren'Py-backed texture cache injected into ``SSInternalPlayer``.

        The core asks us to ``acquire`` each texture path (gamedir-relative) an
        animation needs; we back that with Ren'Py ``Image`` displayables, which
        Ren'Py's own image / texture cache then loads and predicts. ``images()``
        feeds the displayable's ``visit`` so textures are preloaded (no first-
        playback stutter). The core never frees anything — Ren'Py owns lifetime.
        """
        def __init__(self):
            self._cache = {}    # path -> Image

        def acquire(self, path):
            if path and path not in self._cache:
                self._cache[path] = Image(path)

        def get(self, path):
            return self._cache.get(path)

        def image(self, path):
            d = self._cache.get(path)
            if d is None:
                d = Image(path)
                self._cache[path] = d
            return d

        def images(self):
            return list(self._cache.values())

    class SSPlayer(renpy.Displayable):
        """Play one SpriteStudio .ssab pack. Place it in a screen or `show` it.

            add SSPlayer("ss_assets/overall/Basic.ssab") xalign 0.5 yalign 0.5

        One instance plays one .ssab; select an animation in it by name
        (constructor ``animation=`` or :meth:`ss_set_animation`). Renders Normal,
        Instance (nested child animations) and Effect (particle) parts, exposing
        a small ``ss_*`` playback / control / query API.
        """

        def __init__(self, ssab, animation=None, sprites_subdir=None,
                     loop=-1, speed=1.0, sub_frame=True, size=None,
                     attachments=None,
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
            # Textures and external-instance packs are exported co-located with
            # the .ssab, so the directory that holds the .ssab is the single base
            # for all of them — the caller does not need a separate sprites_subdir.
            # `sprites_subdir`, when given, is just a legacy prefix kept for
            # backwards compatibility; the base is always re-derived from the
            # resolved .ssab path below.
            _relpath = (sprites_subdir.rstrip("/\\") + "/" + ssab) if sprites_subdir else ssab
            _relpath = _relpath.replace("\\", "/").lstrip("/")
            self._ssab_relpath = _relpath
            if "/" in _relpath:
                self._base_dir, self._ssab_name = _relpath.rsplit("/", 1)
            else:
                self._base_dir, self._ssab_name = "", _relpath
            self.speed = speed
            # Sub-frame interpolation: when off the frame handed
            # to the Brain for *display* is floored; the playback
            # head stays a raw float either way (docs/06). By default, it is now on.
            self._sub_frame = bool(sub_frame)
            # Layout size. Given as (w, h) (or a single number for a square),
            # render() reports a box of that size and centers the animation
            # within it, so `xalign` / `xpos` / `pos` and container layout work
            # like a normal image. None (default) keeps the legacy behaviour of
            # filling the whole offered area (then position with xoffset/yoffset).
            # `zoom` / Transform still scale the rendered result either way.
            if size is None:
                self._size = None
            elif isinstance(size, (int, float)):
                self._size = (int(size), int(size))
            else:
                self._size = (int(size[0]), int(size[1]))
            # Optional attachments: {part_name: displayable}. Drawn at each named
            # part's current position every frame (e.g. a speech bubble on the
            # head, an item in the hand). v1 is translation-only.
            self._attachments = dict(attachments) if attachments else None
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
            # Delegation: the engine-independent playback core (built lazily on
            # first render) owns the runtime, metadata, rigs and timeline events.
            # This displayable is the Ren'Py adapter around it.
            self._core = None       # ss_renpy.player.SSInternalPlayer
            self._rm = None         # RenPyResourceManager (Ren'Py texture cache)
            self._texpath = {}      # texture_hash -> gamedir-rel image path (cache)
            self._last_st = None
            self._warned = set()
            self._mask_white = None  # cached white tex0 for textureless writers

        def __getstate__(self):
            """Drop the native-backed core + caches for pickling/saves; they are
            rebuilt lazily on the next render (re-applying the animation)."""
            state = self.__dict__.copy()
            state["_core"] = None
            state["_rm"] = None
            state["_texpath"] = {}
            state["_last_st"] = None
            state["_warned"] = set()
            return state

        # -- image attributes (_duplicate, _list_attributes) ---------------
        def _get_available_animations(self):
            # Cache the available animations. _ss_open_bytes temporarily bypasses
            # Ren'Py's prediction lock ("Refusing to open ... while predicting"),
            # so reading the .ssab here during prediction will succeed.
            if self._available_animations is None:
                try:
                    meta = SsabMeta(_ss_open_bytes(self._ssab_relpath))
                    self._available_animations = meta.animation_names()
                except Exception:
                    return []
            return self._available_animations

        def _list_attributes(self, tag, attributes):
            """Tell Ren'Py what attributes (animations/aliases) this displayable accepts."""
            available = set(self._get_available_animations())
            available.update(self.aliases.keys())
            return list(available)

        def _choose_attributes(self, tag, required, optional):
            """Resolve `show <tag> <attr>` to a canonical name when the pack was
            first shown with NO attribute (so its only registered entry is the
            bare tag, e.g. via `renpy.image(tag, SSPlayer(...))` + `show <tag>`).

            Ren'Py's choose_image() calls this hook to attach a new
            animation/alias attribute onto an already-registered displayable.
            Without it, `renpy.show("<tag> talk")` (e.g. SSCharacter's lip-flap
            callback) finds no matching image and the sprite never switches — it
            only works when the FIRST show already carried an attribute (which
            takes the ImageReference.find_target path instead). Every required
            attribute must name one of our animations or aliases, else this
            image does not match. SSPlayer plays one animation at a time, so the
            required attribute(s) fully determine it; stale `optional` (previous)
            attributes are dropped."""
            valid = set(self._get_available_animations())
            valid.update(self.aliases.keys())
            for a in required:
                if a not in valid:
                    return None
            return tuple(required)

        def _duplicate(self, args):
            """Spawn a FRESH SSPlayer instance for `show ssplayer [attributes]`.

            Always returns a NEW copy (never `self`), even with no attributes.
            The registered template must never be the instance actually shown:
            Ren'Py marks a shown displayable unique (``_duplicatable = False``)
            via ``_unique()``, so if `show <tag>` (no attribute) returned the
            template itself, the template would be poisoned and every later
            `show <tag> <attr>` would call ``_duplicate`` on a now-non-
            duplicatable template and get `self` back — never switching the
            animation. (This silently broke SSCharacter lip-flap: showing the
            character with no attribute, then switching to ``talk``, kept
            replaying the idle template instead of playing ``talk``.)"""
            if not getattr(self, "_duplicatable", True):
                return self

            # Start from the template's original spec (may be a list = sequence),
            # then let any attribute(s) pick the alias / animation to play.
            target_anim = self._initial_animation
            if args and getattr(args, "args", None):
                for attr in args.args:
                    if attr in self.aliases:
                        target_anim = self.aliases[attr]
                    elif attr in self._get_available_animations():
                        target_anim = attr

            # Return a copy configured for the chosen animation.
            rv = SSPlayer(
                self.ssab,
                animation=target_anim,
                sprites_subdir=self.sprites_subdir,
                loop=self.loop,
                speed=self.speed,
                sub_frame=self._sub_frame,
                size=self._size,
                attachments=self._attachments,
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
            if self._core is not None:
                return
            # Read the .ssab through Ren'Py's loader so it works loose or in a
            # .rpa archive. `self.ssab` is the gamedir-relative path the caller
            # passed (e.g. "ss_assets/Ringo/Ringo.ssab").
            try:
                data = _ss_open_bytes(self._ssab_relpath)
            except Exception as e:
                raise Exception(
                    "ss: cannot load .ssab %r — check the path (gamedir-relative, "
                    "e.g. \"ss_assets/Ringo/Ringo.ssab\") and that the file ships "
                    "with the game. [%s]" % (self.ssab, e))
            # Build the engine-independent core; the RenPyResourceManager we hand
            # it backs texture loading with Ren'Py's image cache (set_animation
            # acquires this pack's textures), and the pack_reader resolves external
            # instance packs co-located with the .ssab (also archive-aware).
            self._rm = RenPyResourceManager()
            self._core = SSInternalPlayer(
                data, lib=_SS_LIB, base_dir=self._base_dir,
                resource_manager=self._rm,
                pack_reader=_ss_renpy_pack_reader(self._base_dir),
                sub_frame=self._sub_frame,
                enable_events=SS_ENABLE_EVENTS,
            )
            self._start_initial()

        def _start_initial(self, start_frame=-1.0):
            """Set up + play the constructor's animation (or sequence) on the core.

            The pure core plays ONE animation; *sequence* policy lives here in the
            host: for a list we play the first now and keep the rest in
            ``self._anim_queue``, advancing on each ``FramePlan.finished`` in
            render(). This mirrors the SSPlayerForGodot node owning chaining over
            its SsInternalPlayer (the core itself has no notion of a queue)."""
            core = self._core
            core.set_speed(self.speed)
            anim = self._initial_animation
            if isinstance(anim, (list, tuple)) and anim:
                seq = list(anim)
                first = seq.pop(0)
                self._anim_queue = seq
                core.set_loop(1 if seq else self._initial_loop)
                ok = core.set_animation(first)
            else:
                self._anim_queue = []
                core.set_loop(self._initial_loop)
                ok = core.set_animation(anim)   # anim may be None -> first available
            if not ok:
                raise Exception(
                    "ss: animation %r not found in %s (have: %s)"
                    % (anim, self.ssab,
                       ", ".join(core.animation_names()) or "(none)"))
            if start_frame is not None and start_frame >= 0:
                core.play(start_frame=start_frame)
            else:
                core.play()
            self.animation = core.animation

        def _texture_path(self, thash):
            # Resolve via the core (which owns the cellmap → image map, merged
            # with any external instance packs). Cached per displayable for the
            # per-part hot path.
            path = self._texpath.get(thash)
            if path is None:
                path = self._core.texture_path(thash) if self._core else ""
                self._texpath[thash] = path
            return path

        def _base_image(self, tex_path):
            # Image lifetime is owned by the RenPyResourceManager (Ren'Py cache).
            return self._rm.image(tex_path)

        def _warn_once(self, key, msg):
            if key not in self._warned:
                self._warned.add(key)
                renpy.log("ss: " + msg)

        # -- timeline events (UserData / Signal / Audio) -------------------
        def _dispatch_plan(self, plan):
            """Fan this frame's timeline events + the ``looped`` edge out to the
            optional push callbacks; never raises. Sequence chaining and the
            ``finished`` callback are handled in render() (host playback policy) —
            the core only *reports* the finished edge, it never decides what to
            play next. Timeline events are gated by SS_ENABLE_EVENTS (the core
            doesn't collect them when off); the playback-lifecycle callbacks are
            not — that knob is for UserData/Signal/Audio.
            """
            try:
                if SS_ENABLE_EVENTS:
                    for fe in plan.events:
                        self._dispatch_frame_events(fe)
                if plan.looped:
                    self._call_cb(self.on_looped)
            except Exception as e:
                self._warn_once("event-pump",
                                "event dispatch failed (%r); events disabled "
                                "this frame" % (e,))

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
            self._ensure()
            return self._core.poll_events()

        # -- per-frame render ----------------------------------------------
        def render(self, width, height, st, at):
            self._ensure()

            # Detect re-show (time went backwards) -> restart from the top
            # (resets the animation sequence too).
            core = self._core
            if self._last_st is not None and st < self._last_st:
                self._start_initial(start_frame=0)
                self._call_cb(self.on_started)

            _t0 = time.perf_counter() if SS_PROFILE else 0.0
            dt = 0.0 if self._last_st is None else max(0.0, st - self._last_st)
            self._last_st = st
            # Advance the engine-independent core (it takes milliseconds) and get
            # this frame's z-ordered, world-space draw plan.
            _tg = time.perf_counter() if SS_PROFILE else 0.0
            plan = core.update(dt * 1000.0)
            _geom = (time.perf_counter() - _tg) if SS_PROFILE else 0.0
            self.animation = core.animation
            self._dispatch_plan(plan)            # timeline events + on_looped
            # Sequence chaining is the host's playback policy: when the core
            # reports the play->stop edge, advance to the next queued animation
            # (e.g. an alias like ["attack1", "wait1"]) or fire on_finished. The
            # switch happens HERE, between updates — so every frame's draw plan
            # stays consistent with a single animation (no mid-update frame skew).
            if plan.finished:
                if self._anim_queue:
                    nxt = self._anim_queue.pop(0)
                    core.set_loop(1 if self._anim_queue else self._initial_loop)
                    core.set_animation(nxt)
                    core.play()
                    self.animation = core.animation
                    self._call_cb(self.on_started)
                    renpy.redraw(self, 0)
                else:
                    self._call_cb(self.on_finished)

            _draw = 0.0
            # With an explicit `size`, report a box of that size and center the
            # animation within it, so xalign / xpos / pos position us like a
            # normal image; otherwise fill the whole offered area (legacy).
            rw, rh = self._size if self._size else (width, height)
            r = renpy.Render(rw, rh)
            ox, oy = rw / 2.0, rh / 2.0   # SS center -> box center
            if plan.items:
                _td = time.perf_counter() if SS_PROFILE else 0.0
                # Mask: rasterize each distinct coverage once before drawing the
                # targets that sample it (09_mask §3-2). Failure leaves the dict
                # empty so masked parts simply draw unmasked.
                cov_by_id = {}
                if SS_ENABLE_MASK:
                    self._build_coverages(cov_by_id, plan.items, ox, oy, st, at,
                                          rw, rh)
                self._draw_items(r, plan.items, ox, oy, st, at, rw, rh, cov_by_id)
                if SS_PROFILE:
                    _draw = time.perf_counter() - _td

            # Attachments: draw each {part_name: displayable} at that part's
            # current position (v1 = translation only). Guarded so it can never
            # break rendering; nudge with the child's own offset if needed.
            if self._attachments:
                for _pname, _child in self._attachments.items():
                    try:
                        _t = core.part_transform(_pname)
                        if _t is None:
                            continue
                        _cr = renpy.render(_child, rw, rh, st, at)
                        _cw, _ch = _cr.get_size()
                        r.blit(_cr, (int(ox + _t["x"] - _cw / 2.0),
                                     int(oy + _t["y"] - _ch / 2.0)))
                    except Exception:
                        pass

            # Keep requesting redraws only while something is actually moving; an
            # idle sprite (paused / stopped / play-once finished, no live rigs)
            # renders an identical frame, so we let it go quiescent until a
            # control method (ss_play/ss_resume/ss_set_frame/ss_stop/...) re-arms
            # it. is_animating() stays True while effects / instances run.
            if core.is_animating():
                renpy.redraw(self, 0)
            if SS_PROFILE:
                _ss_prof_tick(_geom, _draw, time.perf_counter() - _t0, bool(plan.items))
            return r

        # -- draw dispatch (batched) ---------------------------------------
        def _draw_items(self, r, items, ox, oy, st, at, width, height,
                        cov_by_id=None):
            """Draw the z-ordered renderables, batching consecutive same-texture
            Normal parts into one mesh/blit (and each effect batch likewise).

            A run breaks when the texture or framebuffer blend changes, an effect
            batch interrupts it, or a masked part is reached — preserving draw
            order. A masked part (``MeshPart.mask`` set, with a coverage in
            ``cov_by_id``) draws per-part through ``ss.partcolor_mask`` instead of
            batching. Falls back to per-part / unmasked drawing on any failure."""
            use_mesh = SS_RENDER_BACKEND == "mesh"
            can_batch = SS_BATCH_DRAW and use_mesh and _SS_PC_LAYOUT is not None
            run = []
            run_key = None
            for tag, payload in items:
                if tag == "mesh":
                    ap = payload.mask
                    cov = (cov_by_id.get(id(ap.frame_mask))
                           if ap is not None and cov_by_id else None)
                    if cov is not None:
                        # Masked: flush the current run, then draw it on its own
                        # (the replay shader can't share a batched mesh).
                        if run:
                            self._flush_mesh_run(r, run, ox, oy, st, at, width,
                                                 height, can_batch, use_mesh)
                            run = []
                            run_key = None
                        if not self._draw_mesh_masked(r, payload, ap, cov, ox, oy,
                                                      st, at, width, height):
                            self._flush_mesh_run(r, [payload], ox, oy, st, at,
                                                 width, height, can_batch, use_mesh)
                        continue
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
                        run_key = None
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
                cr = self._tex0_render(mp.texture_hash, st, at, width, height)
                if cr is None:
                    return False
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

        # -- mask / clipping (09_mask §3-2): coverage + replay --------------
        def _white_render(self, st, at):
            """A small white tex0 for texture-less shape writers (no cutout)."""
            if self._mask_white is None:
                self._mask_white = Solid("#ffffffff", xysize=(2, 2))
            return renpy.render(self._mask_white, 2, 2, st, at)

        def _tex0_render(self, thash, st, at, width, height):
            """tex0 source for a mesh/shape draw: the bound atlas for a real
            ``texture_hash``, or a 2x2 white for a textureless Shape part
            (``thash == 0``) — the PartColor (rate forced 1.0) then supplies the
            fill. Returns the render, or None when a non-zero hash can't resolve
            (so the caller can fall back)."""
            if thash == 0:
                return self._white_render(st, at)
            tex = self._texture_path(thash)
            if not tex:
                return None
            return renpy.render(self._base_image(tex), width, height, st, at)

        def _build_coverages(self, cov_by_id, items, ox, oy, st, at,
                             width, height):
            """Rasterize the coverage bitmap for every distinct ``FrameMask`` in
            ``items`` into ``cov_by_id`` (keyed by ``id(frame_mask)``).

            One coverage is shared by all targets of a mask (including instance
            children that inherit it). A build failure is warned once and that
            coverage is simply skipped (its targets then draw unmasked)."""
            if _SS_Mesh2 is None:
                return
            seen = set()
            for tag, mp in items:
                if tag != "mesh" or mp.mask is None:
                    continue
                fm = mp.mask.frame_mask
                key = id(fm)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    cov = self._build_coverage(fm, ox, oy, st, at, width, height)
                except Exception as e:
                    self._warn_once("mask-coverage",
                                    "coverage build failed (%r); masks off this "
                                    "frame" % (e,))
                    cov = None
                if cov is not None:
                    cov_by_id[key] = cov

        def _build_coverage(self, fm, ox, oy, st, at, width, height):
            """Render all of ``fm``'s writers into one offscreen RGBA8 coverage.

            Returns ``(coverage_render, cov_w, cov_h)`` or None. The coverage is
            sized to the writers' world bbox (long edge capped at
            SS_MASK_COVERAGE_MAX_DIM); each writer is drawn with ``ss.mask_write``
            under *additive* blend so disjoint bits OR together (09_mask §3-2-1).
            Built in bbox-local pixel space so the target's ``v_mask_uv`` (derived
            from a_position via the same bbox) indexes it directly."""
            if _SS_Mesh2 is None or not fm.writers:
                return None
            bx, by = fm.bmin
            bw, bh = fm.bsize
            ss = max(1.0, SS_MASK_COVERAGE_SUPERSAMPLE)
            cw = max(2, min(SS_MASK_COVERAGE_MAX_DIM, int(round(bw * ss))))
            ch = max(2, min(SS_MASK_COVERAGE_MAX_DIM, int(round(bh * ss))))
            sx, sy = cw / bw, ch / bh             # world -> coverage px
            add_prop = _ss_gl_blend("add")
            cov = renpy.Render(cw, ch)
            for w in fm.writers:
                try:
                    self._blit_writer(cov, w, bx, by, sx, sy, cw, ch,
                                      st, at, width, height, add_prop)
                except Exception:
                    pass   # one bad writer must not blank the whole coverage
            return (cov, cw, ch)

        def _blit_writer(self, cov, w, bx, by, sx, sy, cw, ch,
                         st, at, width, height, add_prop):
            """Additively rasterize one writer's bit into the coverage ``cov``."""
            pts = w.positions
            npts, ntri = len(pts), len(w.triangles)
            if npts < 3 or ntri < 1:
                return
            tex = self._texture_path(w.texture_hash) if w.has_texture else ""
            if tex:
                cr = renpy.render(self._base_image(tex), width, height, st, at)
                tw, th = cr.get_size()
                if tw <= 0 or th <= 0:
                    return
                nuv = framedata.normalize_uvs(w.uvs, tw, th)
                threshold = (255.0 - w.mask_value) / 255.0
            else:
                cr = self._white_render(st, at)   # texture-less: whole geometry
                nuv = [(0.0, 0.0)] * npts
                threshold = -1.0

            mesh = _SS_Mesh2(_SS_TEXTURE_LAYOUT, npts, ntri)
            geom = []
            for (x, y) in pts:
                geom += [(x - bx) * sx, (y - by) * sy]   # world -> coverage px
            mesh.set_geometry_data(geom)
            attrs = []
            for (u, v) in nuv:
                attrs += [u, v]
            mesh.set_attribute_data(attrs)
            idx = []
            for tri in w.triangles:
                idx += [tri[0], tri[1], tri[2]]
            mesh.set_triangle_data(idx)

            wr = renpy.Render(cw, ch)
            wr.blit(cr, (0, 0))                  # tex0 (cutout source / white)
            wr.mesh = mesh
            if tex and _SS_TEXTURE_WRAP is not None:
                wr.add_property("texture_wrap_tex0", _SS_TEXTURE_WRAP)
            wr.add_shader("ss.mask_write")
            chan = w.bit // 8
            val = float(1 << (w.bit % 8)) / 255.0
            bc = [0.0, 0.0, 0.0]
            bc[chan] = val
            wr.add_uniform("u_bit_color", (bc[0], bc[1], bc[2]))
            wr.add_uniform("u_threshold", threshold)
            if add_prop is not None:
                try:
                    wr.add_property(*add_prop)
                except Exception:
                    pass
            cov.blit(wr, (0, 0))

        def _mask_meta_uniform(self, fm):
            """Flat ``vec4[MAX_WRITERS]`` of (rank, op_invert, is_clipping, 0).

            The writer's bit is its index, so it is not stored. Padded to the
            full array length the shader declares."""
            vals = []
            for (rank, _bit, op, clip) in fm.meta:
                vals += [float(rank), float(op), float(clip), 0.0]
            need = mask.MAX_WRITERS * 4
            if len(vals) < need:
                vals += [0.0] * (need - len(vals))
            return vals

        def _draw_mesh_masked(self, r, mp, ap, cov, ox, oy, st, at, width, height):
            """Draw one masked part via ``ss.partcolor_mask`` (coverage replay).

            Per-vertex colour (like :meth:`_draw_mesh_batch`, one part) so a
            gradient / textureless Shape fill masks with its TRUE colour, not a
            flat average. Binds the coverage as tex1 + the replay uniforms
            (target rank / polarity + the writers' meta), and a 2x2 white tex0 for
            a textureless Shape (``texture_hash == 0``) via :meth:`_tex0_render` so
            a Shape target is clipped instead of falling through unmasked. Returns
            True on success; False makes the caller draw it unmasked."""
            if _SS_Mesh2 is None or _SS_PC_LAYOUT is None:
                return False
            try:
                cov_render, cw, ch = cov
                cr = self._tex0_render(mp.texture_hash, st, at, width, height)
                if cr is None:
                    return False
                tw, th = cr.get_size()
                if tw <= 0 or th <= 0:
                    return False

                pts = mp.positions
                nuv = framedata.normalize_uvs(mp.uvs, tw, th)
                tris = mp.triangles
                mesh = _SS_Mesh2(_SS_PC_LAYOUT, len(pts), len(tris))
                geometry = []
                attributes = []
                for idx in range(len(pts)):
                    x, y = pts[idx]
                    geometry += [ox + x, oy + y]
                    u, v = nuv[idx]
                    c = mp.colors[idx]
                    vx, vy, vz = framedata.partcolor_varg(
                        mp.color_blend, mp.rates[idx])
                    attributes += [u, v, c[0], c[1], c[2], c[3], vx, vy, vz]
                mesh.set_geometry_data(geometry)
                mesh.set_attribute_data(attributes)
                indices = []
                for tri in tris:
                    indices += [tri[0], tri[1], tri[2]]
                mesh.set_triangle_data(indices)

                rv = renpy.Render(width, height)
                rv.blit(cr, (0, 0))                  # tex0 atlas / white
                rv.blit(cov_render, (0, 0))          # tex1 coverage
                if _SS_TEXTURE_WRAP is not None:
                    rv.add_property("texture_wrap_tex0", _SS_TEXTURE_WRAP)
                rv.mesh = mesh
                rv.add_shader("ss.partcolor_mask")
                fm = ap.frame_mask
                bx, by = fm.bmin
                bw, bh = fm.bsize
                rv.add_uniform("u_mask_origin", (ox + bx, oy + by))
                rv.add_uniform("u_mask_size", (bw, bh))
                rv.add_uniform("u_cov_size", (float(cw), float(ch)))
                rv.add_uniform("u_mask_count", len(fm.meta))
                rv.add_uniform("u_mask_rank", float(ap.rank))
                rv.add_uniform("u_mask_inside", 1.0 if ap.visible_inside else 0.0)
                rv.add_uniform("u_mask_meta", self._mask_meta_uniform(fm))
                self._apply_blend(rv, mp)
                r.blit(rv, (0, 0))
                return True
            except Exception as e:
                self._warn_once("mask-draw",
                                "masked draw failed (%r); drawing unmasked"
                                % (e,))
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
            try:
                cr = self._tex0_render(parts[0].texture_hash, st, at, width, height)
                if cr is None:
                    return False
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
            # Preload textures via Ren'Py prediction. set_animation already
            # acquired this pack's textures into the RenPyResourceManager (plus
            # external instance packs as they load); hand those Images back so
            # Ren'Py preloads them — no first-playback stutter.
            try:
                self._ensure()
                return self._rm.images() if self._rm else []
            except Exception:
                return []

        # -- playback / control / query API --------------------------------
        # A small ss_-prefixed, Ren'Py-idiomatic surface that delegates to the
        # engine-independent core. set_animation/play are split (docs/06 §4):
        # set_animation loads+poses; ss_play starts.
        def ss_set_animation(self, name):
            """Load + pose animation ``name`` (does NOT start playback).

            Front-loads the heavy work — native setup, texture acquisition, and
            Instance child-context allocation — so a later :meth:`ss_play` starts
            instantly (docs/06 §4 setAnimation/play split).
            """
            if self._core is None:
                if name:
                    self.animation = name      # build straight into `name`
                self._ensure()
                return True
            if not name or name == self._core.animation:
                return True
            if not self._core.set_animation(name):
                self._warn_once(("anim", name),
                                "setup_animation(%r) failed" % name)
                return False
            self.animation = self._core.animation
            renpy.redraw(self, 0)
            return True

        def ss_get_animation(self):
            return self._core.animation if self._core else self.animation

        def ss_animation_names(self):
            self._ensure()
            return self._core.animation_names()

        def ss_play(self, animation=None, loop=None, start_frame=-1.0):
            """Start playback (optionally switching animation / loop first).

            ``start_frame >= 0`` begins at that frame; otherwise resumes from the
            section start. Re-arms Instance/Effect slots so they re-fire."""
            self._ensure()
            if animation:
                self.ss_set_animation(animation)
            if loop is not None:
                self.loop = loop
                self._core.set_loop(loop)
            if start_frame is not None and start_frame >= 0:
                self._core.play(start_frame=start_frame)
            else:
                self._core.play()
            self.animation = self._core.animation
            self._call_cb(self.on_started)
            renpy.redraw(self, 0)

        def ss_pause(self):
            if self._core:
                self._core.pause()

        def ss_resume(self):
            if self._core:
                self._core.resume()
                renpy.redraw(self, 0)

        def ss_stop(self):
            if self._core:
                self._core.stop()
                # stop() may jump the head (e.g. back to the start frame); re-arm
                # so the change is shown even if the loop had gone quiescent.
                renpy.redraw(self, 0)

        def ss_is_playing(self):
            return bool(self._core and self._core.is_playing())

        def ss_is_pausing(self):
            return bool(self._core and self._core.is_pausing())

        def ss_get_frame(self):
            return self._core.frame_no if self._core else 0.0

        def ss_set_frame(self, frame):
            if self._core:
                self._core.set_frame(frame)
                renpy.redraw(self, 0)

        def ss_total_frames(self):
            return self._core.total_frames if self._core else 0

        def ss_start_frame(self):
            return self._core.start_frame if self._core else 0

        def ss_end_frame(self):
            return self._core.end_frame if self._core else 0

        def ss_set_speed(self, speed):
            self.speed = speed
            if self._core:
                self._core.set_speed(speed)

        def ss_get_speed(self):
            return self.speed

        def ss_set_loop(self, count):
            self.loop = count
            if self._core:
                self._core.set_loop(count)

        def ss_get_loop(self):
            return self.loop

        def ss_set_section(self, start, end):
            if self._core:
                self._core.set_section(start, end)
                renpy.redraw(self, 0)

        def ss_set_playback_direction(self, direction, style=0):
            """``direction``: 0=forward, 1=reverse; ``style``: 0=normal, 1=ping-pong."""
            if self._core:
                self._core.set_playback_direction(direction, style)

        def ss_set_frame_rate(self, fps):
            if self._core:
                self._core.set_frame_rate(fps)

        def ss_get_frame_rate(self):
            return self._core.fps if self._core else 0

        def ss_set_sub_frame_enabled(self, enabled):
            """Toggle sub-frame interpolation (default on)."""
            self._sub_frame = bool(enabled)
            if self._core:
                self._core.set_sub_frame(enabled)
            renpy.redraw(self, 0)

        def ss_is_sub_frame_enabled(self):
            return self._sub_frame

        # -- part query ----------------------------------------------------
        def ss_part_names(self):
            self._ensure()
            return self._core.part_names()

        def ss_part_index(self, name):
            self._ensure()
            return self._core.part_index(name)

        def ss_part_transform(self, name):
            """Player-local transform of a part on the last rendered frame, or
            ``None``: a dict with x/y (px), rotation (deg), xscale/yscale."""
            return self._core.part_transform(name) if self._core else None

        def ss_is_part_hidden(self, name):
            """Whether ``name`` is hidden on the last rendered frame."""
            return self._core.is_part_hidden(name) if self._core else True

    # Back-compat alias for the pre-rename class name (README / older scripts).
    SpriteStudioDisplayable = SSPlayer
