"""The map space: draws the hex grid and tiles, and handles placing tiles."""

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
)

from ..hexgrid import from_offset, hex_to_pixel, pixel_to_hex, rotate
from ..history import GroupCommand, MoveCommand, PlaceCommand, RemoveCommand
from ..model import PlacedTile
from .drawing import HEX_RADIUS, blend as _blend, hex_polygon, outline_path, paint_details, terrain_colour, text_colour

GRID_FILL = QColor("#f4f1ea")
GRID_LINE = QColor("#d6d0c4")
OVER_LIMIT = QColor("#e01b1b")
SELECTED = QColor("#ffd400")
GHOST_OK = QColor("#1f9d3a")
# Tiles below the current layer are washed towards white: the layer just below a little,
# and each layer further down a little more, up to a limit so the colour still shows.
WHITE_WASH = QColor("#ffffff")
WHITE_WASH_STEP = 0.25
WHITE_WASH_MAX = 0.6

# Scene units are scaled by this at 100% zoom, so a hex is about 22 pixels from centre to corner.
VIEW_SCALE = 1.08
MIN_ZOOM = 75
MAX_ZOOM = 125

# How a tile relates to the layer being worked on.
ACTIVE, BELOW, ABOVE = "active", "below", "above"


class TileItem(QGraphicsItem):
    """A placed tile, or the ghost of a tile being carried."""

    def __init__(self, piece, q, r, rotation, layer, ghost=False):
        super().__init__()
        self.piece = piece
        self.q, self.r, self.rotation = q, r, rotation
        self.cells = cells = piece.cells(q, r, rotation)
        self.layer = layer
        self.numbers = {}  # (q, r) -> layer number to show in that hex
        self.ghost = ghost
        self.over_limit = False
        self.selected = False
        self.blocked = False
        self.state = ACTIVE
        self.wash = 0.0  # how far the fill is washed towards white, 0 to 1
        self.path = outline_path(cells)
        self.polygons = [hex_polygon(q, r) for q, r in cells]
        # Tall pieces sit over the tiles beside them.
        self.setZValue((layer + piece.height - 1) * 10 + (5 if ghost else 0))

    def boundingRect(self):
        return self.path.boundingRect().adjusted(-5, -5, 5, 5)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        fill = terrain_colour(self.piece.terrain, self.layer)
        if self.wash:
            fill = _blend(fill, WHITE_WASH, self.wash)
        if self.ghost:
            fill.setAlpha(150)
        painter.setPen(QPen(QColor(0, 0, 0, 50), 0.8))
        painter.setBrush(fill)
        for polygon in self.polygons:
            painter.drawPolygon(polygon)
        paint_details(painter, self.piece, self.q, self.r, self.rotation, HEX_RADIUS, self.wash, WHITE_WASH)

        if self.ghost:
            outline = QPen(OVER_LIMIT if self.blocked else GHOST_OK, 3, Qt.DashLine)
        elif self.over_limit:
            outline = QPen(OVER_LIMIT, 6)
        elif self.state == BELOW:
            # Edges fade with the wash, so the layer just below keeps clear outlines.
            outline = QPen(_blend(QColor("#1d1d1d"), WHITE_WASH, self.wash), 1.5)
        else:
            outline = QPen(QColor("#1d1d1d"), 1.8)
        painter.setPen(outline)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path)
        if self.selected and not self.ghost:
            # Drawn on top so a tile that is over the inventory keeps its red edge.
            painter.setPen(QPen(SELECTED, 3 if self.over_limit else 4))
            painter.drawPath(self.path)

        if not self.numbers:
            return
        font = QFont()
        font.setPixelSize(int(HEX_RADIUS * 0.75))
        font.setBold(True)
        painter.setFont(font)
        for (q, r), number in self.numbers.items():
            cx, cy = hex_to_pixel(q, r, HEX_RADIUS)
            rect = QRectF(cx - HEX_RADIUS, cy - HEX_RADIUS, HEX_RADIUS * 2, HEX_RADIUS * 2)
            # A dark outline keeps the number readable over tree tops and wall lines.
            path = QPainterPath()
            path.addText(0, 0, font, str(number))
            box = path.boundingRect()
            path.translate(rect.center() - box.center())
            light = text_colour(fill) == QColor("#ffffff")
            painter.setPen(QPen(QColor(0, 0, 0, 170) if light else QColor(255, 255, 255, 170), 2.2))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
            painter.setPen(Qt.NoPen)
            painter.setBrush(text_colour(fill))
            painter.drawPath(path)


class MapView(QGraphicsView):
    changed = Signal()  # the map was edited
    message = Signal(str)  # something to show in the status bar
    layer_step = Signal(int)  # +1 or -1 from the keyboard

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QColor("#3a3f44"))
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setMouseTracking(True)
        self.zoom = 100
        self.set_zoom(100)
        self.active_layer = 1

        # The current layer, in a box that sits over the top-left of the map and doesn't zoom.
        self.layer_badge = QLabel(self)
        self.layer_badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.layer_badge.setAlignment(Qt.AlignCenter)
        self.layer_badge.setStyleSheet(
            "QLabel { background: rgba(255, 255, 255, 230); color: #1d1d1d; border: 2px solid #1d1d1d;"
            " border-radius: 8px; padding: 5px 16px; font-size: 30px; font-weight: bold; }"
        )
        self._update_badge()

        self.model = None
        self.history = None
        self.owned = {}
        self.show_over_limit = True  # the Red Border checkbox
        self.palette_widget = None  # dropping a tile here removes it

        self.tile_items = {}
        self.grid_item = None
        self.ghosts = []
        self.selected = []  # uids of selected tiles; the last one is the one clicked most recently
        self.last_placed = None  # (uid, piece_id, rotation) of the newest tile, for right-click copies
        self.carry = None
        self._press = None  # (uid, viewport pos, hex) of a press on a placed tile

    # --- document -----------------------------------------------------

    def set_document(self, model, history):
        self.model = model
        self.history = history
        self.selected = []
        self.last_placed = None
        self.cancel_carry()
        self.rebuild()

    def rebuild(self):
        """Redraw the grid and tiles, after a new map or a change of map size."""
        self._build_grid()
        self.refresh()

    def set_active_layer(self, layer):
        self.active_layer = layer
        self._update_badge()
        self.refresh()
        self._update_ghost()

    def set_show_over_limit(self, show):
        self.show_over_limit = show
        self.refresh()

    def _update_badge(self):
        self.layer_badge.setText(f"Layer {self.active_layer}")
        self.layer_badge.adjustSize()
        corner = self.viewport().geometry().topLeft()
        self.layer_badge.move(corner.x() + 10, corner.y() + 10)
        self.layer_badge.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_badge()

    def set_owned(self, owned):
        self.owned = owned
        self.refresh()

    def set_zoom(self, percent):
        """Zoom to percent of the normal tile size, keeping the same spot in the middle."""
        percent = max(MIN_ZOOM, min(MAX_ZOOM, int(percent)))
        centre = self.mapToScene(self.viewport().rect().center())
        self.zoom = percent
        scale = VIEW_SCALE * percent / 100
        self.setTransform(QTransform.fromScale(scale, scale))
        self.centerOn(centre)

    def _build_grid(self):
        scene = self.scene()
        scene.clear()
        self.tile_items = {}
        self.ghosts = []
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
        self.selected = [uid for uid in self.selected if uid in self.model.tiles]
        over = self.model.over_limit_uids(self.owned) if self.show_over_limit else set()
        moving = self._moving_uids()
        # Each hex shows the number of the highest layer filled at or below the current one.
        numbers = {}
        for cell, (top, uid) in self.model.top_numbers(self.active_layer).items():
            numbers.setdefault(uid, {})[cell] = top
        for uid, tile in self.model.tiles.items():
            item = TileItem(self.model.piece(tile), tile.q, tile.r, tile.rotation, tile.layer)
            item.numbers = numbers.get(uid, {})
            # Overages only show on the layer being worked on.
            item.over_limit = uid in over and tile.layer == self.active_layer
            item.selected = uid in self.selected
            if tile.layer > self.active_layer:
                item.state = ABOVE
                item.setOpacity(0.25)
            elif tile.layer < self.active_layer:
                item.state = BELOW
                item.wash = min(WHITE_WASH_STEP * (self.active_layer - tile.layer), WHITE_WASH_MAX)
            if uid in moving:
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

    # --- selection ----------------------------------------------------

    @property
    def selected_uid(self):
        """The most recently clicked selected tile, or None."""
        return self.selected[-1] if self.selected else None

    def select(self, uids):
        self.selected = list(uids)
        self.refresh()

    def clear_selection(self):
        self.select([])

    # --- carrying tiles -----------------------------------------------

    def start_carry(self, piece_id, rotation=0, grab=(0, 0), sticky=False):
        """Pick up a new piece from the piece list."""
        self.cancel_carry()
        self.carry = {
            "piece_id": piece_id,
            "rotation": rotation % 6,
            "grab": grab,  # offset from the piece's anchor to the hex under the cursor
            "members": None,
            "sticky": sticky,  # keeps placing copies until cancelled
            "global_pos": None,
        }
        self.viewport().setCursor(Qt.ClosedHandCursor)
        self.setFocus()

    def start_move(self, uids, grab_hex):
        """Pick up placed tiles to move them together, holding them at grab_hex."""
        self.cancel_carry()
        gq, gr = grab_hex
        members = []
        for uid in uids:
            tile = self.model.tiles[uid]
            members.append({"uid": uid, "off": (tile.q - gq, tile.r - gr), "rotation": tile.rotation})
        self.carry = {"piece_id": None, "members": members, "sticky": False, "global_pos": None}
        for uid in uids:
            self.tile_items[uid].setVisible(False)
        self.viewport().setCursor(Qt.ClosedHandCursor)
        self.setFocus()

    def _moving_uids(self):
        if not self.carry or not self.carry["members"]:
            return set()
        return {m["uid"] for m in self.carry["members"]}

    def make_sticky(self):
        if self.carry and self.carry["members"] is None:
            self.carry["sticky"] = True
            self.message.emit("Click on the map to place copies. Right-click or press Esc to stop.")

    def cancel_carry(self):
        if not self.carry:
            return
        moving = self._moving_uids()
        self.carry = None
        for uid in moving:
            if uid in self.tile_items:
                self.tile_items[uid].setVisible(True)
        self._remove_ghosts()
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
        moving = self._moving_uids()
        if self._over_viewport(global_pos):
            self._drop(self.viewport().mapFromGlobal(global_pos))
            if not carry["sticky"]:
                self.cancel_carry()
        elif moving and self._over_palette(global_pos):
            self.cancel_carry()
            self.delete_tiles(moving)
        else:
            self.cancel_carry()

    def _targets(self, viewport_pos):
        """(piece_id, q, r, layer, rotation, uid) for everything carried, dropped at viewport_pos."""
        q, r = self._hex_at(viewport_pos)
        carry = self.carry
        if carry["members"] is None:
            gq, gr = carry["grab"]
            return [(carry["piece_id"], q - gq, r - gr, self.active_layer, carry["rotation"], None)]
        targets = []
        for m in carry["members"]:
            tile = self.model.tiles[m["uid"]]
            oq, orr = m["off"]
            targets.append((tile.piece_id, q + oq, r + orr, tile.layer, m["rotation"], m["uid"]))
        return targets

    def _problem(self, targets):
        ignore = {t[5] for t in targets if t[5] is not None}
        for piece_id, q, r, layer, rotation, _uid in targets:
            problem = self.model.check(piece_id, q, r, layer, rotation, ignore=ignore)
            if problem:
                return problem
        return None

    def _drop(self, viewport_pos):
        targets = self._targets(viewport_pos)
        problem = self._problem(targets)
        if self.carry["members"] is not None:
            if problem:
                self.message.emit(f"Can't move there: {problem}")
                return
            moves = []
            for piece_id, q, r, layer, rotation, uid in targets:
                tile = self.model.tiles[uid]
                if (q, r, rotation) != (tile.q, tile.r, tile.rotation):
                    moves.append(MoveCommand(tile, q, r, rotation))
            if moves:
                self.history.push(self.model, GroupCommand(moves))
                self.selected = [t[5] for t in targets]
                self.changed.emit()
            return
        if problem:
            self.message.emit(f"Can't place there: {problem}")
            return
        piece_id, q, r, _layer, rotation, _uid = targets[0]
        self._place(piece_id, q, r, rotation)

    def _place(self, piece_id, q, r, rotation):
        """Place a new tile on the current layer and leave it selected for rotating."""
        tile = PlacedTile(0, piece_id, q, r, self.active_layer, rotation)
        self.history.push(self.model, PlaceCommand(tile))
        self.selected = [tile.uid]
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
        self._remove_ghosts()
        if not self.carry or self.carry["global_pos"] is None:
            return
        global_pos = self.carry["global_pos"]
        if not self._over_viewport(global_pos):
            return
        targets = self._targets(self.viewport().mapFromGlobal(global_pos))
        blocked = self._problem(targets) is not None
        for piece_id, q, r, layer, rotation, _uid in targets:
            piece = self.model.pieces[piece_id]
            ghost = TileItem(piece, q, r, rotation, layer, ghost=True)
            ghost.blocked = blocked
            self.scene().addItem(ghost)
            self.ghosts.append(ghost)

    def _remove_ghosts(self):
        for ghost in self.ghosts:
            self.scene().removeItem(ghost)
        self.ghosts = []

    # --- editing placed tiles -----------------------------------------

    def rotate(self, steps=1):
        """Turn what is carried, or the selected tiles as one block, by 60 degree steps."""
        if self.carry:
            if self.carry["members"] is None:
                self.carry["rotation"] = (self.carry["rotation"] + steps) % 6
                self.carry["grab"] = rotate(*self.carry["grab"], steps)
            else:
                for m in self.carry["members"]:
                    m["off"] = rotate(*m["off"], steps)
                    m["rotation"] = (m["rotation"] + steps) % 6
            self._update_ghost()
            return
        if not self.selected:
            return
        # Turn around the most recently clicked tile.
        pivot = self.model.tiles[self.selected_uid]
        targets = []
        for uid in self.selected:
            tile = self.model.tiles[uid]
            oq, orr = rotate(tile.q - pivot.q, tile.r - pivot.r, steps)
            targets.append((tile.piece_id, pivot.q + oq, pivot.r + orr, tile.layer, (tile.rotation + steps) % 6, uid))
        problem = self._problem(targets)
        if problem:
            self.message.emit(f"Can't rotate: {problem}")
            return
        moves = [MoveCommand(self.model.tiles[t[5]], t[1], t[2], t[4]) for t in targets]
        self.history.push(self.model, GroupCommand(moves))
        self.changed.emit()

    def delete_tiles(self, uids=None):
        """Remove the given tiles, or the selected ones."""
        uids = list(self.selected if uids is None else uids)
        if not uids:
            return
        if self.model.follow_rules:
            for uid in uids:
                if self.model.supports_others(self.model.tiles[uid], ignore=uids):
                    self.message.emit("Can't remove a piece that other pieces rest on or stand against")
                    self.refresh()
                    return
        removes = [RemoveCommand(self.model.tiles[uid]) for uid in uids]
        self.history.push(self.model, GroupCommand(removes))
        self.selected = [uid for uid in self.selected if uid not in uids]
        self.changed.emit()

    # --- mouse and keyboard -------------------------------------------

    def mousePressEvent(self, event):
        if self.model is None:
            return
        pos = event.position().toPoint()
        if self.carry:
            if event.button() == Qt.LeftButton and self.carry["sticky"]:
                self._drop(pos)
                self._update_ghost()
            elif event.button() == Qt.RightButton:
                self.cancel_carry()
            return
        if event.button() == Qt.RightButton:
            self.place_copy(pos)
            return
        if event.button() != Qt.LeftButton:
            return
        q, r = self._hex_at(pos)
        tile = self.model.tile_at(q, r, self.active_layer)
        if tile is not None and tile.layer != self.active_layer:
            tile = None  # tall pieces are picked on the layer they stand on
        self._press = None
        if event.modifiers() & Qt.ControlModifier:
            # Ctrl+click adds a tile to the selection, or takes it out.
            if tile:
                if tile.uid in self.selected:
                    self.selected.remove(tile.uid)
                else:
                    self.selected.append(tile.uid)
                    self._press = (tile.uid, pos, (q, r))
            self.refresh()
            return
        if tile is None:
            self.clear_selection()
            return
        if tile.uid in self.selected:
            # Keep a multi-selection so it can be dragged as one block.
            self.selected.remove(tile.uid)
            self.selected.append(tile.uid)
        else:
            self.selected = [tile.uid]
        self._press = (tile.uid, pos, (q, r))
        self.refresh()

    def mouseMoveEvent(self, event):
        global_pos = event.globalPosition().toPoint()
        if self.carry:
            self.carry_move(global_pos)
            return
        if self._press and event.buttons() & Qt.LeftButton:
            _uid, start, grab_hex = self._press
            distance = (event.position().toPoint() - start).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self._press = None
                self.start_move(list(self.selected), grab_hex)
                self.carry_move(global_pos)

    def mouseReleaseEvent(self, event):
        if self._press and event.button() == Qt.LeftButton and not event.modifiers() & Qt.ControlModifier:
            # A plain click without dragging selects just that tile.
            uid = self._press[0]
            if self.selected != [uid]:
                self.select([uid])
        self._press = None
        if self.carry and not self.carry["sticky"] and event.button() == Qt.LeftButton:
            self.carry_release(event.globalPosition().toPoint())

    def wheelEvent(self, event):
        """The wheel scrolls up and down; Ctrl+wheel (or a sideways wheel) scrolls left and right."""
        dx, dy = event.angleDelta().x(), event.angleDelta().y()
        if event.modifiers() & Qt.ControlModifier:
            dx, dy = dx or dy, 0
        bar_h, bar_v = self.horizontalScrollBar(), self.verticalScrollBar()
        bar_h.setValue(bar_h.value() - dx)
        bar_v.setValue(bar_v.value() - dy)
        if self.carry:
            self._update_ghost()
        event.accept()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self.carry and self.carry["sticky"]:
            self._remove_ghosts()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_R:
            self.rotate(-1 if event.modifiers() & Qt.ShiftModifier else 1)
        elif key in (Qt.Key_Delete, Qt.Key_Backspace):
            if not self.carry:
                self.delete_tiles()
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
