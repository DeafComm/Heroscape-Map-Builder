"""A 3D view of the map: an isometric picture that can be turned, zoomed and moved, but not edited."""

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from ..hexgrid import from_offset, hex_corners, hex_to_pixel
from .drawing import HEX_RADIUS, blend, terrain_colour

LAYER_HEIGHT = HEX_RADIUS * 0.5  # a bit thicker than the real tiles, so layers read clearly
ELEVATION = math.radians(30)  # the fixed tilt of the camera
TURN_STEP = 15  # degrees per press of Q or E
DRAG_TURN = 0.4  # degrees per pixel of right-drag
MIN_SCALE, MAX_SCALE = 0.2, 6.0
SEAM_SCALE = 1.6  # zoomed in at least this far, the lines between stacked layers show

BACKGROUND = QColor("#3a3f44")
BOARD = QColor("#e9e4d8")
BOARD_LINE = QColor(0, 0, 0, 22)
SIDE_TAN = QColor("#c9a777")  # the sides of the real tiles
SIDE_STONE = QColor("#a9a397")  # castle parts and roads are grey plastic
TOP_STONE = QColor("#c9c3b7")
TRUNK = QColor("#7a5230")
LEAVES = QColor("#2f6b35")
LADDER = QColor("#9a6a3a")
OUTLINE = QColor(40, 30, 20, 120)

# The neighbour across each edge of hex_corners: edge i runs from corner i to corner i + 1.
EDGE_NEIGHBOURS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]
STONE_KINDS = ("castle_wall", "doorway", "walk", "stone_wall")


class Prism:
    """A straight-sided solid: a flat polygon (in map pixels) raised from z0 to z1."""

    def __init__(self, points, z0, z1, top, side, hidden_edges=(), cover_top=False, seam=False):
        self.points = points
        self.z0, self.z1 = z0, z1
        self.top, self.side = top, side
        self.hidden_edges = set(hidden_edges)  # sides that touch a neighbour, never seen
        self.cover_top = cover_top  # something sits right on top, so the top isn't seen
        self.seam = seam  # draw the layer line along the top of the sides when zoomed in
        self.centre = (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


class Cone:
    """A round cone, for the evergreen trees."""

    def __init__(self, cx, cy, radius, z0, z1, colour):
        self.centre = (cx, cy)
        self.radius = radius
        self.z0, self.z1 = z0, z1
        self.colour = colour


def _scaled(points, centre, factor):
    cx, cy = centre
    return [(cx + (x - cx) * factor, cy + (y - cy) * factor) for x, y in points]


def _hull(points):
    """Convex hull of 2D points (monotone chain), as QPointF."""
    pts = sorted(set((round(p.x(), 2), round(p.y(), 2)) for p in points))
    if len(pts) < 3:
        return [QPointF(*p) for p in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return [QPointF(*p) for p in lower[:-1] + upper[:-1]]


def build_solids(model, max_layer=None):
    """Turn the map into solids to draw. Only tiles starting at or below max_layer, if given."""
    tiles = [t for t in model.tiles.values() if max_layer is None or t.layer <= max_layer]
    shown = {t.uid for t in tiles}
    occupied = {}  # (q, r, layer) -> tile, for working out hidden faces
    for t in tiles:
        for cell in model.cells_of(t):
            for layer in range(t.layer, model.top_of(t) + 1):
                occupied[(cell[0], cell[1], layer)] = t

    def solid_tile(q, r, layer):
        other = occupied.get((q, r, layer))
        return other is not None and other.uid in shown and model.piece(other).kind in ("tile", "walk")

    solids = []
    R, T = HEX_RADIUS, LAYER_HEIGHT
    for t in tiles:
        piece = model.piece(t)
        cells = model.cells_of(t)
        z0 = (t.layer - 1) * T
        z1 = model.top_of(t) * T
        kind = piece.kind
        stone = kind in STONE_KINDS or piece.terrain == "road"
        side = SIDE_STONE if stone else SIDE_TAN
        top = TOP_STONE if kind in STONE_KINDS else terrain_colour(piece.terrain, t.layer)
        if kind in ("tile", "walk"):
            for q, r in cells:
                points = hex_corners(*hex_to_pixel(q, r, R), R)
                hidden = [i for i, (dq, dr) in enumerate(EDGE_NEIGHBOURS) if solid_tile(q + dq, r + dr, t.layer)]
                covered = solid_tile(q, r, t.layer + 1)
                solids.append(Prism(points, z0, z1, top, side, hidden, covered, seam=True))
        elif kind == "tree":
            centre = [sum(c) / len(cells) for c in zip(*(hex_to_pixel(q, r, R) for q, r in cells))]
            spread = 1.0 if len(cells) == 1 else 1.9
            height = z1 - z0
            trunk = hex_corners(centre[0], centre[1], R * 0.16 * spread)
            solids.append(Prism(trunk, z0, z0 + height * 0.3, TRUNK, TRUNK))
            solids.append(Cone(centre[0], centre[1], R * 0.85 * spread, z0 + height * 0.15, z0 + height * 0.7, LEAVES))
            solids.append(
                Cone(centre[0], centre[1], R * 0.6 * spread, z0 + height * 0.45, z1, blend(LEAVES, QColor("#ffffff"), 0.08))
            )
        elif kind == "castle_wall":
            q, r = cells[0]
            points = hex_corners(*hex_to_pixel(q, r, R), R * 0.9)
            solids.append(Prism(points, z0, z1, top, side))
        elif kind == "doorway":
            for i, (q, r) in enumerate(cells):
                if i in (0, len(cells) - 1):
                    points = hex_corners(*hex_to_pixel(q, r, R), R * 0.9)
                    solids.append(Prism(points, z0, z1, top, side))
                else:
                    # The arch over the way through.
                    points = hex_corners(*hex_to_pixel(q, r, R), R)
                    solids.append(Prism(points, z1 - 2 * T, z1, top, side))
        elif kind == "ladder":
            q, r = cells[0]
            points = hex_corners(*hex_to_pixel(q, r, R), R * 0.3)
            solids.append(Prism(points, z0, z1, LADDER, LADDER))
        elif kind == "stone_wall":
            solids.append(Prism(_stone_wall_footprint(piece, t), z0, z0 + 3 * T, top, side))
    return solids


def _stone_wall_footprint(piece, tile):
    """A thin slab along the edge of the row of tiles the wall stands against."""
    R = HEX_RADIUS
    cells = piece.cells(tile.q, tile.r, tile.rotation)
    ax, ay = hex_to_pixel(*cells[0], R)
    bx, by = hex_to_pixel(*cells[-1], R)
    length = math.hypot(bx - ax, by - ay)
    ux, uy = (bx - ax) / length, (by - ay) / length
    side = [hex_to_pixel(q, r, R) for q, r in piece.side_cells(tile.q, tile.r, tile.rotation)]
    sx = sum(p[0] for p in side) / len(side) - (ax + bx) / 2
    sy = sum(p[1] for p in side) / len(side) - (ay + by) / 2
    along = sx * ux + sy * uy
    nx, ny = sx - along * ux, sy - along * uy
    n = math.hypot(nx, ny) or 1.0
    nx, ny = nx / n, ny / n
    ext, off, half = R * 0.87, R * 0.75, R * 0.15
    a = (ax - ux * ext + nx * off, ay - uy * ext + ny * off)
    b = (bx + ux * ext + nx * off, by + uy * ext + ny * off)
    return [
        (a[0] - nx * half, a[1] - ny * half),
        (b[0] - nx * half, b[1] - ny * half),
        (b[0] + nx * half, b[1] + ny * half),
        (a[0] + nx * half, a[1] + ny * half),
    ]


class Map3DView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(200, 200)
        self.model = None
        self.angle = 0.0  # degrees, turned around the middle of the map
        self.scale = 1.0
        self.pan = QPointF(0, 0)
        self.cut_layer = None  # only show tiles starting at or below this layer
        self.solids = []
        self._drag = None  # (button, last position)
        self._needs_fit = True

    # --- content ------------------------------------------------------

    def set_model(self, model):
        self.model = model
        self._needs_fit = True
        self.refresh()

    def set_cut_layer(self, layer):
        self.cut_layer = layer
        self.refresh()

    def refresh(self):
        if self.model is None:
            return
        self.solids = build_solids(self.model, self.cut_layer)
        self.update()

    def _board_centre(self):
        size = self.model.size
        x0, y0 = hex_to_pixel(*from_offset(0, 0), HEX_RADIUS)
        x1, y1 = hex_to_pixel(*from_offset(size - 1, size - 1), HEX_RADIUS)
        return (x0 + x1) / 2, (y0 + y1) / 2

    def fit(self):
        """Turn back to the start and zoom so the whole board fits."""
        if self.model is None or self.width() < 10:
            return
        self.angle = 0.0
        self.pan = QPointF(0, 0)
        self.scale = 1.0
        size = self.model.size
        corners = [from_offset(c, r) for c in (0, size - 1) for r in (0, size - 1)]
        xs, ys = [], []
        for q, r in corners:
            x, y = self._project_raw(*hex_to_pixel(q, r, HEX_RADIUS), 0)
            xs.append(x)
            ys.append(y)
        width = (max(xs) - min(xs)) + 4 * HEX_RADIUS
        height = (max(ys) - min(ys)) + 8 * HEX_RADIUS
        self.scale = max(MIN_SCALE, min(MAX_SCALE, 0.92 * min(self.width() / width, self.height() / height)))
        self._needs_fit = False
        self.update()

    # --- projection ---------------------------------------------------

    def _rotated(self, x, y):
        cx, cy = self._centre
        a = math.radians(self.angle)
        dx, dy = x - cx, y - cy
        return dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)

    def _project_raw(self, x, y, z):
        self._centre = self._board_centre()
        xr, yr = self._rotated(x, y)
        return xr, yr * math.sin(ELEVATION) - z * math.cos(ELEVATION)

    def project(self, x, y, z):
        xr, yr = self._rotated(x, y)
        return QPointF(
            self.width() / 2 + self.pan.x() + self.scale * xr,
            self.height() / 2 + self.pan.y() + self.scale * (yr * math.sin(ELEVATION) - z * math.cos(ELEVATION)),
        )

    def _depth(self, solid):
        _xr, yr = self._rotated(*solid.centre)
        return (round(yr, 1), solid.z0)

    # --- drawing ------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND)
        if self.model is None:
            return
        if self._needs_fit:
            self.fit()
        self._centre = self._board_centre()
        painter.setRenderHint(QPainter.Antialiasing)
        self._paint_board(painter)
        for solid in sorted(self.solids, key=self._depth):
            if isinstance(solid, Cone):
                self._paint_cone(painter, solid)
            else:
                self._paint_prism(painter, solid)

    def _paint_board(self, painter):
        path = QPainterPath()
        size = self.model.size
        for row in range(size):
            for col in range(size):
                q, r = from_offset(col, row)
                points = [self.project(x, y, 0) for x, y in hex_corners(*hex_to_pixel(q, r, HEX_RADIUS), HEX_RADIUS)]
                path.addPolygon(QPolygonF(points))
                path.closeSubpath()
        painter.setPen(QPen(BOARD_LINE, 1))
        painter.setBrush(BOARD)
        painter.drawPath(path)

    def _shade(self, colour, nx, ny):
        """Light the side facing direction (nx, ny) on the map: brighter facing the upper left."""
        a = math.radians(self.angle)
        length = math.hypot(nx, ny) or 1.0
        sx = (nx * math.cos(a) - ny * math.sin(a)) / length
        factor = 0.86 - 0.14 * sx
        return QColor.fromRgbF(
            min(1.0, colour.redF() * factor), min(1.0, colour.greenF() * factor), min(1.0, colour.blueF() * factor)
        )

    def _paint_prism(self, painter, prism):
        points = prism.points
        n = len(points)
        cx, cy = prism.centre
        bottom = [self.project(x, y, prism.z0) for x, y in points]
        top = [self.project(x, y, prism.z1) for x, y in points]
        a = math.radians(self.angle)
        seam = prism.seam and self.scale >= SEAM_SCALE
        for i in range(n):
            if i in prism.hidden_edges:
                continue
            (x0, y0), (x1, y1) = points[i], points[(i + 1) % n]
            nx, ny = (x0 + x1) / 2 - cx, (y0 + y1) / 2 - cy
            # Only sides facing the camera (towards the bottom of the screen) are seen.
            if nx * math.sin(a) + ny * math.cos(a) <= 0:
                continue
            colour = self._shade(prism.side, nx, ny)
            painter.setPen(QPen(colour, 1))
            painter.setBrush(colour)
            painter.drawPolygon(QPolygonF([bottom[i], bottom[(i + 1) % n], top[(i + 1) % n], top[i]]))
            if seam:
                painter.setPen(QPen(OUTLINE, 0.8))
                painter.drawLine(top[i], top[(i + 1) % n])
        if prism.cover_top:
            return
        painter.setPen(QPen(OUTLINE, 1))
        painter.setBrush(prism.top)
        painter.drawPolygon(QPolygonF(top))

    def _paint_cone(self, painter, cone):
        cx, cy = cone.centre
        base = [
            self.project(cx + cone.radius * math.cos(2 * math.pi * k / 16), cy + cone.radius * math.sin(2 * math.pi * k / 16), cone.z0)
            for k in range(16)
        ]
        apex = self.project(cx, cy, cone.z1)
        painter.setPen(QPen(blend(cone.colour, QColor("#000000"), 0.35), 1))
        painter.setBrush(cone.colour)
        painter.drawPolygon(QPolygonF(_hull(base + [apex])))

    # --- mouse and keyboard -------------------------------------------

    def turn(self, degrees):
        self.angle = (self.angle + degrees) % 360
        self.update()

    def zoom_by(self, factor):
        self.scale = max(MIN_SCALE, min(MAX_SCALE, self.scale * factor))
        self.update()

    def mousePressEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            self._drag = (event.button(), event.position())
            self.setCursor(Qt.ClosedHandCursor if event.button() == Qt.LeftButton else Qt.SizeHorCursor)

    def mouseMoveEvent(self, event):
        if not self._drag:
            return
        button, last = self._drag
        pos = event.position()
        delta = pos - last
        self._drag = (button, pos)
        if button == Qt.RightButton:
            self.turn(delta.x() * DRAG_TURN)
        else:
            self.pan += delta
            self.update()

    def mouseReleaseEvent(self, event):
        self._drag = None
        self.unsetCursor()

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120
        if steps:
            self.zoom_by(1.15**steps)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Q:
            self.turn(-TURN_STEP)
        elif event.key() == Qt.Key_E:
            self.turn(TURN_STEP)
        else:
            event.ignore()  # let the window handle + and - for layers

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._needs_fit:
            self.fit()
