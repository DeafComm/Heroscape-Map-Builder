"""Drives the main window with simulated mouse and keyboard input."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtCore = pytest.importorskip("PySide6.QtCore")
from PySide6.QtCore import QPoint, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from heroscape_builder.gui.drawing import HEX_RADIUS  # noqa: E402
from heroscape_builder.gui.main_window import MainWindow  # noqa: E402
from heroscape_builder.hexgrid import from_offset, hex_to_pixel  # noqa: E402


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    w = MainWindow(settings)
    w.new_map("small", ask=False)
    w.show()
    QTest.qWaitForWindowExposed(w)
    yield w
    w.history.mark_saved()
    w.options_dirty = False
    w.close()
    app.processEvents()


def hex_global(w, col, row):
    view = w.map_view
    x, y = hex_to_pixel(*from_offset(col, row), HEX_RADIUS)
    return view.viewport().mapToGlobal(view.mapFromScene(x, y))


def drag_from_palette(w, piece_id, col, row, rotations=0):
    palette_row = w.palette.rows[piece_id]
    start = palette_row.mapToGlobal(palette_row.rect().center())
    w._palette_pressed(piece_id, start)
    for _ in range(rotations):
        w.map_view.rotate(1)
    target = hex_global(w, col, row)
    w.map_view.carry_move(target)
    w._palette_released(target)


def test_place_rotate_undo(window):
    w = window
    drag_from_palette(w, "rotv.grass.7", 10, 10)
    assert len(w.model.tiles) == 1
    tile = next(iter(w.model.tiles.values()))
    assert (tile.layer, tile.q, tile.r) == (1, *from_offset(10, 10))
    assert "Used 1" in w.palette.rows["rotv.grass.7"].counts_label.text()
    assert w.windowTitle().startswith("Untitled*")
    w.undo()
    assert not w.model.tiles
    w.redo()
    assert len(w.model.tiles) == 1


def test_layer_keys_and_limits(window):
    w = window
    w.map_view.setFocus()
    QTest.keyClick(w.map_view, Qt.Key_Minus)
    assert w.layer == 1
    for _ in range(20):
        QTest.keyClick(w.map_view, Qt.Key_Plus)
    assert w.layer == 15
    QTest.keyClick(w.map_view, Qt.Key_Minus)
    assert w.layer == 14


def test_tiles_go_on_selected_layer_only(window):
    w = window
    drag_from_palette(w, "rotv.grass.7", 10, 10)
    drag_from_palette(w, "rotv.rock.1", 10, 10)  # same layer, blocked
    assert len(w.model.tiles) == 1
    w.step_layer(1)
    drag_from_palette(w, "rotv.rock.1", 10, 10)
    assert sorted(t.layer for t in w.model.tiles.values()) == [1, 2]
    w.step_layer(1)
    drag_from_palette(w, "rotv.sand.3", 20, 20)  # no support on layer 3
    assert len(w.model.tiles) == 2
    w.rules_box.setChecked(False)
    drag_from_palette(w, "rotv.sand.3", 20, 20)
    assert len(w.model.tiles) == 3


def test_click_then_place_copies(window):
    w = window
    palette_row = w.palette.rows["rotv.water.1"]
    QTest.mouseClick(palette_row, Qt.LeftButton)
    assert w.map_view.carry and w.map_view.carry["sticky"]
    view = w.map_view
    for col in (3, 5, 7):
        pos = view.viewport().mapFromGlobal(hex_global(w, col, 3))
        QTest.mouseMove(view.viewport(), pos)
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
    assert len(w.model.tiles) == 3
    QTest.keyClick(view, Qt.Key_Escape)
    assert view.carry is None


def test_move_select_delete(window):
    w = window
    view = w.map_view
    drag_from_palette(w, "rotv.rock.3", 10, 10)
    uid = next(iter(w.model.tiles))
    start = view.viewport().mapFromGlobal(hex_global(w, 10, 10))
    end = view.viewport().mapFromGlobal(hex_global(w, 15, 12))
    QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(view.viewport(), start + QPoint(20, 0))
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, end)
    tile = w.model.tiles[uid]
    assert (tile.q, tile.r) == from_offset(15, 12)
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, end)
    assert view.selected_uid == uid
    QTest.keyClick(view, Qt.Key_R)
    assert w.model.tiles[uid].rotation == 1
    QTest.keyClick(view, Qt.Key_Delete)
    assert not w.model.tiles


def test_over_inventory_goes_negative(window):
    w = window
    drag_from_palette(w, "rotv.sand.7", 4, 4)
    drag_from_palette(w, "rotv.sand.7", 10, 4)
    drag_from_palette(w, "rotv.sand.7", 16, 4)
    assert len(w.model.tiles) == 3
    assert "-1" in w.palette.rows["rotv.sand.7"].counts_label.text()
    over = [item for item in w.map_view.tile_items.values() if item.over_limit]
    assert len(over) == 1


def test_save_and_reload(window, tmp_path):
    w = window
    drag_from_palette(w, "rotv.grass.24", 12, 12, rotations=1)
    path = str(tmp_path / "test.hsmap.json")
    assert w._write(path)
    assert not w.is_dirty()
    assert w.load(path)
    assert len(w.model.tiles) == 1
    assert next(iter(w.model.tiles.values())).rotation == 1


def test_inventory_saved_in_settings(window, tmp_path):
    from heroscape_builder.inventory import Inventory

    w = window
    w.inventory = Inventory({"rotv": 2})
    import json

    w.settings.setValue("inventory", json.dumps(w.inventory.to_dict()))
    w.settings.sync()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    w2 = MainWindow(settings)
    assert w2.inventory.copies == {"rotv": 2}
    w2.close()


def test_inventory_dialog_lists_sets(window):
    from heroscape_builder.gui.inventory_dialog import InventoryDialog

    dialog = InventoryDialog(window.sets, window.inventory, window)
    box, copies = dialog.rows["rotv"]
    assert box.isChecked() and box.isEnabled()
    assert not dialog.rows["rttf"][0].isEnabled()
    copies.setValue(3)
    assert dialog.inventory().copies == {"rotv": 3}


def test_large_map_builds(window):
    window.new_map("large", ask=False)
    assert window.model.size == 80
