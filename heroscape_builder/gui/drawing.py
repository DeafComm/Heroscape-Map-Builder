"""Colours and shapes shared by the map and the piece list."""

import math

from PySide6.QtCore import QLineF, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from ..hexgrid import hex_corners, hex_to_pixel, rotate
from ..model import MAX_LAYER

HEX_RADIUS = 20.0

TERRAIN_COLOURS = {
    "grass": QColor("#5aa83c"),
    "rock": QColor("#9a9590"),
    "sand": QColor("#e3c977"),
    "water": QColor("#3b86d6"),
    "ruin": QColor("#b07a4a"),
    "road": QColor("#b5a88f"),
    "swamp": QColor("#6f7d3c"),
    "swamp_water": QColor("#4c7b74"),
    "tree": QColor("#2e6b2f"),
    "castle_wall": QColor("#b8b2a7"),
    "walk": QColor("#cdc6b8"),
    "stone_wall": QColor("#d8d2c6"),
    "ladder": QColor("#c9a46a"),
}

DETAIL = QColor("#2b2b2b")

# Axial steps to the six neighbours, matching the hex edges a castle wall can run to.
DIRECTIONS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]


def terrain_colour(terrain, layer=1):
    """The terrain colour, darker on low layers and brighter on high ones."""
    base = TERRAIN_COLOURS.get(terrain, QColor("#c040c0"))
    h, s, v, _ = base.getHsvF()
    t = (layer - 1) / (MAX_LAYER - 1)
    return QColor.fromHsvF(max(h, 0.0), s * (1.0 - 0.35 * t), min(1.0, v * (0.8 + 0.4 * t)))


def text_colour(fill):
    return QColor("#111111") if fill.lightnessF() > 0.55 else QColor("#ffffff")


def hex_polygon(q, r, radius=HEX_RADIUS):
    cx, cy = hex_to_pixel(q, r, radius)
    return QPolygonF([QPointF(x, y) for x, y in hex_corners(cx, cy, radius)])


def outline_path(cells, radius=HEX_RADIUS):
    """One path around all the given hexes."""
    path = QPainterPath()
    for q, r in cells:
        path.addPolygon(hex_polygon(q, r, radius))
        path.closeSubpath()
    return path.simplified()


def blend(colour, other, amount):
    """Mix amount (0 to 1) of other into colour."""
    return QColor(
        round(colour.red() + (other.red() - colour.red()) * amount),
        round(colour.green() + (other.green() - colour.green()) * amount),
        round(colour.blue() + (other.blue() - colour.blue()) * amount),
    )


def _centre(q, r, radius):
    return QPointF(*hex_to_pixel(q, r, radius))


def _edge_point(q, r, direction, radius):
    """The middle of the hex edge facing the neighbour in direction (an axial step)."""
    dq, dr = direction
    return (_centre(q, r, radius) + _centre(q + dq, r + dr, radius)) / 2


def paint_details(painter, piece, q, r, rotation, radius=HEX_RADIUS, wash=0.0, wash_colour=QColor("#ffffff")):
    """Draw what marks out trees, walls, ladders and wall walks on top of their hexes."""
    colour = blend(DETAIL, wash_colour, wash)
    cells = piece.cells(q, r, rotation)
    painter.save()
    painter.setBrush(Qt.NoBrush)
    if piece.kind == "tree":
        leaf = blend(QColor("#1d4a1f"), wash_colour, wash)
        painter.setPen(QPen(leaf, radius * 0.12))
        painter.setBrush(blend(QColor("#3f8a3c"), wash_colour, wash))
        for cq, cr in cells:
            painter.drawEllipse(_centre(cq, cr, radius), radius * 0.55, radius * 0.55)
    elif piece.kind == "castle_wall":
        painter.setPen(QPen(colour, radius * 0.35, Qt.SolidLine, Qt.RoundCap))
        cq, cr = cells[0]
        centre = _centre(cq, cr, radius)
        for edge in piece.walls:
            painter.drawLine(QLineF(centre, _edge_point(cq, cr, rotate(*DIRECTIONS[edge], rotation), radius)))
    elif piece.kind == "doorway":
        ends = [_centre(*cells[0], radius), _centre(*cells[-1], radius)]
        painter.setPen(QPen(colour, radius * 0.35, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QLineF(*ends))
        painter.setBrush(colour)
        for point in ends:
            painter.drawEllipse(point, radius * 0.4, radius * 0.4)
        # The open way through, under the arch.
        painter.setPen(QPen(blend(QColor("#f4f1ea"), wash_colour, wash), radius * 0.12, Qt.DashLine))
        cx, cy = hex_to_pixel(*cells[1], radius)
        painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in hex_corners(cx, cy, radius * 0.55)]))
    elif piece.kind == "walk":
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        for cq, cr in piece.support_cells(q, r, rotation):
            painter.drawEllipse(_centre(cq, cr, radius), radius * 0.18, radius * 0.18)
    elif piece.kind == "ladder":
        painter.setPen(QPen(blend(QColor("#5a3a17"), wash_colour, wash), radius * 0.12))
        c = _centre(*cells[0], radius)
        w, h = radius * 0.3, radius * 0.6
        painter.drawLine(QLineF(c.x() - w, c.y() - h, c.x() - w, c.y() + h))
        painter.drawLine(QLineF(c.x() + w, c.y() - h, c.x() + w, c.y() + h))
        for i in range(4):
            y = c.y() - h + (i + 0.5) * 2 * h / 4
            painter.drawLine(QLineF(c.x() - w, y, c.x() + w, y))
    elif piece.kind == "stone_wall":
        a, b = _centre(*cells[0], radius), _centre(*cells[-1], radius)
        length = math.hypot(b.x() - a.x(), b.y() - a.y())
        ux, uy = (b.x() - a.x()) / length, (b.y() - a.y()) / length
        side = piece.side_cells(q, r, rotation)
        sx = sum(_centre(cq, cr, radius).x() for cq, cr in side) / len(side) - (a.x() + b.x()) / 2
        sy = sum(_centre(cq, cr, radius).y() for cq, cr in side) / len(side) - (a.y() + b.y()) / 2
        # Push the line out towards the tiles it stands against, onto the edge between the rows.
        along = sx * ux + sy * uy
        nx, ny = sx - along * ux, sy - along * uy
        n = math.hypot(nx, ny) or 1.0
        nx, ny = nx / n * radius * 0.75, ny / n * radius * 0.75
        ext = radius * 0.87
        painter.setPen(QPen(colour, radius * 0.4, Qt.SolidLine, Qt.FlatCap))
        painter.drawLine(QLineF(a.x() - ux * ext + nx, a.y() - uy * ext + ny, b.x() + ux * ext + nx, b.y() + uy * ext + ny))
    painter.restore()


def piece_icon(piece, size=56):
    """A small picture of the piece's shape."""
    radius = 10.0
    cells = piece.cells(0, 0, 0)
    path = outline_path(cells, radius)
    rect = path.boundingRect()
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    scale = min((size - 4) / rect.width(), (size - 4) / rect.height(), 1.4)
    painter.translate(size / 2, size / 2)
    painter.scale(scale, scale)
    painter.translate(-rect.center())
    fill = terrain_colour(piece.terrain, 6)
    painter.setPen(QColor(0, 0, 0, 60))
    painter.setBrush(fill)
    for q, r in cells:
        painter.drawPolygon(hex_polygon(q, r, radius))
    paint_details(painter, piece, 0, 0, 0, radius)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QColor("#222222"))
    painter.drawPath(path)
    painter.end()
    return pixmap
