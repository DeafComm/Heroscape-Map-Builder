"""The main window: piece list, map space, layer selector and menus."""

import json
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..fileio import FILE_SUFFIX, MapFileError, load_map, save_map
from ..hexgrid import MAP_SIZES
from ..history import UNDO_LIMIT, History
from ..inventory import Inventory
from ..model import MAX_LAYER, MIN_LAYER, MapModel
from ..pieces import load_pieces, load_sets
from .armies import ArmyPanel
from .inventory_dialog import InventoryDialog
from .map_view import MAX_ZOOM, MIN_ZOOM, MapView
from .palette import Palette

DEFAULT_SIZE = "medium"
SIZE_LABELS = {name: f"{name.title()} ({n} × {n})" for name, n in MAP_SIZES.items()}


class MainWindow(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings or QSettings("HeroscapeMapBuilder", "HeroscapeMapBuilder")
        self.pieces = load_pieces()
        self.sets, _ = load_sets()
        self.inventory = self._load_inventory()
        self.path = None
        self.options_dirty = False  # changes that aren't undoable, like the rules checkbox
        self._press_start = None

        self.palette = Palette(self.pieces)
        self.map_view = MapView()
        self.map_view.palette_widget = self.palette
        for row in self.palette.all_rows():
            row.pressed.connect(self._palette_pressed)
            row.dragged.connect(self.map_view.carry_move)
            row.released.connect(self._palette_released)
        self.map_view.changed.connect(self._map_changed)
        self.map_view.message.connect(lambda text: self.statusBar().showMessage(text, 5000))
        self.map_view.layer_step.connect(self.step_layer)

        inventory_button = QPushButton("Inventory…")
        inventory_button.clicked.connect(self.edit_inventory)
        left = QVBoxLayout()
        left.addWidget(inventory_button)
        left.addWidget(self.palette, 1)

        self.layer_down = QPushButton("−")
        self.layer_up = QPushButton("+")
        for button in (self.layer_down, self.layer_up):
            button.setFixedWidth(36)
            button.setFocusPolicy(Qt.NoFocus)
        self.layer_down.setToolTip("Down one layer (-)")
        self.layer_up.setToolTip("Up one layer (+)")
        self.layer_down.clicked.connect(lambda: self.step_layer(-1))
        self.layer_up.clicked.connect(lambda: self.step_layer(1))
        self.layer_label = QLabel()
        self.layer_label.setMinimumWidth(110)
        self.layer_label.setAlignment(Qt.AlignCenter)
        self.rules_box = QCheckBox("Follow game rules")
        self.rules_box.setFocusPolicy(Qt.NoFocus)
        self.rules_box.toggled.connect(self._rules_toggled)
        self.red_border_box = QCheckBox("Red Border")
        self.red_border_box.setFocusPolicy(Qt.NoFocus)
        self.red_border_box.setToolTip("Outline tiles placed beyond what you own in red")
        self.red_border_box.setChecked(self.settings.value("red_border", "true") != "false")
        self.map_view.set_show_over_limit(self.red_border_box.isChecked())
        self.red_border_box.toggled.connect(self._red_border_toggled)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(MIN_ZOOM, MAX_ZOOM)
        self.zoom_slider.setSingleStep(5)
        self.zoom_slider.setPageStep(10)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(140)
        self.zoom_slider.setFocusPolicy(Qt.NoFocus)
        self.zoom_slider.valueChanged.connect(self._zoom_changed)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(40)
        self.size_box = QComboBox()
        self.size_box.setFocusPolicy(Qt.NoFocus)
        for name in MAP_SIZES:
            self.size_box.addItem(SIZE_LABELS[name], name)
        self.size_box.currentIndexChanged.connect(self._size_chosen)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Layer:"))
        bottom.addWidget(self.layer_down)
        bottom.addWidget(self.layer_label)
        bottom.addWidget(self.layer_up)
        bottom.addSpacing(24)
        bottom.addWidget(self.rules_box)
        bottom.addSpacing(12)
        bottom.addWidget(self.red_border_box)
        bottom.addStretch(1)
        bottom.addWidget(QLabel("Zoom:"))
        bottom.addWidget(self.zoom_slider)
        bottom.addWidget(self.zoom_label)
        bottom.addSpacing(16)
        bottom.addWidget(QLabel("Map size:"))
        bottom.addWidget(self.size_box)

        right = QVBoxLayout()
        right.addWidget(self.map_view, 1)
        right.addLayout(bottom)

        self.armies = ArmyPanel(self.sets)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addLayout(left)
        layout.addLayout(right, 1)
        layout.addWidget(self.armies)
        self.setCentralWidget(central)
        self._build_menus()

        self.resize(1440, 900)
        self.new_map(DEFAULT_SIZE, ask=False)

    # --- menus --------------------------------------------------------

    def _build_menus(self):
        file_menu = self.menuBar().addMenu("&File")
        self._add_action(file_menu, "&New", QKeySequence.New, lambda: self.new_map())
        self._add_action(file_menu, "&Open…", QKeySequence.Open, self.open_map)
        self._add_action(file_menu, "&Save", QKeySequence.Save, self.save)
        self._add_action(file_menu, "Save &As…", QKeySequence("Ctrl+Shift+S"), self.save_as)
        file_menu.addSeparator()
        self._add_action(file_menu, "&Quit", QKeySequence.Quit, self.close)

        edit_menu = self.menuBar().addMenu("&Edit")
        self.undo_action = self._add_action(edit_menu, "&Undo", QKeySequence("Ctrl+Z"), self.undo)
        self.redo_action = self._add_action(edit_menu, "&Redo", None, self.redo)
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        edit_menu.addSeparator()
        rotate = self._add_action(edit_menu, "Rotate tile", None, lambda: self.map_view.rotate(1))
        rotate.setText("Rotate tile\tR")
        delete = self._add_action(edit_menu, "Remove tile", None, lambda: self.map_view.delete_tiles())
        delete.setText("Remove tile\tDel")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "&Inventory…", QKeySequence("Ctrl+I"), self.edit_inventory)

        help_menu = self.menuBar().addMenu("&Help")
        self._add_action(help_menu, "&Controls", None, self.show_controls)

    def _add_action(self, menu, text, shortcut, slot):
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # --- state --------------------------------------------------------

    def _load_inventory(self):
        raw = self.settings.value("inventory")
        if not raw:
            return Inventory()
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return Inventory()
        return Inventory.from_dict(data, {s.id for s in self.sets})

    def _set_document(self, model, history, path):
        self.model = model
        self.history = history
        self.path = path
        self.options_dirty = False
        self.rules_box.blockSignals(True)
        self.rules_box.setChecked(model.follow_rules)
        self.rules_box.blockSignals(False)
        self._show_size(model.size_name)
        self.map_view.owned = self.inventory.owned_counts(self.pieces)
        self.map_view.set_document(model, history)
        self.set_layer(MIN_LAYER)
        self._map_changed()

    def _map_changed(self):
        self.map_view.refresh()
        self.palette.set_counts(self.inventory.owned_counts(self.pieces), self.model.used_counts())
        self.undo_action.setEnabled(self.history.can_undo())
        self.redo_action.setEnabled(self.history.can_redo())
        self._update_title()

    def _update_title(self):
        name = Path(self.path).name if self.path else "Untitled"
        star = "*" if self.is_dirty() else ""
        self.setWindowTitle(f"{name}{star} — Heroscape Map Builder")

    def is_dirty(self):
        return self.history.dirty or self.options_dirty

    def set_layer(self, layer):
        layer = max(MIN_LAYER, min(MAX_LAYER, layer))
        self.layer = layer
        self.layer_label.setText(f"<b>{layer}</b> of {MAX_LAYER}")
        self.layer_down.setEnabled(layer > MIN_LAYER)
        self.layer_up.setEnabled(layer < MAX_LAYER)
        self.map_view.selected = []
        self.map_view.set_active_layer(layer)

    def step_layer(self, step):
        self.set_layer(self.layer + step)

    def keyPressEvent(self, event):
        # The map handles these itself when it has focus.
        if event.key() in (Qt.Key_Plus, Qt.Key_Equal):
            self.step_layer(1)
        elif event.key() in (Qt.Key_Minus, Qt.Key_Underscore):
            self.step_layer(-1)
        else:
            super().keyPressEvent(event)

    def _rules_toggled(self, checked):
        self.model.follow_rules = checked
        self.options_dirty = True
        self._update_title()
        self.map_view.setFocus()

    def _red_border_toggled(self, checked):
        self.map_view.set_show_over_limit(checked)
        self.settings.setValue("red_border", "true" if checked else "false")
        self.map_view.setFocus()

    # --- placing from the piece list ----------------------------------

    def _palette_pressed(self, piece_id, global_pos):
        self._press_start = QPoint(global_pos)
        self.map_view.start_carry(piece_id)
        self.map_view.carry_move(global_pos)

    def _palette_released(self, global_pos):
        start, self._press_start = self._press_start, None
        moved = start is not None and (global_pos - start).manhattanLength() >= QApplication.startDragDistance()
        if not moved and not self.map_view._over_viewport(global_pos):
            # A click: keep the piece and place copies with each click on the map.
            self.map_view.make_sticky()
        else:
            self.map_view.carry_release(global_pos)

    # --- commands -----------------------------------------------------

    def undo(self):
        self.map_view.cancel_carry()
        self.history.undo(self.model)
        self.map_view.selected = []
        self._map_changed()

    def redo(self):
        self.map_view.cancel_carry()
        self.history.redo(self.model)
        self.map_view.selected = []
        self._map_changed()

    def edit_inventory(self):
        dialog = InventoryDialog(self.sets, self.inventory, self)
        if dialog.exec():
            self.inventory = dialog.inventory()
            self.settings.setValue("inventory", json.dumps(self.inventory.to_dict()))
            self.settings.sync()
            self.map_view.owned = self.inventory.owned_counts(self.pieces)
            self._map_changed()

    def new_map(self, size_name=None, ask=True):
        """Start an empty map, at the size picked under the map unless one is given."""
        if ask and not self.maybe_save():
            return
        if size_name not in MAP_SIZES:
            size_name = self.size_box.currentData() or DEFAULT_SIZE
        self._set_document(MapModel(self.pieces, size_name), History(UNDO_LIMIT), None)

    def _show_size(self, size_name):
        self.size_box.blockSignals(True)
        self.size_box.setCurrentIndex(self.size_box.findData(size_name))
        self.size_box.blockSignals(False)

    def _zoom_changed(self, percent):
        self.map_view.set_zoom(percent)
        self.zoom_label.setText(f"{percent}%")

    def _size_chosen(self, _index):
        size_name = self.size_box.currentData()
        if size_name == self.model.size_name:
            return
        if not self.model.fits(size_name):
            QMessageBox.warning(
                self,
                "Map too big",
                f"Some tiles would be off the edge of a {SIZE_LABELS[size_name]} map. "
                "Move or remove them first.",
            )
            self._show_size(self.model.size_name)
            return
        self.map_view.cancel_carry()
        self.model.size_name = size_name
        self.options_dirty = True
        self.map_view.rebuild()
        self._update_title()

    def open_map(self):
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open map", self._last_dir(), f"Heroscape maps (*{FILE_SUFFIX});;JSON files (*.json);;All files (*)"
        )
        if path:
            self.load(path)

    def load(self, path):
        try:
            model, _name = load_map(path, self.pieces)
        except MapFileError as e:
            QMessageBox.warning(self, "Couldn't open map", str(e))
            return False
        self.settings.setValue("last_dir", str(Path(path).parent))
        self._set_document(model, History(UNDO_LIMIT), path)
        return True

    def save(self):
        if not self.path:
            return self.save_as()
        return self._write(self.path)

    def save_as(self):
        start = self.path or str(Path(self._last_dir()) / f"untitled{FILE_SUFFIX}")
        path, _ = QFileDialog.getSaveFileName(self, "Save map", start, f"Heroscape maps (*{FILE_SUFFIX})")
        if not path:
            return False
        if not path.endswith(".json"):
            path += FILE_SUFFIX
        return self._write(path)

    def _write(self, path):
        try:
            save_map(path, self.model)
        except OSError as e:
            QMessageBox.warning(self, "Couldn't save map", str(e))
            return False
        self.path = path
        self.settings.setValue("last_dir", str(Path(path).parent))
        self.history.mark_saved()
        self.options_dirty = False
        self._update_title()
        self.statusBar().showMessage(f"Saved {path}", 5000)
        return True

    def _last_dir(self):
        return self.settings.value("last_dir") or str(Path.home())

    def maybe_save(self):
        """Ask about unsaved changes. Returns False if the user cancels."""
        if not self.is_dirty():
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            "This map has unsaved changes. Save them first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if answer == QMessageBox.Save:
            return self.save()
        return answer == QMessageBox.Discard

    def closeEvent(self, event):
        if self.maybe_save():
            event.accept()
        else:
            event.ignore()

    def show_controls(self):
        QMessageBox.information(
            self,
            "Controls",
            "<b>Place:</b> drag a piece from the left onto the map. Or click a piece, then click on the map "
            "to place copies; right-click or Esc stops.<br>"
            "<b>Place another:</b> right-click on the map to place another of the last tile you placed.<br>"
            "<b>Rotate:</b> R (Shift+R the other way), while carrying a piece or with tiles selected. "
            "A tile you just placed stays selected.<br>"
            "<b>Select several:</b> Ctrl+click tiles on the current layer, then drag them as one block.<br>"
            "<b>Scroll:</b> mouse wheel up and down, Ctrl+wheel left and right. Zoom (75% to 125%) with the "
            "slider under the map.<br>"
            "<b>Piece lists:</b> pick Terrain, Castle or Trees/Ruins in the drop-down above each list.<br>"
            "<b>Move:</b> drag a tile (or the selected tiles) on the current layer.<br>"
            "<b>Remove:</b> select tiles and press Delete, or drag them back to the piece list.<br>"
            "<b>Layers:</b> + goes up a layer, - goes down. New tiles go on the current layer. Tiles on "
            "lower layers get a white wash that gets stronger the further down they are, and tiles on higher "
            "layers fade. Each hex shows the number of the highest layer filled at or below the current "
            "layer, which is also shown in the top-left corner of the map.<br>"
            "<b>Tall pieces:</b> trees, castle walls, the doorway and ladders fill several layers. Place them "
            "on the layer above the tile they stand on; their hexes show their top layer. Wall walks go on "
            "the layer above a wall's top.<br>"
            "<b>Red Border:</b> turns the red outline on tiles beyond what you own on or off. It only shows "
            "on the current layer.<br>"
            "<b>Undo / redo:</b> Ctrl+Z / Ctrl+Y (last 20 actions).",
        )
