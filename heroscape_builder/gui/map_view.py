"""The map space: draws the hex grid and tiles, and handles placing tiles."""

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView

from ..hexgrid import from_offset, hex_to_pixel, pixel_to_hex, rotate
from ..history import MoveCommand, PlaceCommand, RemoveCommand
from ..model import PlacedTile
from .drawing import HEX_RADIUS, hex_polygon, outline_path, terrain_colour, text_colour

GRID_FILL = QColor("#f4f1ea")
GRID_LINE = QColor("#d6d0c4")
OVER_LIMIT = QColor("#e01b1b")
SELECTED = QColor("#ffd400")
GHOST_OK = QColor("#1f9d3a")
OTHER_LAYER_TINT = QColor("#5b6b85")  # tiles below the current layer are washed towards this

# Scene units are scaled by this, so a hex is drawn about 22 pixels from centre to corner.
VIEW_SCALE = 1.08

# How a tile relates to the layer being worked on.
ACTIVE, BELOW, ABOVE = "active", "below", "above"


class TileItem(QGraphicsItem):
    """A placed tile, or the ghost of a tile being carried."""

    def __init__(self, piece, cells, layer, ghost=False):
        super().__init__()
        self.piece = piece
        self.cells = cells
        self.layer = layer
        self.ghost = ghost
        self.over_limit = False
        self.selected = False
        self.blocked = False
        self.state = ACTIVE
        self.path = outline_path(cells)
        self.polygons = [hex_polygon(q, r) for q, r in cells]
        self.centres = [QPointF(*hex_to_pixel(q, r, HEX_RADIUS)) for q, r in cells]
        self.setZValue(layer * 10 + (5 if ghost else 0))

    def boundingRect(self):
        return self.path.boundingRect().adjusted(-4, -4, 4, 4)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        fill = terrain_colour(self.piece.terrain, self.layer)
        if self.state == BELOW:
            fill = _blend(fill, OTHER_LAYER_TINT, 0.7)
        if self.ghost:
            fill.setAlpha(150)
        painter.setPen(QPen(QColor(0, 0, 0, 50), 0.8))
        painter.setBrush(fill)
        for polygon in self.polygons:
            painter.drawPolygon(polygon)

        if self.ghost:
            outline = QPen(OVER_LIMIT if self.blocked else GHOST_OK, 3, Qt.DashLine)
        elif self.selected:
            outline = QPen(SELECTED, 4)
        elif self.over_limit:
            outline = QPen(OVER_LIMIT, 3.5)
        elif self.state == BELOW:
            outline = QPen(QColor("#2e3644"), 1.2)
        else:
            outline = QPen(QColor("#1d1d1d"), 1.8)
        painter.setPen(outline)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path)
        if self.selected and self.over_limit:
            painter.setPen(QPen(OVER_LIMIT, 1.5))
            painter.drawPath(self.path)

        font = QFont()
        font.setPixelSize(int(HEX_RADIUS * 0.75))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(text_colour(fill))
        for centre in self.centres:
            rect = QRectF(centre.x() - HEX_RADIUS, centre.y() - HEX_RADIUS, HEX_RADIUS * 2, HEX_RADIUS * 2)
            painter.drawText(rect, Qt.AlignCenter, str(self.layer))


def _blend(colour, other, amount):
    """Mix amount (0 to 1) of other into colour."""
    return QColor(
        round(colour.red() + (other.red() - colour.red()) * amount),
        round(colour.green() + (other.green() - colour.green()) * amount),
        round(colour.blue() + (other.blue() - colour.blue()) * amount),
    )


class MapView(QGraphicsView):
    changed = Signal()  # the map was edited
    message = Signal(str)  # something to show in the status bar
    layer_step = Signal(int)  # +1 or -1 from the keyboard

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransform(QTransform.fromScale(VIEW_SCALE, VIEW_SCALE))
        self.setBackgroundBrush(QColor("#3a3f44"))
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setMouseTracking(True)

        self.model = None
        self.history = None
        self.active_layer = 1
        self.owned = {}
        self.palette_widget = None  # dropping a tile here removes it

        self.tile_items = {}
        self.grid_item = None
        self.ghost = None
        self.selected_uid = None
        self.last_placed = None  # (uid, piece_id, rotation) of the newest tile, for right-click copies
        self.carry = None
        self._press = None  # (uid, viewport pos, hex) of a press on a placed tile

    # --- document -----------------------------------------------------

    def set_document(self, model, history):
        self.model = model
        self.history = history
        self.selected_uid = None
        self.last_placed = None
        self.cancel_carry()
        self.rebuild()

    def rebuild(self):
        """Redraw the grid and tiles, after a new map or a change of map size."""
        self._build_grid()
        self.refresh()

    def set_active_layer(self, layer):
        self.active_layer = layer
        self.refresh()
        self._update_ghost()

    def set_owned(self, owned):
        self.owned = owned
        self.refresh()

    def _build_grid(self):
        scene = self.scene()
        scene.clear()
        self.tile_items = {}
        self.ghost = None
        size = self.model.size
        path = QPainterPath()
        for row in range(size):
            for col in range(size):
                path.addPolygon(hex_polygon(*from_offset(col, row)))
                path.closeSubpath()
        self.grid_item = QGraphicsPathItem(path)
        self.grid_item.setBrush(QBrush(GRID_FILL))
        self.grid_item.setPen(QPen(GRID_LINE, 1))
        self.grid_item.setZValue(-1)
        scene.addItem(self.grid_item)
        margin = HEX_RADIUS
        scene.setSceneRect(path.boundingRect().adjusted(-margin, -margin, margin, margin))
        self.centerOn(scene.sceneRect().center())

    def refresh(self):
        """Redraw every placed tile from the model."""
        if self.model is None:
            return
        scene = self.scene()
        for item in self.tile_items.values():
            scene.removeItem(item)
        self.tile_items = {}
        over = self.model.over_limit_uids(self.owned)
        moving = self.carry["moving_uid"] if self.carry else None
        for uid, tile in self.model.tiles.items():
            item = TileItem(self.model.piece(tile), self.model.cells_of(tile), tile.layer)
            item.over_limit = uid in over
            item.selected = uid == self.selected_uid
            if tile.layer > self.active_layer:
                item.state = ABOVE
                item.setOpacity(0.25)
            elif tile.layer < self.active_layer:
                item.state = BELOW
            if uid == moving:
                item.setVisible(False)
            scene.addItem(item)
            self.tile_items[uid] = item

    def _hex_at(self, viewport_pos):
        point = self.mapToScene(viewport_pos)
        return pixel_to_hex(point.x(), point.y(), HEX_RADIUS)

    def _over_viewport(self, global_pos):
        return self.viewport().rect().contains(self.viewport().mapFromGlobal(global_pos))

    def _over_palette(self, global_pos):
        w = self.palette_widget
        return w is not None and w.isVisible() and w.rect().contains(w.mapFromGlobal(global_pos))

    # --- carrying a tile ----------------------------------------------

    def start_carry(self, piece_id, rotation=0, moving_uid=None, grab=(0, 0), sticky=False):
        """Pick up a piece from the list, or a placed tile to move it."""
        self.cancel_carry()
        self.carry = {
            "piece_id": piece_id,
            "rotation": rotation % 6,
            "moving_uid": moving_uid,
            "grab": grab,  # offset from the tile's anchor to the hex under the cursor
            "sticky": sticky,  # keeps placing copies until cancelled
            "global_pos": None,
        }
        if moving_uid is not None:
            self.tile_items[moving_uid].setVisible(False)
        self.viewport().setCursor(Qt.ClosedHandCursor)
        self.setFocus()

    def make_sticky(self):
        if self.carry:
            self.carry["sticky"] = True
            self.message.emit("Click on the map to place copies. Right-click or press Esc to stop.")

    def cancel_carry(self):
        if not self.carry:
            return
        moving = self.carry["moving_uid"]
        self.carry = None
        if moving is not None and moving in self.tile_items:
            self.tile_items[moving].setVisible(True)
        self._remove_ghost()
        self.viewport().unsetCursor()

    def carry_move(self, global_pos):
        if not self.carry:
            return
        self.carry["global_pos"] = QPoint(global_pos)
        self._update_ghost()

    def carry_release(self, global_pos):
        """Drop what is being carried at global_pos."""
        if not self.carry:
            return
        carry = self.carry
        if self._over_viewport(global_pos):
            self._drop(self.viewport().mapFromGlobal(global_pos))
            if not carry["sticky"]:
                self.cancel_carry()
        elif carry["moving_uid"] is not None and self._over_palette(global_pos):
            self.cancel_carry()
            self.delete_tile(carry["moving_uid"])
        else:
            self.cancel_carry()

    def _target(self, viewport_pos):
        """Anchor hex and rotation for the carried piece at a viewport position."""
        q, r = self._hex_at(viewport_pos)
        gq, gr = self.carry["grab"]
        return q - gq, r - gr, self.carry["rotation"]

    def _drop(self, viewport_pos):
        carry = self.carry
        q, r, rotation = self._target(viewport_pos)
        moving = carry["moving_uid"]
        if moving is not None:
            tile = self.model.tiles[moving]
            problem = self.model.check(tile.piece_id, q, r, tile.layer, rotation, ignore_uid=moving)
            if problem:
                self.message.emit(f"Can't move there: {problem}")
                return
            if (q, r, rotation) != (tile.q, tile.r, tile.rotation):
                self.history.push(self.model, MoveCommand(tile, q, r, rotation))
                self.selected_uid = moving
                self.changed.emit()
            return
        problem = self.model.check(carry["piece_id"], q, r, self.active_layer, rotation)
        if problem:
            self.message.emit(f"Can't place there: {problem}")
            return
        self._place(carry["piece_id"], q, r, rotation)

    def _place(self, piece_id, q, r, rotation):
        """Place a new tile on the current layer and leave it selected for rotating."""
        tile = PlacedTile(0, piece_id, q, r, self.active_layer, rotation)
        self.history.push(self.model, PlaceCommand(tile))
        self.selected_uid = tile.uid
        self.last_placed = (tile.uid, piece_id, rotation)
        self.changed.emit()

    def place_copy(self, viewport_pos):
        """Right-click: place another of the most recently placed tile at the mouse."""
        if self.last_placed is None:
            self.message.emit("Place a tile first, then right-click to place more of it")
            return
        uid, piece_id, rotation = self.last_placed
        if uid in self.model.tiles:
            rotation = self.model.tiles[uid].rotation  # follow any rotation since it was placed
        q, r = self._hex_at(viewport_pos)
        problem = self.model.check(piece_id, q, r, self.active_layer, rotation)
        if problem:
            self.message.emit(f"Can't place there: {problem}")
            return
        self._place(piece_id, q, r, rotation)

    def _update_ghost(self):
        self._remove_ghost()
        if not self.carry or self.carry["global_pos"] is None:
            return
        global_pos = self.carry["global_pos"]
        if not self._over_viewport(global_pos):
            return
        q, r, rotation = self._target(self.viewport().mapFromGlobal(global_pos))
        piece = self.model.pieces[self.carry["piece_id"]]
        moving = self.carry["moving_uid"]
        layer = self.model.tiles[moving].layer if moving is not None else self.active_layer
        self.ghost = TileItem(piece, piece.cells(q, r, rotation), layer, ghost=True)
        self.ghost.blocked = self.model.check(piece.id, q, r, layer, rotation, ignore_uid=moving) is not None
        self.scene().addItem(self.ghost)

    def _remove_ghost(self):
        if self.ghost is not None:
            self.scene().removeItem(self.ghost)
            self.ghost = None

    # --- editing placed tiles -----------------------------------------

    def rotate(self, steps=1):
        if self.carry:
            self.carry["rotation"] = (self.carry["rotation"] + steps) % 6
            self.carry["grab"] = rotate(*self.carry["grab"], steps)
            self._update_ghost()
        elif self.selected_uid is not None:
            tile = self.model.tiles[self.selected_uid]
            rotation = (tile.rotation + steps) % 6
            problem = self.model.check(tile.piece_id, tile.q, tile.r, tile.layer, rotation, ignore_uid=tile.uid)
            if problem:
                self.message.emit(f"Can't rotate: {problem}")
                return
            self.history.push(self.model, MoveCommand(tile, tile.q, tile.r, rotation))
            self.changed.emit()

    def delete_tile(self, uid=None):
        uid = self.selected_uid if uid is None else uid
        if uid is None:
            return
        tile = self.model.tiles[uid]
        if self.model.follow_rules and self.model.supports_others(tile):
            self.message.emit("Can't remove a tile with other tiles on top of it")
            self.refresh()
            return
        self.history.push(self.model, RemoveCommand(tile))
        if self.selected_uid == uid:
            self.selected_uid = None
        self.changed.emit()

    def clear_selection(self):
        self.selected_uid = None
        self.refresh()

    # --- mouse and keyboard -------------------------------------------

    def mousePressEvent(self, event):
        if self.model is None:
            return
        if self.carry:
            if event.button() == Qt.LeftButton and self.carry["sticky"]:
                self._drop(event.position().toPoint())
                self._update_ghost()
            elif event.button() == Qt.RightButton:
                self.cancel_carry()
            return
        if event.button() == Qt.RightButton:
            self.place_copy(event.position().toPoint())
            return
        if event.button() != Qt.LeftButton:
            return
        q, r = self._hex_at(event.position().toPoint())
        tile = self.model.tile_at(q, r, self.active_layer)
        self.selected_uid = tile.uid if tile else None
        self._press = (tile.uid, event.position().toPoint(), (q, r)) if tile else None
        self.refresh()

    def mouseMoveEvent(self, event):
        global_pos = event.globalPosition().toPoint()
        if self.carry:
            self.carry_move(global_pos)
            return
        if self._press and event.buttons() & Qt.LeftButton:
            uid, start, (q, r) = self._press
            distance = (event.position().toPoint() - start).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self._press = None
                tile = self.model.tiles[uid]
                self.start_carry(tile.piece_id, tile.rotation, moving_uid=uid, grab=(q - tile.q, r - tile.r))
                self.carry_move(global_pos)

    def mouseReleaseEvent(self, event):
        self._press = None
        if self.carry and not self.carry["sticky"] and event.button() == Qt.LeftButton:
            self.carry_release(event.globalPosition().toPoint())

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            self.rotate(1 if delta < 0 else -1)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self.carry and self.carry["sticky"]:
            self._remove_ghost()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_R:
            self.rotate(-1 if event.modifiers() & Qt.ShiftModifier else 1)
        elif key in (Qt.Key_Delete, Qt.Key_Backspace):
            if not self.carry:
                self.delete_tile()
        elif key == Qt.Key_Escape:
            if self.carry:
                self.cancel_carry()
            else:
                self.clear_selection()
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.layer_step.emit(1)
        elif key in (Qt.Key_Minus, Qt.Key_Underscore):
            self.layer_step.emit(-1)
        else:
            super().keyPressEvent(event)
