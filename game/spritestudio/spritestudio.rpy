# SpriteStudio Player for Ren'Py — SSPlayer
#
# Renders a SpriteStudio 7 .ssab animation pack as a Creator-Defined Displayable.
# One SSPlayer instance plays one .ssab and selects an animation in it by name:
#
#     add SSPlayer("ss_assets/Ringo/Ringo.ssab", animation="Idle") xalign 0.5 yalign 0.5
#
# The heavy lifting (frame stepping, world transforms, UVs, vertex colours,
# particle sim) is done by the native "Brain" (libssruntime) via ctypes; this
# file is the thin Ren'Py rendering layer + setup/path wiring around it.
#
# Supported part kinds: Normal (per-vertex mesh — shear / free-deform, per-vertex
# parts_color, framebuffer + PartColor blend), Instance (nested child animations,
# synced or independent, recursive), Effect (particles), Mesh/deform, and Shape
# (textureless procedural polygons — rect / triangle / star / arrow, filled by the
# PartColor). Mask / clipping and the SS6 user-shader family (ss-*) are supported
# too. Text / NineSlice parts are not drawn yet.
#
# Timeline events (UserData / Signal / Audio) are surfaced via the optional on_*
# callbacks and the ss_poll_events() queue; `finished` / `looped` derive from
# runtime state. Playing audio is normally the host's job — the Player reports the
# trigger and, with SS_ENABLE_AUDIO (default on), also plays it through Ren'Py.
#
# Rendering conventions that can vary by Ren'Py build / GPU (rotation sign, mirror
# axis, blend, mask, render backend) are exposed as the SS_* tuning knobs below.
# The defaults are known-good; override a knob only if something looks wrong on
# your target. The engine-independent cores are headless-verified by
# tools/verify_*.py; GL2 rendering is signed off visually (Shift+B / run-demo).

init -10 python:
    import os
    import sys, math, time

    # Packaging (build.classify): the library classifies only its OWN files — its
    # per-platform native libraries (below). The `.ssab` / `.ssqb` pack formats hold
    # the GAME's own assets, so shipping those is the game's responsibility, done in
    # its options.rpy alongside the audio rules (see game/options.rpy) — NOT here.
    # build.classify is FIRST-MATCH-WINS by registration order, and this runs at
    # init -10, so a game can override any of it from an EARLIER init in options.rpy.

    # Native libraries: ship ONLY the target platform's binary, mirroring Ren'Py's
    # own per-platform lib tagging (renpy/common/00build.rpy). Without this a mac
    # .app would also carry the Windows .dll / Linux .so / Web .wasm — dead weight.
    # The two `None` excludes come first (first-match-wins) so they win over the
    # lib patterns below:
    #  * stale __pycache__ from headless CPython test runs — never ship it;
    #  * the converter (libssconverter.*) is an import- / dev-time tool used by
    #    auto_importer (gated on config.developer); a shipped game never loads it.
    build.classify('**/__pycache__/**', None)
    build.classify('**/*ssconverter.*', None)
    build.classify('**/spritestudio/libs/macos/**', 'mac')
    build.classify('**/spritestudio/libs/windows/x86_64/**', 'windows')
    build.classify('**/spritestudio/libs/linux/x86_64/**', 'linux')
    build.classify('**/spritestudio/libs/linux/aarch64/**', 'linux_arm')
    # Android: the Brain ships in the APK's lib/<abi>/ (jniLibs) — staged there at
    # build time by deploy-android.* — and is loaded by soname at runtime, NOT from
    # the game tree. So exclude it from the packaged assets (like the iOS xcframework
    # below), or it would ship twice (once in lib/, once as dead weight in assets/).
    build.classify('**/spritestudio/libs/android/**', None)
    # iOS: the Brain is a dynamic xcframework linked + embedded into the app via
    # Xcode (Embed & Sign), NOT loaded from the game tree at runtime — so exclude
    # it from the packaged data, or it ships twice (once embedded, once dead
    # weight under base/). Instead it is added to the Xcode target via Embed &
    # Sign — scripts/deploy-ios.sh generates the project and the demo/consumer
    # both do that one step by hand (docs/en/export.md -> iOS Export).
    build.classify('**/spritestudio/libs/ios/**', None)
    build.classify('**/spritestudio/libs/web/**', 'web')

    # This library lives at <gamedir>/spritestudio/ by convention. If you drop
    # it somewhere else, set `store.spritestudio_root` in an earlier init block
    # (e.g. `init -20 python: spritestudio_root = "..."`), or edit this line.
    _SS_ROOT = getattr(store, "spritestudio_root", None) or \
        os.path.join(renpy.config.gamedir, "spritestudio")
    # ss_renpy, the generated ss.* bindings, and flatbuffers all live under python/.
    _SS_PY = os.path.join(_SS_ROOT, "python")

    # On Android the game tree lives INSIDE the APK (Ren'Py's asset store), not on
    # a real filesystem — `renpy.config.gamedir` is not a real path — so importing
    # ss_renpy straight off `sys.path` fails (ModuleNotFoundError). Extract the
    # pure-Python package tree (ss_renpy + the generated ss.* bindings + flatbuffers,
    # all under spritestudio/python/) via Ren'Py's archive-aware loader into the
    # app's writable private dir, and import from there instead. (The native Brain
    # is handled separately: it ships in the APK's lib/<abi>/ jniLibs and is loaded
    # by soname — see ss_renpy/ssruntime_native.load_library.)
    if getattr(renpy, "android", False):
        import shutil
        _rel_py = "spritestudio/python"          # loader paths use "/" on all OSes
        _dest = os.path.join(os.environ["ANDROID_PRIVATE"], "ss_extracted")
        _dest_py = os.path.join(_dest, "spritestudio", "python")
        # Re-extract from scratch each launch so a stale tree from a previous app
        # version (e.g. a since-removed module) can never shadow the new one; the
        # tree is small and this runs once at init.
        if os.path.isdir(_dest):
            shutil.rmtree(_dest, ignore_errors=True)
        for _dir, _fn in renpy.loader.listdirfiles():
            if _fn != _rel_py and not _fn.startswith(_rel_py + "/"):
                continue
            _out = os.path.join(_dest, *_fn.split("/"))
            _outdir = os.path.dirname(_out)
            if not os.path.isdir(_outdir):
                os.makedirs(_outdir)
            with renpy.loader.load(_fn) as _src, open(_out, "wb") as _w:
                _w.write(_src.read())
        _SS_PY = _dest_py

    if _SS_PY not in sys.path:
        sys.path.insert(0, _SS_PY)

    import ss_renpy
    from ss_renpy import ssruntime, framedata, events, instance, effectplan, resolver, mask
    from ss_renpy.effect import EffectRig
    from ss_renpy.instance import InstanceRig, collect_ordered
    from ss_renpy.ssab_meta import SsabMeta
    from ss_renpy.player import SSInternalPlayer
    from ss_renpy.resource import ResourceManager

    # iOS (incl. the Simulator) reports sys.platform == "darwin", so the
    # engine-independent runtime can't tell it apart from desktop macOS on its
    # own — it would try to dlopen the macOS .dylib and fail. Only the host knows
    # the real target: Ren'Py sets renpy.ios there. Flip the SS_IOS marker that
    # ssruntime_native._is_ios() already honors so it routes to the static
    # xcframework (loaded via CDLL(None)) instead of libs/macos/.
    if getattr(renpy, "ios", False):
        os.environ["SS_IOS"] = "1"

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

    # --- Tuning knobs (set before the first render) ------------------------
    # Rendering conventions vary a little by Ren'Py build / GPU. Each knob has a
    # known-good default; override it here (no code changes) if the result looks
    # wrong on your target.
    SS_ROTATE_SIGN = 1.0          # set -1.0 if rotation direction is reversed
    SS_MIRROR_AXIS = "y"          # "y" = mirror via negative yzoom, "x" = xzoom

    # Render backend:
    #   "mesh" (default) — model-based per-vertex mesh (renpy.gl2 Mesh2) + custom
    #       shader. The only backend that reproduces shear / free-deform and the
    #       baked UV transforms (UvScale / UvTranslation / UvRotation), by sampling
    #       the full atlas with gl_texture_wrap = REPEAT. Mirrors the reference
    #       renderers. On any error it falls back per-part to "transform", so it
    #       can never blank the screen.
    #   "transform" — blit + Transform. Robust, but drops shear / free-deform to a
    #       similarity fit and renders per-vertex colour gradients as a flat tint;
    #       it also cannot represent UV scale / rotation (it crops the cell rect),
    #       so packs like Basic.ssab (UvScale=2) render wrong.
    # "mesh" is the default for that reason; choose "transform" only if the mesh
    # backend misbehaves on your GPU / Ren'Py build.
    SS_RENDER_BACKEND = "mesh"

    SS_ENABLE_BLEND = True        # apply framebuffer blend via gl_blend_func
    SS_ENABLE_PARTCOLOR = True    # apply parts_color tint (transform backend)
    # Mask / clipping (SDK doc: 40_components/40_mask.md). Needs the mesh
    # backend + custom shaders + offscreen Render-to-texture; set False to draw
    # masked parts plainly (geometry stays correct, the mask is simply not
    # applied). The coverage bitmap is sized to the writers' world bbox × the
    # supersample factor, capped at this long edge (px). The mask edge is a hard
    # 1-bit test (no AA), so its sharpness is limited by the coverage resolution:
    # SUPERSAMPLE > 1 renders the coverage above the bbox's world-pixel size so a
    # scaled / high-DPI (Retina) display doesn't show blocky stair-steps along the
    # mask boundary. 2 suits a 2× Retina display; raise it if the player is
    # scaled up further.
    SS_ENABLE_MASK = True
    SS_MASK_COVERAGE_MAX_DIM = 2048
    SS_MASK_COVERAGE_SUPERSAMPLE = 2.0
    # Deprecated no-op retained for compatibility; mask-edge antialiasing is
    # controlled solely by SS_MASK_COVERAGE_SUPERSAMPLE.
    SS_MASK_ANTIALIAS = True

    # User-shader effects (SS6 ss-* family: sepia / outline / bmask / hsb / step /
    # move / wave / noise / blur / pix / scatter / circle / spot). Needs the mesh
    # backend + custom shaders; a part with an assigned shader draws per-part
    # through its ss.user_* variant (breaking the same-texture batch). Set False to
    # draw those parts plainly (geometry + PartColor stay correct, the effect is
    # simply not applied). The `overall/Shader.ssab` sample pack exercises all 13.
    # A part that is BOTH masked and shadered draws masked (the mask wins); the two
    # rarely combine. Ported from SSPlayerForGodot (ss_player/shaders/*.fs); the
    # engine-independent half is headless-verified by tools/verify_shader.py.
    SS_ENABLE_USER_SHADERS = True

    # Timeline events (UserData / Signal / Audio). The decoder is pure-Python and
    # headless-verified (tools/verify_events.py); collecting into the poll queue
    # is cheap and always on when enabled. Optional callbacks (see the
    # displayable constructor) run *inside* render() — keep them light; for
    # control flow (jumps, sound) prefer draining ss_poll_events() from a screen.
    SS_ENABLE_EVENTS = True

    # Play SS Audio timeline events through Ren'Py's audio system (SDK docs:
    # 40_components/90_audio.md + 10_introduction/20_limitations.md). When on,
    # the displayable resolves each Audio event to its sound
    # file (via the pack's SoundList), preloads the files at setup if the pack
    # carries any (lazy: nothing happens for packs with no audio), and plays each
    # trigger — forward playback only (reverse / ping-pong return legs and
    # negative speed are skipped; most decoders can't play audio backwards) and
    # honouring loop_num as a *play count*. The `on_audio` callback still fires as
    # a notification regardless. Requires SS_ENABLE_EVENTS (audio arrives as a
    # timeline event); set False to leave all playing to `on_audio`.
    SS_ENABLE_AUDIO = True
    # A Ren'Py channel plays ONE stream, so a single channel makes simultaneous SS
    # Audio events cut each other off. To play them in PARALLEL we register a pool
    # of channels (mixer "sfx") and hand each trigger an idle one (round-robin
    # when all are busy). Size the pool for the most sounds a pack fires at once;
    # the same sound repeated by loop_num still queues on one channel (sequential,
    # not parallel — it is one clip played N times). SSPlayer(audio_channel="…")
    # overrides the pool with a single fixed channel for that instance.
    SS_AUDIO_CHANNELS = 8
    # Mixer the pool channels use, so SS audio obeys the player's volume slider /
    # mute for that mixer (affinity with Ren'Py's channel system). "sfx" is a
    # built-in mixer; change to "music"/"voice"/a custom mixer to reclassify.
    SS_AUDIO_MIXER = "sfx"
    _SS_AUDIO_POOL = []      # registered channel names (filled at init, below)
    _SS_AUDIO_RR = [0]       # round-robin cursor (list = mutable across calls)

    def _ss_next_audio_channel():
        """Pick a pooled channel for one Audio trigger: an idle one if any, else
        round-robin the oldest — so simultaneous events play in parallel instead
        of stomping one channel. Falls back to the built-in "sound" channel when
        the pool is empty (audio left unregistered)."""
        pool = _SS_AUDIO_POOL
        if not pool:
            return "sound"
        n = len(pool)
        start = _SS_AUDIO_RR[0] % n
        for k in range(n):
            chan = pool[(start + k) % n]
            try:
                if renpy.music.get_playing(chan) is None:
                    _SS_AUDIO_RR[0] = (start + k + 1) % n
                    return chan
            except Exception:
                pass
        # All busy — steal the oldest (round-robin) so a new trigger still sounds.
        chan = pool[start]
        _SS_AUDIO_RR[0] = (start + 1) % n
        return chan

    # Channel playback is not bound to the displayable, and Ren'Py gives NO hide
    # hook when a player is swapped out of a screen (the Shift+B browser and the
    # feature viewer both `add`-a-displayable-held-in-a-variable, then swap the
    # variable — the old player is simply dropped, so `_hide` never fires and its
    # sound would play on). This off-screen reaper is the safety net: while a
    # player has live audio it keeps redrawing (see render()), so an on-screen
    # player's `_audio_last_render` stays fresh; one that stopped being rendered
    # goes stale and gets its audio stopped. Registered as a periodic callback
    # (~20Hz) below, so it covers every removal path, not just `hide`/`scene`.
    # The registry of players-with-sound is a STRONG set (a class attribute of
    # SSPlayer, see the class body) — a weak set would let a swapped-out player be
    # garbage-collected before the reaper could quiet it (the exact orphaned-audio
    # bug). A class attribute is not part of the saved store (pickled by class
    # reference), so it never bloats saves the way a `store` global would.
    SS_AUDIO_OFFSCREEN_STOP = 0.25   # seconds un-rendered before audio is cut

    def _ss_audio_reaper():
        """Periodic: stop / prune audio for tracked players (see above). Never raises."""
        live = getattr(SSPlayer, "_audio_live", None)
        if not live:
            return
        try:
            now = renpy.display.core.get_time()
        except Exception:
            return
        for p in list(live):
            try:
                used = p._audio_channels_used
                if not used:
                    live.discard(p)
                    continue
                # Off-screen (live audio but no recent render) -> stop it all.
                if now - getattr(p, "_audio_last_render", 0.0) > SS_AUDIO_OFFSCREEN_STOP:
                    p._stop_audio()
                    continue
                # On-screen: drop channels whose sound has ended so the player can
                # go idle again (get_playing is None once a clip finishes).
                still = set(c for c in used
                            if renpy.music.get_playing(c) is not None)
                p._audio_channels_used = still
                if not still:
                    live.discard(p)
            except Exception:
                pass

    # Register premultiplied gl_blend_func entries for the SS framebuffer
    # BlendTypes Ren'Py doesn't ship. Ren'Py's gl_blend_func gives the same raw
    # glBlendFuncSeparate/glBlendEquationSeparate access WebGL has, so we mirror
    # SSPlayerForWeb's applyBlend EXACTLY — Screen / Invert / Exclusion
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

    # id_hash (fnv1a of the SS shader name, e.g. fnv1a("ss-sepia")) -> registered
    # ss.user_* Ren'Py shader. Populated below once the variants register; stays
    # empty on an older Ren'Py without register_shader (draw code then skips the
    # user-shader path). Keyed by the Brain's own hash so it matches the draw
    # plan's PartAttributeShader.id_hash exactly (mirrors Godot's
    # ss_runtime_hash_string catalog).
    _SS_USER_SHADER_BY_HASH = {}
    # Which optional uniforms each variant actually references. Ren'Py's shader
    # cache PRUNES a declared-but-unused uniform from the compiled program, so we
    # bind u_texel / u_cell_rect only for the variants whose GLSL uses them (every
    # variant uses u_ss_param, so that is always bound). Populated with the map.
    _SS_USER_NEEDS_TEXEL = set()
    _SS_USER_NEEDS_CELL = set()

    # PartColor shader (SDK doc: 40_components/50_parts_color.md), used by the
    # "mesh" backend. The CPU reference is framedata.eval_partcolor — keep this
    # GLSL in step with it. Registered defensively: older Ren'Py without
    # register_shader just skips it (the mesh backend then falls back to the
    # transform backend).
    if hasattr(renpy, "register_shader"):
        try:
            renpy.register_shader(
                "ss.partcolor",
                variables="""
                    uniform sampler2D tex0;
                    attribute vec2 a_tex_coord;
                    varying vec2 v_tex_coord;
                    uniform vec4 u_ss_color;   // (r,g,b,a) 0..1, a = hierarchical alpha
                    uniform vec3 u_ss_varg;    // (1+c.x*rate, c.y*rate, c.z)
                """,
                vertex_300="v_tex_coord = a_tex_coord;",
                fragment_300="""
                    vec4 p = texture2D(tex0, v_tex_coord);
                    // Ren'Py GL2 textures are premultiplied-alpha (cf. the
                    // built-in renpy.alpha shader, which scales rgb AND a by
                    // opacity). Work in straight space for the PartColor formula,
                    // then re-premultiply so opacity actually dims the part.
                    vec3 s = p.a > 0.0 ? p.rgb / p.a : p.rgb;
                    // out_rgb = s*varg.x + mix(1, s, varg.z)*color*varg.y
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
        # (dynamic batching). Same fragment math as the
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

        # -- Mask / clipping (coverage-bitmap hybrid) ------------------------
        # Two shaders implement the spec's stencil over an offscreen coverage
        # (SDK doc: 40_components/40_mask.md):
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
                # inlined. SINGLE-TAP by design: a multi-tap AA grid would nest
                # with the 24-iteration replay loop (ES 1.00 / GLSL 120 must
                # unroll constant loops) — up to 96 unrolled iterations, each
                # with a texture sample, too large for reliable Metal/ANGLE
                # compilation. The mask edge is antialiased by
                # SS_MASK_COVERAGE_SUPERSAMPLE instead.
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
                            // bbox-outside == no writer covers it: a
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
                                bool is_active = clip ? (u_mask_rank > m.x)
                                                      : (u_mask_rank < m.x);
                                if (!is_active) continue;
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
                            if (masked != inside) discard;               // inside/outside rule
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

        # -- User-shader effects (SS6 ss-* family) ---------------------------
        # Ported from SSPlayerForGodot (ss_player/shaders/*.fs). Each variant is a
        # per-part shader over the same per-vertex mesh as ss.partcolor_batched
        # (a_tex_coord + a_ss_color + a_ss_varg), so gradients / Shape fills keep
        # their true per-vertex colour. Shared, DRY-composed GLSL: _SS_USER_FUNCS
        # holds the helpers, each fragment body inserts its effect between the
        # (un-premultiplied) input sample and the PartColor composite.
        #
        # Dialect adaptations vs the Godot originals (Ren'Py GL2 is GLSL ES 1.00 /
        # 120, premultiplied-alpha textures):
        #   * ss_input_texture(TEXTURE, uv) -> ss_texs(tex0, uv): sample + UN-
        #     premultiply to straight colour (the SS6 math — luminance / HSB /
        #     averaging — assumes straight rgb; Godot's canvas textures already are).
        #     Output re-premultiplies (ss_pc_out / inline).
        #   * TEXTURE_PIXEL_SIZE -> u_texel (= 1/atlas_size, set per draw).
        #   * PI -> SS_PI (no ES 1.00 built-in); ss_paramN -> u_ss_param.{x,y,z,w};
        #     ss_cell_rect -> u_cell_rect (circle / spot only).
        #   * ss-move's data-dependent loop bound -> constant 128 loop with an
        #     early `break` (ES 1.00 forbids non-constant loop bounds), matching
        #     the mask-replay idiom already used above.
        _SS_USER_VARS = """
            uniform sampler2D tex0;
            attribute vec2 a_tex_coord;
            attribute vec4 a_ss_color;
            attribute vec3 a_ss_varg;
            varying vec2 v_tex_coord;
            varying vec4 v_ss_color;
            varying vec3 v_ss_varg;
            uniform vec2 u_texel;      // 1/atlas_size (Godot TEXTURE_PIXEL_SIZE)
            uniform vec4 u_ss_param;   // (param0, param1, param2, param3)
        """
        _SS_USER_VARS_CELL = _SS_USER_VARS + \
            "            uniform vec4 u_cell_rect;  // cell UV bounds (lt.uv, rb.uv)\n"
        _SS_USER_VERT = """
            v_tex_coord = a_tex_coord;
            v_ss_color = a_ss_color;
            v_ss_varg = a_ss_varg;
        """
        _SS_USER_FUNCS = """
            const float SS_PI = 3.14159265358979;
            // Ren'Py GL2 textures are premultiplied; un-premultiply to straight so
            // the SS6 effect math matches the Godot originals (whose canvas
            // textures are straight). Alpha is unchanged by (un)premultiply.
            vec4 ss_texs(sampler2D t, vec2 uv) {
                vec4 p = texture2D(t, uv);
                return vec4(p.a > 0.0 ? p.rgb / p.a : p.rgb, p.a);
            }
            // PartColor composite (SDK doc: 40_components/50_parts_color.md),
            // straight-space.
            vec3 ss_pc_blend(vec3 rgb, vec3 color, vec3 varg) {
                return rgb * varg.x + mix(vec3(1.0), rgb, varg.z) * color * varg.y;
            }
            // Straight rgb+a -> PartColor-composited, re-premultiplied output.
            vec4 ss_pc_out(vec3 rgb, float a, vec4 color, vec3 varg) {
                vec3 o = ss_pc_blend(rgb, color.rgb, varg);
                float oa = a * color.a;
                return vec4(o * oa, oa);
            }
        """
        _SS_HSB_FUNCS = """
            vec4 ss_rgb_to_hsb(vec4 color) {
                vec4 K = vec4(0.0, -1.0/3.0, 2.0/3.0, -1.0);
                vec4 p = mix(vec4(color.bg, K.wz), vec4(color.gb, K.xy),
                             step(color.b, color.g));
                vec4 q = mix(vec4(p.xyw, color.r), vec4(color.r, p.yzx),
                             step(p.x, color.r));
                float d = q.x - min(q.w, q.y);
                float e = 1.0e-10;
                return vec4(abs(q.z + (q.w - q.y) / (6.0 * d + e)),
                            d / (q.x + e), q.x, color.a);
            }
            vec4 ss_hsb_to_rgb(vec4 hsb) {
                vec4 K = vec4(1.0, 2.0/3.0, 1.0/3.0, 3.0);
                vec3 p = abs(fract(hsb.xxx + K.xyz) * 6.0 - K.www);
                return vec4(hsb.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), hsb.y),
                            hsb.w);
            }
        """
        _SS_RND_FUNC = """
            float ss_rnd(vec2 p) {
                return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
            }
        """
        # name -> (needs_cell_rect, extra fragment_functions, fragment body).
        _SS_USER_FRAG = {
            "sepia": (False, "", """
                float fPower = u_ss_param.x;
                vec4 Pixel = ss_texs(tex0, v_tex_coord);
                float gray = dot(Pixel.rgb, vec3(0.298912, 0.586611, 0.114478));
                vec3 GrayRgb = vec3(gray);
                vec3 SepiaRgb = GrayRgb * vec3(1.07, 0.74, 0.43);
                vec3 toned = mix(SepiaRgb, GrayRgb, step(fPower, 0.0));
                vec3 mixed_rgb = mix(Pixel.rgb, toned, abs(fPower));
                gl_FragColor = ss_pc_out(mixed_rgb, Pixel.a, v_ss_color, v_ss_varg);
            """),
            "outline": (False, "", """
                float fThreshold = u_ss_param.x;
                float fRatio = abs(fThreshold);
                float e = 1.0e-5;
                vec2 px = u_texel;
                float lo = 0.0;
                lo += step(ss_texs(tex0, v_tex_coord + vec2(-px.x, 0.0)).a, fRatio);
                lo += step(ss_texs(tex0, v_tex_coord + vec2(px.x, 0.0)).a, fRatio);
                lo += step(ss_texs(tex0, v_tex_coord + vec2(0.0, -px.y)).a, fRatio);
                lo += step(ss_texs(tex0, v_tex_coord + vec2(0.0, px.y)).a, fRatio);
                vec4 ctr = ss_texs(tex0, v_tex_coord);
                float hi = step(fRatio + e, ctr.a);
                float v = min(hi * lo, 1.0);
                if (v <= 0.0) discard;
                gl_FragColor = ss_pc_out(vec3(v), v, v_ss_color, v_ss_varg);
            """),
            "bmask": (False, "", """
                float fBrightness = u_ss_param.x;
                vec4 Pixel = ss_texs(tex0, v_tex_coord);
                float b = abs(step(fBrightness, 0.0)
                              - max(Pixel.r, max(Pixel.g, Pixel.b)));
                if (b <= abs(fBrightness)) discard;
                gl_FragColor = ss_pc_out(Pixel.rgb, Pixel.a, v_ss_color, v_ss_varg);
            """),
            "hsb": (False, _SS_HSB_FUNCS, """
                float fHue = u_ss_param.x;
                float fSaturation = u_ss_param.y;
                float fBrightness = u_ss_param.z;
                vec4 Pixel = ss_texs(tex0, v_tex_coord);
                vec4 hsb = ss_rgb_to_hsb(Pixel);
                hsb.x += fHue;
                hsb.y = clamp(hsb.y + fSaturation, 0.0, 1.0);
                hsb.z = clamp(hsb.z + fBrightness, 0.0, 1.0);
                if (hsb.x < 0.0) hsb.x += 1.0;
                if (hsb.x > 1.0) hsb.x -= 1.0;
                vec4 shifted = ss_hsb_to_rgb(hsb);
                gl_FragColor = ss_pc_out(shifted.rgb, shifted.a, v_ss_color,
                                         v_ss_varg);
            """),
            "step": (False, "", """
                float fThreshold = u_ss_param.x;
                float fStage = u_ss_param.y;
                float fColor = u_ss_param.z;
                vec4 Pixel = ss_texs(tex0, v_tex_coord);
                float d = 1.0 + 255.0 * abs(fStage);
                float e = 1.0e-10;
                float t = abs(fThreshold);
                float b = abs(step(fThreshold, 0.0)
                              - max(Pixel.r, max(Pixel.g, Pixel.b)));
                float rr = clamp(floor((b - t) / (t + e) * 256.0 / d) * d / 256.0,
                                 0.0, 1.0);
                float c = step(t, b) * rr;
                vec3 vv = mix(vec3(c), Pixel.rgb * c, fColor);
                gl_FragColor = ss_pc_out(vv, Pixel.a, v_ss_color, v_ss_varg);
            """),
            "move": (False, "", """
                float fDistance = u_ss_param.x;
                float fDirection = u_ss_param.y;
                float fPower = u_ss_param.z;
                vec2 Coord = v_tex_coord;
                vec2 px = u_texel;
                int iCount = int(floor(abs(fDistance) * 96.0));
                if (iCount > 128) iCount = 128;
                vec2 Vel = vec2(sin(fDirection * SS_PI) * px.x,
                                cos(fDirection * SS_PI) * px.y) * sign(fDistance);
                Coord += Vel * float(iCount);
                Coord -= Vel;
                vec4 Pixel = ss_texs(tex0, Coord);
                for (int i = 1; i < 128; i++) {
                    if (i >= iCount) break;
                    Coord -= Vel;
                    Pixel = mix(ss_texs(tex0, Coord), Pixel, 0.96 * abs(fPower));
                }
                gl_FragColor = ss_pc_out(Pixel.rgb, Pixel.a, v_ss_color, v_ss_varg);
            """),
            "wave": (False, "", """
                float fWidth = u_ss_param.x;
                float fHeight = u_ss_param.y;
                float fPhase = u_ss_param.z;
                vec2 Coord = v_tex_coord;
                vec2 px = u_texel;
                float l = 384.0 * fHeight * 0.5;
                float s = l * sin(Coord.y * 384.0 * fWidth * 0.5
                                  + SS_PI * 2.0 * fPhase) * px.x;
                vec4 Pixel = ss_texs(tex0, vec2(Coord.x + s, Coord.y));
                gl_FragColor = ss_pc_out(Pixel.rgb, Pixel.a, v_ss_color, v_ss_varg);
            """),
            "noise": (False, _SS_RND_FUNC, """
                float fPower = u_ss_param.x;
                float fColor = u_ss_param.y;
                float fPhase = u_ss_param.z;
                vec2 Coord = v_tex_coord;
                vec2 px = u_texel;
                vec2 u = floor(Coord / px) * px;
                vec4 Pixel = ss_texs(tex0, Coord);
                vec2 t = u + vec2(fPhase);
                vec3 c;
                c.r = ss_rnd(t);
                c.g = mix(c.r, ss_rnd(t * c.r), fColor);
                c.b = mix(c.g, ss_rnd(t * c.g), fColor);
                Pixel.rgb = clamp(mix(Pixel.rgb, c.rgb, fPower), 0.0, 1.0);
                gl_FragColor = ss_pc_out(Pixel.rgb, Pixel.a, v_ss_color, v_ss_varg);
            """),
            # ss-blur intentionally SKIPS the PartColor composite (matches SS6):
            # the 9 taps are averaged then multiplied by the vertex colour.
            "blur": (False, "", """
                float fFocus = u_ss_param.x;
                vec2 px = u_texel;
                vec2 d = vec2(fFocus * px.x * 16.0, fFocus * px.y * 16.0);
                vec2 tc = v_tex_coord;
                vec4 sum = ss_texs(tex0, tc);
                sum += ss_texs(tex0, vec2(tc.x + d.x, tc.y + d.y));
                sum += ss_texs(tex0, vec2(tc.x + d.x, tc.y));
                sum += ss_texs(tex0, vec2(tc.x, tc.y + d.y));
                sum += ss_texs(tex0, vec2(tc.x - d.x, tc.y - d.y));
                sum += ss_texs(tex0, vec2(tc.x + d.x, tc.y - d.y));
                sum += ss_texs(tex0, vec2(tc.x - d.x, tc.y + d.y));
                sum += ss_texs(tex0, vec2(tc.x - d.x, tc.y));
                sum += ss_texs(tex0, vec2(tc.x, tc.y - d.y));
                vec4 Pixel = sum / 9.0;
                float oa = Pixel.a * v_ss_color.a;
                gl_FragColor = vec4(Pixel.rgb * v_ss_color.rgb * oa, oa);
            """),
            "pix": (False, "", """
                float fPower = u_ss_param.x;
                vec2 px = u_texel;
                float v = 1.0 + 96.0 * fPower;
                vec2 step_uv = vec2(v * px.x, v * px.y);
                vec2 Coord = floor(v_tex_coord / step_uv) * step_uv;
                vec4 Pixel = ss_texs(tex0, Coord);
                gl_FragColor = ss_pc_out(Pixel.rgb, Pixel.a, v_ss_color, v_ss_varg);
            """),
            "scatter": (False, _SS_RND_FUNC, """
                float fPower = u_ss_param.x;
                float fRatio = u_ss_param.y;
                float fPhase = u_ss_param.z;
                vec2 Coord = v_tex_coord;
                vec2 px = u_texel;
                vec2 u = floor(Coord / px) * px;
                vec2 t = u + vec2(fPhase);
                float r = ss_rnd(t) * SS_PI * 2.0 - SS_PI;
                float r2 = step(ss_rnd(t * r), fRatio);
                vec2 v = vec2(sin(r), cos(r)) * px * 96.0 * fPower * r2;
                vec4 Pixel = ss_texs(tex0, Coord + v);
                gl_FragColor = ss_pc_out(Pixel.rgb, Pixel.a, v_ss_color, v_ss_varg);
            """),
            "circle": (True, "", """
                float fPhase = u_ss_param.x;
                float fDirection = u_ss_param.y;
                float e = 1.0e-10;
                vec2 px = u_texel;
                vec2 uv1 = vec2(px.x + e, px.y + e);
                vec2 lt_uv = u_cell_rect.xy;
                vec2 rb_uv = u_cell_rect.zw;
                vec2 center_uv = (lt_uv + rb_uv) * 0.5;
                vec2 tx = v_tex_coord / uv1;
                vec2 cc = center_uv / uv1;
                vec2 lt = lt_uv / uv1;
                vec2 rb = rb_uv / uv1;
                vec2 dd = rb - lt;
                vec2 vv = tx - cc;
                float r = min(abs(rb.x - cc.x), abs(rb.y - cc.y)) + e;
                float dis = length(vv);
                if (dis > r) discard;
                vec2 nv = (dis > e) ? (vv / dis) : vec2(1.0, 0.0);
                float uu = 1.0 - dis / r;
                float ang = (atan(nv.y, nv.x) / SS_PI + 1.0) * 0.5 + fPhase;
                if (ang < 0.0) ang += 1.0;
                if (ang > 1.0) ang -= 1.0;
                if (fDirection <= 0.0) ang = 1.0 - ang;
                vec2 st = dd * vec2(uu, ang) * uv1;
                vec4 Pixel = ss_texs(tex0, lt_uv + st);
                gl_FragColor = ss_pc_out(Pixel.rgb, Pixel.a, v_ss_color, v_ss_varg);
            """),
            "spot": (True, "", """
                float fPower = u_ss_param.x;
                float fDecay = u_ss_param.y;
                float fColor = u_ss_param.z;
                float e = 1.0e-10;
                float p = abs(fPower);
                float d_abs = abs(fDecay);
                vec2 px = u_texel;
                vec2 uv1 = vec2(px.x + e, px.y + e);
                vec2 lt_uv = u_cell_rect.xy;
                vec2 rb_uv = u_cell_rect.zw;
                vec2 center_uv = (lt_uv + rb_uv) * 0.5;
                vec2 cc = center_uv / uv1;
                vec2 rb = rb_uv / uv1;
                float l = min(abs(rb.x - cc.x), abs(rb.y - cc.y)) + e;
                vec2 tt = v_tex_coord / uv1;
                vec2 vv = cc - tt;
                float fR = max(p / (length(vv / l) + e) - p, 0.0);
                float fL = max(p - length(vv / l), 0.0);
                fR = clamp(mix(fR, fL, d_abs), 0.0, 1.0);
                vec3 sampled = ss_texs(tex0, v_tex_coord).rgb;
                gl_FragColor = ss_pc_out(mix(vec3(1.0), sampled, fColor), fR,
                                         v_ss_color, v_ss_varg);
            """),
        }
        # SS shader id string -> our variant key (drives the hash map below).
        _SS_USER_NAME_MAP = [
            ("ss-sepia", "sepia"), ("ss-outline", "outline"),
            ("ss-bmask", "bmask"), ("ss-hsb", "hsb"), ("ss-step", "step"),
            ("ss-move", "move"), ("ss-wave", "wave"), ("ss-noise", "noise"),
            ("ss-blur", "blur"), ("ss-pix", "pix"), ("ss-scatter", "scatter"),
            ("ss-circle", "circle"), ("ss-spot", "spot"),
        ]
        try:
            for _nm, (_cell, _fns, _body) in _SS_USER_FRAG.items():
                _sh = "ss.user_" + _nm
                renpy.register_shader(
                    _sh,
                    variables=(_SS_USER_VARS_CELL if _cell else _SS_USER_VARS),
                    vertex_300=_SS_USER_VERT,
                    fragment_functions=_SS_USER_FUNCS + _fns,
                    fragment_300=_body,
                )
                if "u_texel" in _body:
                    _SS_USER_NEEDS_TEXEL.add(_sh)
                if "u_cell_rect" in _body:
                    _SS_USER_NEEDS_CELL.add(_sh)
            # Hash via the Brain's own fnv1a so the keys match the draw plan's
            # PartAttributeShader.id_hash byte-for-byte (mirrors Godot).
            _SS_USER_SHADER_BY_HASH = {
                ssruntime.hash_string(_ss): "ss.user_" + _key
                for _ss, _key in _SS_USER_NAME_MAP
            }
        except Exception as e:
            _SS_USER_SHADER_BY_HASH = {}
            _SS_USER_NEEDS_TEXEL = set()
            _SS_USER_NEEDS_CELL = set()
            renpy.log("ss: register_shader(ss.user_*) failed: %r; user-shader "
                      "effects disabled" % (e,))

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

    # Batch draw: pack per-vertex colour into custom Mesh2
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
        arity / convention (premultiply, row order, 5x4 vs 5x5) is version-
        dependent, so the whole construction is guarded — any mismatch returns
        None and the part renders untinted (geometry stays correct).
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

    def _ss_refresh_index_if_changed():
        """Cheap staleness check for the dev browser. If the set of .ssab under the
        asset roots no longer matches the cached index, drop the cache so the next
        _ss_get_index() rebuilds it. Uses the already-built renpy.list_files() (no
        disk scan) and only pays the metadata re-read when packs actually changed —
        so opening the browser is near-free when nothing was added. The auto
        importer refreshes list_files() (index_files) when it converts a new pack on
        reload, so a freshly imported pack is visible here without a full restart."""
        global _SS_INDEX
        if _SS_INDEX is None:
            return
        roots = [r.replace("\\", "/").strip("/")
                 for r in (getattr(store, "ss_asset_dirs", None) or ["ss_assets"])]
        current = set()
        for p in renpy.list_files():
            rp = p.replace("\\", "/")
            if rp.endswith(".ssab") and any(
                    rp == r or rp.startswith(r + "/") for r in roots):
                current.add(rp)
        if current != {r.rel_path for r in _SS_INDEX.records()}:
            _SS_INDEX = None

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
        feeds the displayable's incremental texture prewarm
        (``_prewarm_textures``) so atlases are GPU-resident before first use.
        The core never frees anything — Ren'Py owns lifetime.
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

    def _ss_pack_pc_mesh(parts, ox, oy, tw, th):
        """Pack a run of Normal / Shape parts into flat (geometry, attributes,
        indices) arrays for the ``_SS_PC_LAYOUT`` mesh (a_tex_coord + a_ss_color +
        a_ss_varg) — the per-vertex build shared by the batched, masked and
        user-shader mesh draws.

        Per vertex: world position offset to screen px by (ox, oy); UV normalized
        by the atlas size (tw, th); per-corner PartColor RGBA + the shader ``varg``
        triple. Triangles are rebased by the running vertex count, so ``parts`` may
        be a single part (masked / user-shader draw) or a whole same-texture run
        (batched draw). Returns ``(geometry, attributes, indices, nverts)``.
        """
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
                vx, vy, vz = framedata.partcolor_varg(mp.color_blend, mp.rates[idx])
                attributes += [u, v, c[0], c[1], c[2], c[3], vx, vy, vz]
            for (i, j, k) in mp.triangles:
                indices += [base + i, base + j, base + k]
            base += len(mp.positions)
        return geometry, attributes, indices, base

    class SSPlayer(renpy.Displayable):
        """Play one SpriteStudio .ssab pack. Place it in a screen or `show` it.

            add SSPlayer("ss_assets/overall/Basic.ssab") xalign 0.5 yalign 0.5

        One instance plays one .ssab; select an animation in it by name
        (constructor ``animation=`` or :meth:`ss_set_animation`). Renders Normal,
        Instance (nested child animations) and Effect (particle) parts, exposing
        a small ``ss_*`` playback / control / query API.
        """

        # Players with SS audio currently sounding, read by _ss_audio_reaper to
        # stop the sound of any that stopped being rendered (hidden / scene-changed
        # / swapped out of a screen). A STRONG set on purpose: a weak one would let
        # a swapped-out player be GC'd before it could be quieted. On the class (not
        # a store global) so it is never saved/rolled back with the game state.
        _audio_live = set()

        def __init__(self, ssab, animation=None, sprites_subdir=None,
                     loop=-1, speed=1.0, sub_frame=True, size=None,
                     attachments=None,
                     on_user_data=None, on_signal=None, on_audio=None,
                     on_finished=None, on_looped=None, on_started=None,
                     aliases=None, audio_channel=None, **kwargs):
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
            # `sprites_subdir`, when given, is an optional prefix kept for
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
            # head stays a raw float either way (SDK doc:
            # 30_core/20_playback_control.md). Defaults to on.
            self._sub_frame = bool(sub_frame)
            # Layout size. Given as (w, h) (or a single number for a square),
            # render() reports a box of that size and centers the animation
            # within it, so `xalign` / `xpos` / `pos` and container layout work
            # like a normal image. None (default) fills the whole offered area
            # (position with xoffset/yoffset).
            # `zoom` / Transform still scale the rendered result either way.
            if size is None:
                self._size = None
            elif isinstance(size, (int, float)):
                self._size = (int(size), int(size))
            else:
                self._size = (int(size[0]), int(size[1]))
            # Optional attachments: displayables pinned to a named part's live
            # transform every frame (e.g. an item in the hand, an effect over the
            # head, a second SS animation linked to a bone). Stored as a list of
            # plain records
            #   {"part": name, "child": displayable,
            #    "drive_scale": bool, "on_hide": "follow"|"hide"}
            # so several children can ride one part and the whole list pickles
            # with the displayable (child displayables are picklable). The
            # constructor also takes the ergonomic {part_name: child} dict;
            # ss_attach / ss_detach edit the list at runtime. render() does the
            # compositing (translation + rotation, scale when drive_scale).
            self._attachments = self._init_attachments(attachments)
            # Per-attachment Transform cache (rotated/scaled children only),
            # keyed by record index and rebuilt only when the part's angle/scale
            # actually changes — kept OFF the record so it never pickles. Any
            # attach/detach invalidates it (indices shift). See render().
            self._xform_cache = {}
            # Optional event callbacks (the recommended Player API; SDK doc:
            # 30_core/20_playback_control.md). Each is invoked as
            # cb(self, frame_index, event) for the per-part events
            # and cb(self) for started/finished/looped, guarded so a raising
            # callback can never break rendering. Prefer module-level functions /
            # store methods (lambdas/locals defeat rollback pickling).
            self.on_user_data = on_user_data
            self.on_signal = on_signal
            self.on_audio = on_audio
            self.on_finished = on_finished
            self.on_looped = on_looped
            self.on_started = on_started
            # How SS Audio events pick a Ren'Py channel (when SS_ENABLE_AUDIO):
            #   None      -> the shared parallel pool (ss_audio_*, sfx mixer):
            #                simultaneous sounds get distinct channels. Default.
            #   "name"    -> always this one channel (may cut itself off).
            #   callable  -> f(player, frame, audio) -> channel name, or None to
            #                fall back to the pool: route a game's own channels.
            # (A callable, like on_*, must be a module-level fn to pickle/rollback.)
            self._audio_channel = audio_channel
            # Setup-time audio preload runs once per built core (see _ensure /
            # _preload_audio); reset when the core is rebuilt (reshow / unpickle).
            self._audio_preloaded = False
            # Channels this instance has played SS audio on, so hide/stop can quiet
            # exactly this player's sound (channel playback outlives the displayable
            # otherwise — a hidden/scene-changed sprite would keep sounding).
            self._audio_channels_used = set()
            # Last render time while audio was live — the off-screen reaper reads
            # it to tell an on-screen player (kept redrawing) from a swapped-out one.
            self._audio_last_render = 0.0
            # The current frame + loop count to restore on rollback/reshow, plus
            # whether playback was live at that point ("playing" / "paused" /
            # "stopped"): restoring a paused, stopped or naturally finished
            # player must NOT silently resume it (see _ensure / _playback_state).
            self._saved_frame = -1.0
            self._saved_loop = self._initial_loop
            self._saved_state = "playing"
            # Delegation: the engine-independent playback core (built lazily on
            # first render) owns the runtime, metadata, rigs and timeline events.
            # This displayable is the Ren'Py adapter around it.
            self._core = None       # ss_renpy.player.SSInternalPlayer
            self._rm = None         # RenPyResourceManager (Ren'Py texture cache)
            self._texpath = {}      # texture_hash -> gamedir-rel image path (cache)
            self._last_st = None
            self._warned = set()
            self._mask_white = None  # cached white tex0 for textureless writers
            # Atlases still to force onto the GPU (see _prewarm_textures): None
            # until the first render snapshots them, then drained a few per frame.
            self._prewarm_pending = None
            # Per-part overrides this game has set: {(part_index, kind): args}.
            # The Brain owns the live table, but Ren'Py drops the native core on
            # pickling and rebuilds it lazily, so the overrides would vanish on
            # save/load without this record. Plain data (ints, strings, tuples),
            # so it pickles with the displayable. See _reapply_overrides.
            self._overrides = {}

        def __getstate__(self):
            """Drop the native-backed core + caches for pickling/saves; they are
            rebuilt lazily on the next render (re-applying the animation)."""
            state = self.__dict__.copy()
            state["_core"] = None
            state["_rm"] = None
            state["_texpath"] = {}
            state["_last_st"] = None
            state["_warned"] = set()
            state["_prewarm_pending"] = None   # GPU textures are gone too; re-warm
            state["_audio_preloaded"] = False  # core is rebuilt; preload re-runs
            state["_audio_channels_used"] = set()
            state["_xform_cache"] = {}         # pure render cache; rebuild lazily
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
            animation. (Otherwise SSCharacter lip-flap silently breaks: a
            character shown with no attribute, then switched to ``talk``, keeps
            replaying the idle template.)"""
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
                # The template's ORIGINAL loop — self.loop is mutated to 1 while
                # a sequence is queued, and copying that would make the copy's
                # final animation play once and freeze instead of honouring the
                # constructor's loop.
                loop=self._initial_loop,
                speed=self.speed,
                sub_frame=self._sub_frame,
                size=self._size,
                attachments=self._attach_list(),
                on_user_data=self.on_user_data,
                on_signal=self.on_signal,
                on_audio=self.on_audio,
                on_finished=self.on_finished,
                on_looped=self.on_looped,
                on_started=self.on_started,
                aliases=self.aliases,
                audio_channel=self._audio_channel,
                **self.kwargs
            )
            # Carry the overrides that survive an animation change. The copy
            # builds its own core, whose setup_animation drops visibility and
            # non-Permanent colour/cell overrides exactly as a creator-initiated
            # switch does — so the Permanent ones are precisely what must ride
            # along. Without this, an attribute switch (`show ringo talk`, or
            # SSCharacter's lip-flap) silently threw away a costume the game had
            # set Permanent, which docs/*/usage.md §5 promises persists.
            rv._overrides = self._permanent_overrides()
            rv._duplicatable = False
            return rv

        # -- lazy native setup ---------------------------------------------
        def _ensure(self):
            # A save written before per-part overrides existed restores a
            # __dict__ without `_overrides`, and every override path runs
            # through here first — so seed it before the early return.
            if not hasattr(self, "_overrides"):
                self._overrides = {}
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
            try:
                self._core = SSInternalPlayer(
                    data, lib=_SS_LIB, base_dir=self._base_dir,
                    resource_manager=self._rm,
                    pack_reader=_ss_renpy_pack_reader(self._base_dir),
                    sub_frame=self._sub_frame,
                    enable_events=SS_ENABLE_EVENTS,
                )
            except Exception as e:
                # Keep the message diagnosable: a corrupt/truncated pack would
                # otherwise surface as a bare struct.error from the FlatBuffers
                # walk with no hint of which file caused it.
                self._core = None
                raise Exception(
                    "ss: cannot load .ssab %r — the pack data is invalid "
                    "(re-export it from the .sspj). [%s]" % (self.ssab, e))

            # If restoring from a saved state (e.g. after rollback unpickled this
            # instance), restore the exact animation and frame.
            if getattr(self, "_saved_frame", -1.0) >= 0.0:
                core = self._core
                core.set_speed(self.speed)
                # Loop count: use the value the core actually last ran with
                # (snapshotted each frame in render()). This preserves a runtime
                # ss_set_loop / ss_play(loop=...) across rollback — mirroring how
                # speed is carried above — and already encodes the sequence rule
                # (1 for a mid-chain clip, the request for the final one).
                core.set_loop(getattr(self, "_saved_loop", self._initial_loop))
                anim = getattr(self, "animation", None)
                if not anim:
                    anim = self._initial_animation
                    if isinstance(anim, (list, tuple)) and anim:
                        anim = anim[0]
                if core.set_animation(anim):
                    # Restore the *state* too, not just the head. A save written
                    # before this existed has no _saved_state -> "playing",
                    # i.e. the previous behaviour.
                    state = getattr(self, "_saved_state", "playing")
                    if state == "stopped":
                        # Paused-forever: a stopped player, or a one-shot that
                        # had already finished. Deliberately NO play() — that
                        # would resume it, and for a finished one-shot it would
                        # also re-arm the completion edge so on_finished (and
                        # sequence advance) fired a second time for the same
                        # playthrough. set_animation left the head parked, so
                        # seeking alone poses the saved frame.
                        core.set_frame(self._saved_frame)
                    else:
                        # play() re-seeks to the section start, so seek to the
                        # saved frame AFTER starting playback. Seeking first and
                        # then play()ing would clobber the head back to frame 0
                        # (i.e. the animation would still reset on rollback), and
                        # update(0) on the first post-rollback render then poses
                        # this exact frame.
                        core.play()
                        core.set_frame(self._saved_frame)
                        if state == "paused":
                            core.pause()
                else:
                    # Saved animation is gone (e.g. the pack changed since the
                    # save) — fall back to a fresh start rather than leaving the
                    # core with no animation set (a silently blank sprite).
                    self._start_initial()
            else:
                self._start_initial()

            # Restore the per-part overrides the game had set before this core
            # was dropped (save/load, rollback, re-show). Runs AFTER
            # _start_initial / the saved-state restore: setup_animation clears the
            # Brain's override table, so applying them earlier would be undone by it.
            self._reapply_overrides()
            # Preload this pack's audio once, at setup, if it has any (lazy:
            # no-op for packs with no sound). Done here, before the first
            # update() fires any Audio event.
            self._preload_audio()

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
                # Play it ourselves (the Player, not the runtime, plays audio —
                # SDK doc: 40_components/90_audio.md) AND notify: on_audio stays
                # a notification hook so a game can react (subtitles, ...)
                # without owning playback.
                if SS_ENABLE_AUDIO:
                    self._play_audio(fe.frame_index, a)
                self._call_cb(self.on_audio, fe.frame_index, a)

        # -- audio (SDK doc: 40_components/90_audio.md) --------------------
        def _audio_full_path(self, file_ref):
            """Join an ssab-relative sound reference with this pack's base dir
            (like a texture path) and confirm Ren'Py can load it; "" if not."""
            if not file_ref:
                return ""
            path = (self._base_dir + "/" + file_ref) if self._base_dir else file_ref
            try:
                if not renpy.loadable(path):
                    return ""
            except Exception:
                pass
            return path

        def _preload_audio(self):
            """Warm this pack's sound files at setup, once (SDK doc:
            40_components/90_audio.md).

            Ren'Py streams + decodes audio on `play`; there is no public API to
            pre-decode a sound, so "preload" here means resolving each file and
            reading its bytes through the loader (archive-aware) so the archive
            index and OS page cache are warm — the first `renpy.sound.play` is a
            warm open, not a cold disk/archive lookup. Lazy: does nothing for a
            pack with no audio, or when SS_ENABLE_AUDIO is off. Idempotent per
            built core; never raises."""
            if self._audio_preloaded:
                return
            self._audio_preloaded = True
            if not SS_ENABLE_AUDIO or self._core is None:
                return
            try:
                if not self._core.meta.has_audio():
                    return
            except Exception:
                return
            seen = set()
            for sf in self._core.meta.sound_files():
                path = self._audio_full_path(sf.file_path)
                if not path or path in seen:
                    continue
                seen.add(path)
                try:
                    _ss_open_bytes(path)     # read via loader -> warms the cache
                except Exception as e:
                    self._warn_once(("audio-preload", path),
                                    "audio preload failed for %r (%r)" % (path, e))

        def _play_audio(self, frame, audio):
            """Play one SS Audio timeline event (SDK doc:
            40_components/90_audio.md). Never raises.

            Forward-only: skip when the effective direction is backward — the
            runtime's is_playing_forward (direction + ping-pong leg) XOR a
            negative speed (most decoders can't play audio in reverse; SDK doc:
            10_introduction/20_limitations.md).
            ``loop_num`` is a *play count* (SS has no infinite loop), realised by
            queueing the file that many times on the channel."""
            try:
                forward = self._core.is_playing_forward()
                if self.speed < 0:
                    forward = not forward
                if not forward:
                    return
                path = self._audio_full_path(audio.file_path)
                if not path:
                    # Unresolved: no matching SoundFile, or the file is missing
                    # from the deployed pack. Warn once so it is diagnosable.
                    self._warn_once(("audio-unresolved", audio.sound_name),
                                    "audio %r has no loadable file (base=%r, "
                                    "file=%r) — skipped" % (audio.sound_name,
                                    self._base_dir, audio.file_path))
                    return
                count = audio.loop_num if (audio.loop_num or 0) >= 1 else 1
                chan = self._resolve_audio_channel(frame, audio)
                renpy.sound.play([path] * count, channel=chan)
                # Remember it so _hide()/ss_stop_audio()/the reaper can quiet this
                # player, and register for the off-screen reaper (keeps its
                # last-render fresh while on screen).
                self._audio_channels_used.add(chan)
                try:
                    self._audio_last_render = renpy.display.core.get_time()
                except Exception:
                    pass
                SSPlayer._audio_live.add(self)
            except Exception as e:
                self._warn_once(("audio-play", getattr(audio, "sound_name", "")),
                                "audio playback failed (%r)" % (e,))

        def _stop_audio(self, fadeout=0.0):
            """Stop SS audio this player started (channels it has played on). Used
            on hide / scene change (via _hide) and by ss_stop_audio(). Because the
            channel pool is shared, this can in rare cases also cut a sound another
            SSPlayer round-robin'd onto the same channel; on a scene change every
            player is hidden so all pooled sound stops, which is the intent. Never
            raises."""
            for chan in list(self._audio_channels_used):
                try:
                    renpy.music.stop(channel=chan, fadeout=fadeout)
                except Exception:
                    pass
            self._audio_channels_used.clear()
            SSPlayer._audio_live.discard(self)

        def _resolve_audio_channel(self, frame, audio):
            """Resolve which Ren'Py channel this event plays on (see __init__):
            a callable routes per-event, a string is a fixed channel, and None (or
            a callable returning None) uses the shared parallel pool."""
            ch = self._audio_channel
            if callable(ch):
                try:
                    ch = ch(self, frame, audio)
                except Exception as e:
                    self._warn_once(("audio-route", id(self._audio_channel)),
                                    "audio_channel callable raised: %r" % (e,))
                    ch = None
            return ch or _ss_next_audio_channel()

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

            The queue behind it is bounded, so a caller that polls far less often
            than the animation emits loses the OLDEST events. That would be
            invisible — the returned list just quietly starts at the tail — so
            warn once here (the core counts the evictions; nothing else could
            tell a slow poller from a callback-only game, which drops nothing it
            wanted).
            """
            self._ensure()
            events = self._core.poll_events()
            if self._core.events_dropped:
                self._warn_once(
                    "event-overflow",
                    "the event queue overflowed (%d dropped): ss_poll_events() "
                    "is being drained slower than %s emits. Poll every "
                    "interaction, or use the on_user_data / on_signal callbacks."
                    % (self._core.events_dropped, self.ssab))
            return events

        # -- texture prewarm ------------------------------------------------
        def _prewarm_textures(self, width, height, st, at, budget=2):
            """Force this pack's atlases onto the GPU up front, a few per frame.

            Ren'Py uploads a cell atlas to the GPU only when its ``Image`` is
            first *drawn* (``im.cache.get(texture=True)`` -> a synchronous
            ``ready_one_texture`` drain). ``visit()`` prediction merely decodes
            the CPU surface — it does NOT drain that GPU-upload queue — and while
            we animate we ``renpy.redraw`` every frame, so the interaction never
            idles for Ren'Py to drain it in the background. The upshot: a large
            atlas a long animation doesn't reference until deep into its timeline
            (e.g. a multi-megabyte atlas first referenced a hundred frames into
            a cinematic) uploads mid-playback and stalls that one frame — the
            classic first-play-only hitch that never recurs
            (the texture stays GPU-resident across loops). The Godot / Web ports
            never show it because they upload every cellmap at load; we do the
            same here, spread over the first frames so neither the show frame nor
            a mid-anim frame carries the whole cost. Idempotent; never raises."""
            if self._prewarm_pending is None:
                self._prewarm_pending = list(self._rm.images()) if self._rm else []
            n = 0
            while self._prewarm_pending and n < budget:
                img = self._prewarm_pending.pop()
                try:
                    # A throwaway render drives the full upload path (decode +
                    # ready_one_texture); the atlas then lives in Ren'Py's texture
                    # cache, so the real draw — this frame or much later — is free.
                    renpy.render(img, width, height, st, at)
                except Exception:
                    pass
                n += 1
            if self._prewarm_pending:
                # Keep draining even if playback goes idle before we finish.
                renpy.redraw(self, 0)

        # -- sequence chaining (host playback policy) ----------------------
        def _advance_to_next_in_sequence(self, core):
            """Pop the queue to the next playable clip and start it; True if one
            started, False when the sequence is spent.

            Skips (with a one-time warning) any queued name the pack lacks —
            otherwise a typo'd entry would silently replay the previous clip with
            no diagnostics. Loop count is 1 for a mid-sequence clip and the
            original request for the final one."""
            while self._anim_queue:
                cand = self._anim_queue.pop(0)
                core.set_loop(1 if self._anim_queue else self._initial_loop)
                if core.set_animation(cand):
                    core.play()
                    # As in ss_set_animation: the Brain dropped visibility +
                    # non-Permanent overrides, so drop them from the record too.
                    self._prune_overrides_for_new_animation()
                    return True
                self._warn_once(("chain", cand),
                                "sequence animation %r not found; skipped"
                                % (cand,))
            return False

        # -- rollback state snapshot ---------------------------------------
        def _playback_state(self, core):
            """``"playing"`` / ``"paused"`` / ``"stopped"`` for the rollback record.

            Ren'Py pickles this displayable without the native core and rebuilds
            it lazily, so whether playback was *live* has to be carried as plain
            data alongside the frame — otherwise every restore resumes. A
            naturally finished one-shot reads as "stopped": the Brain parks it on
            the final frame with is_playing false (SDK doc:
            30_core/20_playback_control.md), and restoring it as playing would
            re-fire the completion edge. Never raises — an unreadable state
            degrades to the previous behaviour ("playing")."""
            try:
                if core.is_pausing():
                    return "paused"
                if core.is_finished() or not core.is_playing():
                    return "stopped"
            except Exception:
                pass
            return "playing"

        # -- per-frame render ----------------------------------------------
        def render(self, width, height, st, at):
            self._ensure()

            # Detect re-show (time went backwards) -> restart from the top
            # (resets the animation sequence too).
            core = self._core
            if self._last_st is not None and st < self._last_st:
                self._saved_frame = -1.0
                self._start_initial(start_frame=0)
                # A re-show restarts the animation, and that setup_animation
                # dropped the Brain's visibility + non-Permanent overrides —
                # mirror it. (The _ensure() rebuild path also goes through
                # _start_initial but must NOT prune: it is restoring, not
                # switching, which is why this lives here and not in there.)
                self._prune_overrides_for_new_animation()
                self._call_cb(self.on_started)

            # Pre-upload atlases so a large one first drawn deep in a long
            # timeline doesn't stall that frame (first-play hitch). See above.
            if self._prewarm_pending is None or self._prewarm_pending:
                self._prewarm_textures(width, height, st, at)

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
            # Sequence chaining is the host's playback policy: on the core's
            # completion edge (FramePlan.finished = the is_finished rising edge),
            # advance to the next queued clip (e.g. an alias like ["attack1",
            # "wait1"]) or fire on_finished once the sequence is spent. The switch
            # happens HERE, between updates — so every frame's draw plan stays
            # consistent with a single animation (no mid-update frame skew).
            if plan.finished:
                if self._advance_to_next_in_sequence(core):
                    self.animation = core.animation
                    self._call_cb(self.on_started)
                    renpy.redraw(self, 0)
                else:
                    self._call_cb(self.on_finished)

            # Rollback / save snapshot, taken AFTER the chaining block: on a
            # chain-advance frame the head has just moved to the NEW clip's
            # section start, and snapshotting before would pair the new
            # animation with the OLD clip's last frame — an out-of-range seek
            # whenever the next clip is shorter. Read from the core rather than
            # `plan` so a degraded (exception) frame still records the true head.
            self._saved_frame = core.frame_no
            self._saved_loop = core.loop
            self._saved_state = self._playback_state(core)

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
                # targets that sample it (SDK doc: 40_components/40_mask.md).
                # Failure leaves the dict empty so masked parts simply draw
                # unmasked.
                cov_by_id = {}
                if SS_ENABLE_MASK:
                    self._build_coverages(cov_by_id, plan.items, ox, oy, st, at,
                                          rw, rh)
                self._draw_items(r, plan.items, ox, oy, st, at, rw, rh, cov_by_id)
                if SS_PROFILE:
                    _draw = time.perf_counter() - _td

            # Attachments: draw each pinned child at its part's live transform.
            # v1 composites translation + rotation, and scale when drive_scale;
            # the child is always drawn in FRONT of the sprite (no z insertion
            # between parts yet). The child's `anchor` point is pinned to the
            # part and is the rotation/scale pivot. Guarded so a bad child can
            # never break the frame. Children are few, so a Transform wrap only
            # happens when the part is actually rotated/scaled — the common
            # translation-only case stays allocation-free. See ss_attach.
            _recs = self._attach_list()
            if _recs:
                for _i, _rec in enumerate(_recs):
                    try:
                        _pname = _rec["part"]
                        _t = core.part_transform(_pname)
                        if _t is None:
                            continue
                        if _rec["on_hide"] == "hide" and \
                                core.is_part_hidden(_pname):
                            continue
                        _child = _rec["child"]
                        # Part rotation plus the child's fixed rest offset; both
                        # the Transform wrap and the anchor math below use this
                        # total, so the anchor rides the offset child too.
                        _ang = _t["rotation"] + _rec["angle"]
                        _sx, _sy = (_t["xscale"], _t["yscale"]) \
                            if _rec["drive_scale"] else (1.0, 1.0)
                        _ax, _ay = _rec["anchor"]
                        _tx, _ty = ox + _t["x"], oy + _t["y"]
                        if abs(_ang) < 1e-3 and abs(_sx - 1.0) < 1e-3 \
                                and abs(_sy - 1.0) < 1e-3:
                            # Pure translation: pin the anchor point directly.
                            _cr = renpy.render(_child, rw, rh, st, at)
                            _cw, _ch = _cr.get_size()
                            r.blit(_cr, (int(_tx - _ax * _cw),
                                         int(_ty - _ay * _ch)))
                        else:
                            # Rotate/scale about the child centre (Transform's
                            # default), then offset so the ANCHOR lands on the
                            # part. part_transform's scale is |magnitude| (a
                            # mirrored part reads positive), so a negative-scale
                            # flip is a v2/matrix concern.
                            #
                            # The child's UNROTATED size drives the anchor
                            # vector, so it is read live (an animated child may
                            # resize); Ren'Py caches renders per
                            # (displayable, w, h, st, at), and the Transform
                            # renders the same child at the same st, so this is
                            # a cache hit rather than a second real render.
                            _c0 = renpy.render(_child, rw, rh, st, at)
                            _cw, _ch = _c0.get_size()
                            # Hot path: reuse the Transform while the part's
                            # angle/scale hold steady (a fixed rest angle, an
                            # idle pose), so the common case allocates nothing
                            # per frame. A continuously rotating part genuinely
                            # needs new parameters, and rebuilding beats
                            # mutating a live displayable Ren'Py may have cached.
                            _key = (_ang, _sx, _sy)
                            _xf = self._xform_cache.get(_i)
                            if _xf is None or _xf[0] != _key:
                                _xf = (_key, Transform(_child, rotate=_ang,
                                                       xzoom=_sx, yzoom=_sy))
                                self._xform_cache[_i] = _xf
                            _cr = renpy.render(_xf[1], rw, rh, st, at)
                            _rw2, _rh2 = _cr.get_size()
                            # Vector centre->anchor, transformed the SAME way
                            # Transform did (rotate clockwise-positive, y-down),
                            # so the anchor rides the rotated bar. Coupled to
                            # _ang: flip the rotate sign and the anchor follows.
                            _th = math.radians(_ang)
                            _cos, _sin = math.cos(_th), math.sin(_th)
                            _vx = (_ax - 0.5) * _cw
                            _vy = (_ay - 0.5) * _ch
                            _px = _sx * _vx * _cos - _sy * _vy * _sin
                            _py = _sx * _vx * _sin + _sy * _vy * _cos
                            r.blit(_cr, (int(_tx - _rw2 / 2.0 - _px),
                                         int(_ty - _rh2 / 2.0 - _py)))
                    except Exception:
                        pass

            # While this player has sound playing, mark it rendered *now* and keep
            # redrawing even if the animation itself is idle: the off-screen reaper
            # reads _audio_last_render to tell a still-shown player (which keeps
            # refreshing this) from one swapped out of a screen (which stops
            # rendering and gets its audio cut). The reaper prunes finished
            # channels, so this lapses once the sound ends and the sprite idles.
            if self._audio_channels_used:
                self._audio_last_render = renpy.display.core.get_time()
            # Keep requesting redraws only while something is actually moving; an
            # idle sprite (paused / stopped / play-once finished, no live rigs)
            # renders an identical frame, so we let it go quiescent until a
            # control method (ss_play/ss_resume/ss_set_frame/ss_stop/...) re-arms
            # it. is_animating() stays True while effects / instances run.
            if core.is_animating():
                renpy.redraw(self, 0)
            elif self._audio_channels_used:
                # Animation is idle but a sound is still playing: keep the
                # displayable barely alive so the off-screen reaper can still see
                # it is shown — but SLOWLY. A full-rate redraw here would rebuild an
                # unchanged frame ~60x/s for the whole clip (e.g. a multi-second
                # SE over a finished pose); ~10fps is well inside the reaper's
                # SS_AUDIO_OFFSCREEN_STOP (0.25s) window and ~6x cheaper.
                renpy.redraw(self, 0.1)
            if SS_PROFILE:
                _ss_prof_tick(_geom, _draw, time.perf_counter() - _t0, bool(plan.items))
            return r

        # -- draw dispatch (batched) ---------------------------------------
        def _draw_items(self, r, items, ox, oy, st, at, width, height,
                        cov_by_id=None):
            """Draw the z-ordered renderables, batching consecutive same-texture
            Normal parts into one mesh/blit (and each effect batch likewise).

            A run breaks when the texture or framebuffer blend changes, an effect
            batch interrupts it, or a masked / user-shadered part is reached —
            preserving draw order. A masked part (``MeshPart.mask`` set, with a
            coverage in ``cov_by_id``) draws per-part through ``ss.partcolor_mask``;
            a part with a recognized ``shader_id_hash`` draws per-part through its
            ``ss.user_*`` variant. Both break the batch. Falls back to per-part /
            unmasked / plain drawing on any failure."""
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
                        # (the replay shader can't share a batched mesh). If the
                        # part ALSO carries a user shader, the mask wins (the two
                        # rarely combine and there's no merged replay+effect pass).
                        if (SS_ENABLE_USER_SHADERS and payload.shader_id_hash
                                in _SS_USER_SHADER_BY_HASH):
                            self._warn_once(("mask+shader", payload.shader_id_hash),
                                            "part %d is both masked and shadered; "
                                            "mask applied, user shader skipped"
                                            % payload.part_index)
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
                    # User-shader effect (SS6 ss-*): per-part through its variant,
                    # can't share a batched mesh either.
                    ush = (_SS_USER_SHADER_BY_HASH.get(payload.shader_id_hash)
                           if SS_ENABLE_USER_SHADERS and use_mesh else None)
                    if ush is not None:
                        if run:
                            self._flush_mesh_run(r, run, ox, oy, st, at, width,
                                                 height, can_batch, use_mesh)
                            run = []
                            run_key = None
                        if not self._draw_mesh_user_shader(r, payload, ush, ox, oy,
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
            reference players do. ``parts_color`` is applied per-part
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

        # -- mask / clipping: coverage + replay -----------------------------
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
            under *additive* blend so disjoint bits OR together (SDK doc:
            40_components/40_mask.md).
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

                geometry, attributes, indices, nverts = _ss_pack_pc_mesh(
                    [mp], ox, oy, tw, th)
                mesh = _SS_Mesh2(_SS_PC_LAYOUT, nverts, len(indices) // 3)
                mesh.set_geometry_data(geometry)
                mesh.set_attribute_data(attributes)
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

        def _draw_mesh_user_shader(self, r, mp, shader, ox, oy, st, at,
                                   width, height):
            """Draw one part through a user-shader variant (SS6 ss-* family).

            Same per-vertex mesh as :meth:`_draw_mesh_masked` (a_tex_coord +
            a_ss_color + a_ss_varg, so gradients / Shape fills keep their true
            colour), but binds ``shader`` (e.g. ``ss.user_sepia``) with the effect
            uniforms instead of the coverage replay: ``u_texel`` (= 1/atlas px,
            Godot's TEXTURE_PIXEL_SIZE), ``u_ss_param`` (param0..3), and — for the
            cell-rect shaders (circle / spot) — ``u_cell_rect`` (the part's atlas
            cell in UV, from ``src_rect``). Returns True on success; False makes
            the caller draw the part plainly (effect skipped, never blanks)."""
            if _SS_Mesh2 is None or _SS_PC_LAYOUT is None:
                return False
            try:
                cr = self._tex0_render(mp.texture_hash, st, at, width, height)
                if cr is None:
                    return False
                tw, th = cr.get_size()
                if tw <= 0 or th <= 0:
                    return False

                geometry, attributes, indices, nverts = _ss_pack_pc_mesh(
                    [mp], ox, oy, tw, th)
                mesh = _SS_Mesh2(_SS_PC_LAYOUT, nverts, len(indices) // 3)
                mesh.set_geometry_data(geometry)
                mesh.set_attribute_data(attributes)
                mesh.set_triangle_data(indices)

                rv = renpy.Render(width, height)
                rv.blit(cr, (0, 0))                  # tex0 atlas / white
                if _SS_TEXTURE_WRAP is not None:
                    rv.add_property("texture_wrap_tex0", _SS_TEXTURE_WRAP)
                rv.mesh = mesh
                rv.add_shader(shader)
                # u_ss_param (every variant uses it): (param0..param3).
                params = mp.shader_params
                rv.add_uniform("u_ss_param", (
                    params[0] if len(params) > 0 else 0.0,
                    params[1] if len(params) > 1 else 0.0,
                    params[2] if len(params) > 2 else 0.0,
                    params[3] if len(params) > 3 else 0.0))
                # Bind the optional uniforms only for variants that use them (an
                # unused one is pruned from the compiled program — see
                # _SS_USER_NEEDS_*). u_texel = 1/atlas px (Godot TEXTURE_PIXEL_SIZE);
                # neighbour-sampling variants step by it in UV space.
                if shader in _SS_USER_NEEDS_TEXEL:
                    rv.add_uniform("u_texel", (1.0 / tw, 1.0 / th))
                # u_cell_rect = the part's atlas cell in UV (circle / spot).
                # src_rect is (left, top, w, h) atlas px.
                if shader in _SS_USER_NEEDS_CELL:
                    l, t, w, h = mp.src_rect
                    rv.add_uniform("u_cell_rect", (
                        l / tw, t / th, (l + w) / tw, (t + h) / th))
                self._apply_blend(rv, mp)
                r.blit(rv, (0, 0))
                return True
            except Exception as e:
                self._warn_once(("user-shader", shader),
                                "user shader %s failed (%r); drawing plainly"
                                % (shader, e))
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
                geometry, attributes, indices, nverts = _ss_pack_pc_mesh(
                    parts, ox, oy, tw, th)
                mesh = _SS_Mesh2(_SS_PC_LAYOUT, nverts, len(indices) // 3)
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
            # Our own ATLASES are deliberately absent: predicting every atlas up
            # front stalls mid-animation when the background decode finishes and
            # the main thread uploads massive PNGs. They are prewarmed a few per
            # frame by _prewarm_textures() instead.
            #
            # Attachment children ARE reported. They are ordinary displayables
            # the game handed us, not pack textures, so they take the normal
            # Ren'Py path: without this the predictor never loads them and the
            # first frame one is drawn stalls on decode+upload — the very hitch
            # _prewarm_textures exists to avoid — and Ren'Py could not manage
            # their lifecycle either.
            return [_r["child"] for _r in self._attach_list()]

        # -- hide / destroy: stop this player's audio -----------------------
        def _handles_event(self, event):
            # Opt into the hide/replace notification. With config.fast_unhandled_event
            # (default True) Ren'Py skips _hide() for a displayable that does not
            # claim the event, so without this our _hide would never run and the
            # sprite's audio would outlive it on a `scene` / `hide` / re-show.
            return event in ("hide", "replaced", "replace")

        def _hide(self, st, at, kind):
            # Fired when this displayable is hidden (`hide`/`scene`), replaced by a
            # re-show of the same tag, or its screen hides. Channel playback is not
            # tied to the displayable, so stop the sound we started, then report
            # ready-to-remove (None = no lingering hide animation). Only meaningful
            # when we own playback (SS_ENABLE_AUDIO); harmless otherwise.
            self._stop_audio()
            return None

        # -- playback / control / query API --------------------------------
        # A small ss_-prefixed, Ren'Py-idiomatic surface that delegates to the
        # engine-independent core. set_animation/play are split (SDK doc:
        # 30_core/20_playback_control.md): set_animation loads+poses; ss_play
        # starts.
        def ss_set_animation(self, name):
            """Load + pose animation ``name`` (does NOT start playback).

            Front-loads the heavy work — native setup, texture acquisition, and
            Instance child-context allocation — so a later :meth:`ss_play` starts
            instantly (the setAnimation/play split).
            """
            if self._core is None:
                # First build: _ensure() arms the constructor's animation via
                # _start_initial(); fall through so `name` is applied on top
                # (the pack's atlases are shared, so the extra set_animation
                # costs no meaningful texture work).
                self._ensure()
            if not name or name == self._core.animation:
                return True
            if not self._core.set_animation(name):
                self._warn_once(("anim", name),
                                "setup_animation(%r) failed" % name)
                return False
            # An explicit switch overrides any pending sequence: drop the queue
            # and restore the constructor loop, or a leftover chain (e.g. from a
            # sequence constructor whose first clip _ensure just armed) would
            # resume after `name` finishes, and its intermediate loop=1 would
            # cap `name` at a single play.
            self._anim_queue = []
            self.loop = self._initial_loop
            self._core.set_loop(self._initial_loop)
            # setup_animation dropped the Brain's visibility + non-Permanent
            # overrides; keep our restore record in step with it.
            self._prune_overrides_for_new_animation()
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
            # Stopping the player also silences the audio it triggered (the sound
            # is on independent channels, so it would otherwise keep playing).
            self._stop_audio()

        def ss_stop_audio(self, fadeout=0.0):
            """Stop SS audio this player is currently sounding (SDK doc:
            40_components/90_audio.md). Called automatically on hide / scene
            change and ss_stop(); call it directly to cut the sound early or
            with a `fadeout` (seconds)."""
            self._stop_audio(fadeout=fadeout)

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

        # -- part attachments ----------------------------------------------
        # Pin a displayable to a part's live transform: every frame it is drawn
        # at that part's position (and rotation; scale too when drive_scale),
        # so an item follows the hand, an effect rides the head, a second SS
        # animation links to a bone. The child is ANY Ren'Py displayable — an
        # image name, "file.png", a Transform(...), even another SSPlayer — so
        # the whole Ren'Py composition stack rides along. This is the Ren'Py
        # form of the Godot/Unity "part tracking": there is no scene tree to
        # push to, so the child is composited INTO this player's render at the
        # part, which matches those ports' "child of the player" case (the
        # accurate one). Children draw in front of the sprite (v1: no z
        # insertion between parts). Several may ride one part.
        #
        #     $ ringo.ss_attach("hand_R", "sword.png")
        #     $ ringo.ss_attach("head", Transform("aura", zoom=1.2), on_hide="hide")
        #     $ ringo.ss_attach("hand_R", "sword.png", anchor=(0.5, 1.0))  # grip
        #     $ ringo.ss_detach(part="hand_R")
        #
        # anchor=(ax, ay) is the child point (as a 0..1 fraction of its size)
        # pinned to the part and used as the rotation/scale pivot: (0.5, 0.5)
        # centres it (default), (0.5, 1.0) puts the child's BOTTOM edge on the
        # part (a held item's grip), (0.5, 0.0) the top edge.
        #
        # Overrides live on the Brain; attachments are pure host policy (like
        # sequence chaining), so they are plain data that pickles straight into
        # the save — no _reapply step needed.
        def _init_attachments(self, attachments):
            """Normalise the constructor's ``attachments`` into the record list.

            Accepts the ergonomic ``{part_name: child}`` dict or a list of
            records (what _duplicate passes back). Child references go through
            ``renpy.displayable`` so an image name / "file.png" / a displayable
            all work. Returns a fresh list (never aliased to the source)."""
            out = []
            if not attachments:
                return out
            src = attachments.items() if isinstance(attachments, dict) \
                else [(r["part"], r) for r in attachments]
            for part, val in src:
                if isinstance(val, dict):          # a record (from _duplicate)
                    out.append({"part": val["part"],
                                "child": renpy.displayable(val["child"]),
                                "drive_scale": bool(val.get("drive_scale", False)),
                                "on_hide": val.get("on_hide", "follow"),
                                "anchor": val.get("anchor", (0.5, 0.5)),
                                "angle": val.get("angle", 0.0)})
                else:                              # {part_name: child}
                    out.append({"part": part,
                                "child": renpy.displayable(val),
                                "drive_scale": False, "on_hide": "follow",
                                "anchor": (0.5, 0.5), "angle": 0.0})
            return out

        def _attach_list(self):
            """The attachment records — the single accessor every path uses.

            Migrates state unpickled from a save written before attachments
            became a record list: back then the attribute did not exist at all,
            or held ``None`` / the ``{part: child}`` dict. Without this, a loaded
            save would hit ``None.append`` in ss_attach, ``len(None)`` in
            ss_clear_attachments, and a dict walk in render() that yields part
            NAMES where records are expected (silently dropping every child).
            Also seeds the non-pickled Transform cache render() reads."""
            recs = getattr(self, "_attachments", None)
            if not isinstance(recs, list):
                recs = self._init_attachments(recs)
                self._attachments = recs
                self._xform_cache = {}
            elif not hasattr(self, "_xform_cache"):
                self._xform_cache = {}
            return recs

        def _invalidate_attachments(self):
            """Drop the Transform cache: it is keyed by record index, so any
            attach/detach shifts it. Cheap — it refills on the next render."""
            self._xform_cache = {}
            renpy.redraw(self, 0)

        def ss_attach(self, part, child, drive_scale=False, on_hide="follow",
                      anchor=(0.5, 0.5), angle=0.0):
            """Pin ``child`` to ``part``; returns the normalised child.

            ``part`` is a part name (need not exist yet — a child rides it once
            the part appears). ``child`` is any displayable (image name,
            "file.png", Transform(...), another SSPlayer). ``drive_scale`` also
            matches the part's scale (position + rotation always apply).
            ``on_hide``: "follow" keeps drawing while the part is hidden, "hide"
            drops the child that frame. ``anchor=(ax, ay)`` is the child point
            (0..1 fraction of its size) pinned to the part and used as the
            rotation/scale pivot; default centres it, (0.5, 1.0) pins the bottom
            edge (a grip). ``angle`` is a fixed rotation offset (degrees,
            clockwise-positive) added on top of the part's rotation, to align
            the child's rest orientation with the part's local axis (e.g. a
            hand part carries the wrist angle, so a held item usually needs an
            offset to lie along the fingers; -90 rotates it CCW)."""
            child = renpy.displayable(child)
            anchor = (float(anchor[0]), float(anchor[1]))
            self._attach_list().append({"part": part, "child": child,
                                        "drive_scale": bool(drive_scale),
                                        "on_hide": on_hide, "anchor": anchor,
                                        "angle": float(angle)})
            self._invalidate_attachments()
            return child

        def ss_detach(self, child=None, part=None):
            """Remove attachments matching ``child`` and/or ``part``; returns the
            count removed. Pass the child ss_attach returned (or the same
            displayable). With neither given, removes nothing — use
            ss_clear_attachments to drop them all."""
            if child is None and part is None:
                return 0
            if child is not None:
                child = renpy.displayable(child)
            keep, removed = [], 0
            for rec in self._attach_list():
                match_child = child is None or rec["child"] is child \
                    or rec["child"] == child
                match_part = part is None or rec["part"] == part
                if match_child and match_part:
                    removed += 1
                else:
                    keep.append(rec)
            self._attachments = keep
            if removed:
                self._invalidate_attachments()
            return removed

        def ss_clear_attachments(self):
            """Remove every attachment; returns the count removed."""
            n = len(self._attach_list())
            self._attachments = []
            if n:
                self._invalidate_attachments()
            return n

        def ss_attachments(self):
            """Current attachments as a list of ``(part_name, child)`` tuples."""
            return [(r["part"], r["child"]) for r in self._attach_list()]

        # -- part overrides ------------------------------------------------
        # Per-part runtime overrides: "make this part this colour / cell /
        # hidden NOW". The Brain applies them on the resolved pose, so an
        # override wins over both the keyframe and any blend (SDK doc:
        # 40_components/65_override_layer.md).
        #
        #     $ ringo.ss_set_part_color_override("apple", "#f00", blend_op=1)
        #     $ ringo.ss_set_part_visibility_override("apple", True, cascade=True)
        #     $ ringo.ss_clear_all_part_overrides()
        #
        # `part` is a part NAME or its index (ss_part_index). Colours take any
        # Ren'Py colour form ("#f00", (255, 0, 0), Color(...)); they are read in
        # the same 8-bit sRGB space as the authored PartColor and the Brain
        # pre-multiplies alpha, so pass the colour as authored. Each method
        # returns False when the part is unknown or the runtime rejects the call.
        #
        # Every setter asks for a redraw: an override changes the pose WITHOUT
        # changing the frame number, so a paused (or quiescent) player would
        # otherwise keep showing the previous frame until something else moved.
        def _norm_color(self, color):
            """Any Ren'Py colour form -> the packed 0xRRGGBBAA the core takes.

            Accepts everything `Color()` does — "#f00", (255, 0, 0[, a]), a
            Color — plus an already-packed 0xRRGGBBAA int."""
            if isinstance(color, int):
                return color & 0xFFFFFFFF
            # Color() answers None for None and RAISES for anything else it
            # cannot read (e.g. TypeError: not iterable). Either way the caller
            # deserves to be told which value was wrong, not a bare traceback
            # from inside Ren'Py's colour parser.
            try:
                c = renpy.color.Color(color)
            except Exception:
                c = None
            if c is None:
                raise ValueError(
                    "ss: %r is not a colour — pass \"#rrggbb\", an "
                    "(r, g, b[, a]) tuple, a Color, or a packed 0xRRGGBBAA int"
                    % (color,))
            r, g, b, a = c
            return (r << 24) | (g << 16) | (b << 8) | a

        def _record_override(self, part, kind, args):
            """Remember a set/clear so it can be restored after Ren'Py drops and
            rebuilds the native core (see _reapply_overrides). ``args=None``
            forgets the entry. Keyed by the RESOLVED part index, so a name and
            an index for the same part collapse to one record."""
            i = self._core.resolve_part(part) if self._core else -1
            if i < 0:
                return
            if args is None:
                self._overrides.pop((i, kind), None)
            else:
                self._overrides[(i, kind)] = args

        def _reapply_overrides(self):
            """Re-apply the recorded overrides onto a freshly built core.

            Ren'Py drops the native core on pickling (saves, rollback) and
            rebuilds it lazily, which would silently lose every override the
            game had set — so restoring them is host policy, the same tier that
            re-applies the animation, loop and speed. The Brain still owns the
            live table and its lifecycle; this only replays what the game asked
            for. One-shot (OverwriteOnNextKeyframe) overrides are deliberately
            never recorded: the Brain drops them when playback reaches the next
            keyframe, and that handover is not observable from here, so
            replaying one would resurrect an override that had already expired.
            """
            core = self._core
            if core is None or not self._overrides:
                return
            for (i, kind), args in list(self._overrides.items()):
                try:
                    if kind == "visibility":
                        core.set_part_visibility_override(i, args[0], args[1])
                    elif kind == "color":
                        color, blend_op, priority = args
                        if isinstance(color, tuple):
                            core.set_part_color_override_corners(
                                i, color, blend_op, priority)
                        else:
                            core.set_part_color_override(
                                i, color, blend_op, priority)
                    elif kind == "cell":
                        core.set_part_cell_override(i, args[0], args[1], args[2])
                except Exception:
                    # A record that no longer resolves (e.g. a cell removed by a
                    # re-export) must not break the rebuild — drop it silently.
                    self._overrides.pop((i, kind), None)

        def _permanent_overrides(self):
            """The subset of the override record that survives an animation
            change: Permanent colour/cell entries.

            Colour is ``(packed, blend_op, priority)`` and cell is
            ``(cellmap, cell, priority)`` — priority last in both; visibility has
            none and is always dropped. Tolerates a state unpickled before
            overrides existed (no ``_overrides`` attribute)."""
            return {key: args
                    for key, args in getattr(self, "_overrides", {}).items()
                    if key[1] != "visibility"
                    and args[2] == ssruntime.PRIORITY_PERMANENT}

        def _prune_overrides_for_new_animation(self):
            """Mirror the Brain's own lifecycle on a CREATOR-initiated animation
            change: visibility and non-Permanent colour/cell overrides are
            dropped, Permanent ones survive.

            Deliberately not called from _start_initial: that path also runs when
            the core is merely rebuilt (save/load, re-show), and pruning there
            would throw away the very records _reapply_overrides is restoring.
            """
            self._overrides = self._permanent_overrides()

        def ss_set_part_visibility_override(self, part, hide=True, cascade=False):
            """Force-hide ``part``, or revert it to the animation (``hide=False``).

            ``cascade`` propagates the force-hide to the part's descendants.
            Visibility takes no priority mode: it always wins, and any new
            animation clears it."""
            self._ensure()
            if not self._core.set_part_visibility_override(part, hide, cascade):
                return False
            # hide=False IS the revert (the runtime drops the entry), so record
            # it as a clear rather than as an override worth restoring.
            self._record_override(
                part, "visibility",
                (True, bool(cascade)) if hide else None)
            renpy.redraw(self, 0)
            return True

        def ss_clear_part_visibility_override(self, part):
            """Clear a part's visibility override (revert to the animation)."""
            self._ensure()
            if not self._core.clear_part_visibility_override(part):
                return False
            self._record_override(part, "visibility", None)
            renpy.redraw(self, 0)
            return True

        def ss_set_part_color_override(self, part, color, blend_op=0, priority=1):
            """Tint ``part`` with one colour (all four corners).

            ``blend_op``: 0=Mix, 1=Mul, 2=Add, 3=Sub. ``priority``:
            0=OverwriteOnNextKeyframe (one-shot), 1=HoldUntilNextAnimation
            (default), 2=Permanent. Normal parts only — other part types
            silently ignore it (the call still succeeds)."""
            self._ensure()
            packed = self._norm_color(color)
            if not self._core.set_part_color_override(part, packed, blend_op,
                                                      priority):
                return False
            if priority != ssruntime.PRIORITY_OVERWRITE_ON_NEXT_KEYFRAME:
                self._record_override(part, "color", (packed, blend_op, priority))
            renpy.redraw(self, 0)
            return True

        def ss_set_part_color_override_corners(self, part, corners, blend_op=0,
                                               priority=1):
            """Like :meth:`ss_set_part_color_override` with four distinct corner
            colours, given in ``left-top, right-top, left-bottom, right-bottom``
            order."""
            self._ensure()
            cols = list(corners) if corners is not None else []
            if len(cols) != 4:
                return False
            packed = tuple(self._norm_color(c) for c in cols)
            if not self._core.set_part_color_override_corners(
                    part, packed, blend_op, priority):
                return False
            if priority != ssruntime.PRIORITY_OVERWRITE_ON_NEXT_KEYFRAME:
                self._record_override(part, "color", (packed, blend_op, priority))
            renpy.redraw(self, 0)
            return True

        def ss_clear_part_color_override(self, part):
            """Clear a part's colour override (revert to the animation)."""
            self._ensure()
            if not self._core.clear_part_color_override(part):
                return False
            self._record_override(part, "color", None)
            renpy.redraw(self, 0)
            return True

        def ss_set_part_cell_override(self, part, cellmap_name, cell_name,
                                      priority=1):
            """Make ``part`` draw a different cell.

            ``cellmap_name`` is written WITHOUT the ``.ssce`` extension; list the
            valid targets with :meth:`ss_cellmap_names` / :meth:`ss_cell_names`.
            The cell is resolved immediately, so an unknown name returns False.
            Normal and mask parts only. Empty names revert to the animation."""
            self._ensure()
            if not self._core.set_part_cell_override(part, cellmap_name,
                                                     cell_name, priority):
                return False
            if not cellmap_name and not cell_name:
                self._record_override(part, "cell", None)   # the revert sentinel
            elif priority != ssruntime.PRIORITY_OVERWRITE_ON_NEXT_KEYFRAME:
                self._record_override(part, "cell",
                                      (cellmap_name, cell_name, priority))
            renpy.redraw(self, 0)
            return True

        def ss_clear_part_cell_override(self, part):
            """Clear a part's cell override (revert to the animation)."""
            self._ensure()
            if not self._core.clear_part_cell_override(part):
                return False
            self._record_override(part, "cell", None)
            renpy.redraw(self, 0)
            return True

        def ss_clear_all_part_overrides(self):
            """Clear every per-part override on this player."""
            self._ensure()
            if not self._core.clear_all_part_overrides():
                return False
            self._overrides = {}
            renpy.redraw(self, 0)
            return True

        def ss_cellmap_names(self):
            """Names of this pack's cellmaps (cell-override targets)."""
            self._ensure()
            return self._core.cellmap_names()

        def ss_cell_names(self, cellmap_name):
            """Names of the cells in ``cellmap_name`` (cell-override targets)."""
            self._ensure()
            return self._core.cell_names(cellmap_name)

    # Backwards-compatible alias for the original public class name.
    SpriteStudioDisplayable = SSPlayer


# Register the SS Audio channel pool. register_channel() is only allowed during
# the init phase, so this runs here (a normal `init python`, after the library's
# `init -10` defs and after Ren'Py's built-in mixers) rather than lazily at play
# time. Deliberately non-invasive: a private `ss_audio_*` namespace on the chosen
# mixer, created ONLY when SS_ENABLE_AUDIO is on, so it never disturbs the game's
# own sound / music / voice channels — while giving zero-config parallel playback
# to anyone who just wants sound. A dev reload re-runs this and register_channel
# cleanly replaces the existing channels.
init python:
    if SS_ENABLE_AUDIO:
        _SS_AUDIO_POOL = ["ss_audio_%d" % _i
                          for _i in range(max(1, SS_AUDIO_CHANNELS))]
        for _c in _SS_AUDIO_POOL:
            try:
                renpy.music.register_channel(_c, mixer=SS_AUDIO_MIXER, loop=False)
            except Exception as _e:
                renpy.log("ss: could not register audio channel %r (%r)"
                          % (_c, _e))
        # Register the off-screen audio reaper as a periodic callback (~20Hz), so
        # a player swapped out of a screen (no `_hide`) still stops sounding.
        # Drop any stale copy first (a dev reload redefines the function).
        renpy.config.periodic_callbacks[:] = [
            _cb for _cb in renpy.config.periodic_callbacks
            if getattr(_cb, "__name__", "") != "_ss_audio_reaper"]
        renpy.config.periodic_callbacks.append(_ss_audio_reaper)
