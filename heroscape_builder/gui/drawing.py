"""Colours and shapes shared by the map and the piece list."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap, QPolygonF

from ..hexgrid import hex_corners, hex_to_pixel
from ..model import MAX_LAYER

HEX_RADIUS = 20.0

TERRAIN_COLOURS = {
    "grass": QColor("#5aa83c"),
    "rock": QColor("#9a9590"),
    "sand": QColor("#e3c977"),
    "water": QColor("#3b86d6"),
    "ruin": QColor("#b07a4a"),
}


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
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QColor("#222222"))
    painter.drawPath(path)
    painter.end()
    return pixmap
