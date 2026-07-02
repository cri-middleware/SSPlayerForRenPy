# Limitations & Scope

This is a list of supported features and limitations in the currently provided SpriteStudio Player for Ren'Py.

## Current Status

We currently support the core features of SpriteStudio 7, including Mesh, Effect, and Instance.

### Supported Features
- **Normal Parts**: Basic rendering
- **Transforms**: Position, Rotation, Non-uniform scale, H/V flip
- **Hierarchical Structure**: Parent-child linking (Pre-baked world matrices in `RenderMode::Direct`)
- **Alpha and Blending**: Per-part opacity (Alpha), major blend modes (Mix, Add, Multiply, etc.)
- **Vertex Color (`parts_color`)**: Application of vertex colors and color blending (Mix, Add, Multiply, Sub, etc.)
- **Mesh / Free Deformation**: GL2 mesh-based freeform deformation and weighted deformation via bone linking
- **Special Parts**:
  - **Effect** (Particle Effects)
  - **Instance** (Nested animation playback)
  - **Mask** (Clipping mask feature)
- **User Data / Events**: Signal processing via callbacks on the script side (animation events)

### Limitations / Not Yet Supported
> [!WARNING]
> - **Some Special Parts**: `Shape`, `Text`, and `NineSlice` are currently not supported (with exceptions such as using `Shape` as a mask area).
> - **Some Special Blends**: Because we rely on Ren'Py's `config.gl_blend_func`, highly specialized blend modes may default to approximations or standard Mix.

## Performance and Platform Notes

> [!NOTE]
> **Performance**
> Because rendering is routed through `ctypes` and Creator-Defined Displayables, your frame rate may be affected by animations with an extremely high mesh vertex count, or by having many particle effects overlapping at once.

> [!WARNING]
> **Supported Platforms**
> The native library is only expected to load on Desktop platforms (Windows, macOS, Linux). Implementations for Mobile (Android, iOS) and Web platforms are future tasks.

> [!TIP]
> **Distribution (`.rpa`)**
> Because `.ssab` files and textures are loaded via Ren'Py's loader, you can package them into an `.rpa` archive for release builds or leave them loosely placed.
