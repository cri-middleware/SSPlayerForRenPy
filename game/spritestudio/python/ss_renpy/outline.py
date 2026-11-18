"""Part outlines, and the hit test over them, on the last frame drawn.

A part's outline is the quad it is drawn with, in the space
``SSInternalPlayer.part_transform`` reports (the animation's origin at
``(0, 0)``, ``y`` downward), as four ``(x, y)`` corners in the runtime's
``lt, rt, lb, rb`` order:

  * a part with a cell: its four local vertices through its world matrix, skew
    and vertex deform included;
  * a Mesh part: the axis-aligned box around its vertices, which the runtime
    hands over in world space -- a skinned mesh's own matrix sits near the root
    and does not describe the art;
  * a part with a size and no cell (a Shape): the size around its pivot,
    through its world matrix. A vertex deform that carries a Shape's corner
    outside its size is not followed;
  * Null, bone, Instance and Effect parts, which have no size, and hidden
    parts: no outline. A part drawn at alpha 0 has one.

The runtime's buffers last until its next call: a slot step or an update
reuses them, and on the native build a setup clears them, while the web build
keeps its last copy. Read at query time, they would describe another frame, or
none, and the two builds would disagree; :class:`FrameCopy` copies what an
outline needs out of each frame instead, into buffers kept from frame to frame.
"""

from __future__ import annotations

from ss_renpy import framedata


def _into(dst: bytearray, src, nbytes: int) -> int:
    if nbytes > len(dst):
        dst.extend(bytes(nbytes - len(dst)))
    if nbytes > 0:
        memoryview(dst)[:nbytes] = memoryview(src).cast("B")[:nbytes]
    return max(nbytes, 0)


def _soa_into(dst: bytearray, soa, itemsize: int = 4) -> int:
    view, n = soa
    return _into(dst, view, n * itemsize) if view is not None else 0


def contains(quad, x: float, y: float) -> bool:
    """Whether ``(x, y)`` lies inside the outline ``lt -> rt -> rb -> lb`` of
    ``quad``, by the even-odd rule, so a deform that folds it over itself still
    answers."""
    (ltx, lty), (rtx, rty), (lbx, lby), (rbx, rby) = quad
    inside = False
    for ax, ay, bx, by in ((ltx, lty, lbx, lby), (rtx, rty, ltx, lty),
                           (rbx, rby, rtx, rty), (lbx, lby, rbx, rby)):
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


class FrameCopy:
    """What the outlines of one frame are read from, copied out of the runtime
    before anything else touches it: the FrameData (the part states and the
    draw order), the local vertices and, for a pack with Mesh parts, the Mesh
    vertices. The world matrices are the player's own snapshot."""

    __slots__ = ("_frame", "_n_frame", "_local", "_n_local", "_mesh_x",
                 "_mesh_y", "_mesh_at", "_n_mesh", "_n_mesh_at", "_world")

    def __init__(self) -> None:
        self._frame = bytearray()
        self._local = bytearray()
        self._mesh_x = bytearray()
        self._mesh_y = bytearray()
        self._mesh_at = bytearray()
        self._n_frame = self._n_local = self._n_mesh = self._n_mesh_at = 0
        self._world = None

    def capture(self, rt, fb, world, with_mesh: bool) -> None:
        """Copy frame ``fb`` of ``rt``, whose world matrices are ``world``.
        Call right after ``get_frame_data_view``, before any slot steps."""
        self._world = world
        self._n_frame = _into(self._frame, fb, len(fb)) if fb else 0
        self._n_local = _soa_into(self._local, rt.local_vertices())
        if with_mesh:
            self._n_mesh = _soa_into(self._mesh_x, rt.mesh_vertices_x())
            _soa_into(self._mesh_y, rt.mesh_vertices_y())
            self._n_mesh_at = _soa_into(self._mesh_at, rt.mesh_vertex_offsets())

    def _frame_data(self):
        if not self._n_frame:
            return None
        return framedata.parse(bytes(memoryview(self._frame)[:self._n_frame]))

    def quad(self, index: int):
        """The outline of part ``index``, or ``None``."""
        fd = self._frame_data()
        if fd is None or not 0 <= index < fd.PartsLength():
            return None
        return self._quad(fd, index)

    def hit_test(self, x: float, y: float, targets=None) -> int:
        """The front-most part whose outline holds ``(x, y)``, among the part
        indices in ``targets`` (every part when ``None``), or -1."""
        fd = self._frame_data()
        if fd is None:
            return -1
        count = fd.PartsLength()
        # Back to front: the runtime leaves hidden parts out of the order.
        for rank in range(fd.DrawOrderLength() - 1, -1, -1):
            index = fd.DrawOrder(rank)
            if index >= count or (targets is not None and index not in targets):
                continue
            quad = self._quad(fd, index)
            if quad is not None and contains(quad, x, y):
                return index
        return -1

    def _quad(self, fd, i: int):
        ps = fd.Parts(i)
        w = self._world
        m = i * framedata.MATRIX_STRIDE
        if ps is None or ps.Hide() or w is None or m + 16 > len(w):
            return None
        if i + 1 < self._n_mesh_at // 4:
            at = memoryview(self._mesh_at)[:self._n_mesh_at].cast("I")
            lo, hi = at[i], at[i + 1]
            if hi > lo and hi * 4 <= self._n_mesh:
                xs = memoryview(self._mesh_x)[lo * 4:hi * 4].cast("f")
                ys = memoryview(self._mesh_y)[lo * 4:hi * 4].cast("f")
                left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
                return ((left, top), (right, top), (left, bottom), (right, bottom))
        mat = w[m:m + 16]
        if ps.Cell() >= 0:
            v = i * framedata.VERT_STRIDE
            if (v + 8) * 4 > self._n_local:
                return None
            lv = memoryview(self._local)[v * 4:(v + 8) * 4].cast("f")
            return tuple(framedata._transform(mat, lv[c], lv[c + 1])
                         for c in (0, 2, 4, 6))
        width, height = ps.SizeX(), ps.SizeY()
        if not (width > 0 and height > 0):
            return None
        left = -(0.5 + ps.PivotX()) * width
        top = -(0.5 + ps.PivotY()) * height
        right, bottom = left + width, top + height
        return tuple(framedata._transform(mat, cx, cy) for cx, cy in
                     ((left, top), (right, top), (left, bottom), (right, bottom)))
