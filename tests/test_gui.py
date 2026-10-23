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
    view.ensureVisible(x - 1, y - 1, 2, 2, 60, 60)
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


def test_placed_tile_stays_selected_for_rotating(window):
    w = window
    drag_from_palette(w, "rotv.grass.3", 10, 10)
    uid = next(iter(w.model.tiles))
    assert w.map_view.selected_uid == uid
    QTest.keyClick(w.map_view, Qt.Key_R)
    assert w.model.tiles[uid].rotation == 1


def test_right_click_places_copy_of_last_tile(window):
    w = window
    view = w.map_view
    drag_from_palette(w, "rotv.water.1", 5, 5)
    QTest.keyClick(view, Qt.Key_R)
    for col in (7, 9, 11):
        pos = view.viewport().mapFromGlobal(hex_global(w, col, 5))
        QTest.mouseClick(view.viewport(), Qt.RightButton, Qt.NoModifier, pos)
    tiles = list(w.model.tiles.values())
    assert [t.piece_id for t in tiles] == ["rotv.water.1"] * 4
    assert all(t.rotation == 1 for t in tiles)
    assert view.selected_uid == tiles[-1].uid
    assert "Used 4" in w.palette.rows["rotv.water.1"].counts_label.text()


def test_right_click_with_nothing_placed_does_nothing(window):
    view = window.map_view
    pos = view.viewport().mapFromGlobal(hex_global(window, 5, 5))
    QTest.mouseClick(view.viewport(), Qt.RightButton, Qt.NoModifier, pos)
    assert not window.model.tiles


def test_other_layers_are_tinted(window):
    from heroscape_builder.gui.map_view import ABOVE, ACTIVE, BELOW

    w = window
    w.rules_box.setChecked(False)
    drag_from_palette(w, "rotv.grass.1", 5, 5)
    w.step_layer(1)
    drag_from_palette(w, "rotv.grass.1", 8, 5)
    w.step_layer(1)
    drag_from_palette(w, "rotv.grass.1", 11, 5)
    w.step_layer(-1)
    states = sorted(item.state for item in w.map_view.tile_items.values())
    assert states == sorted([BELOW, ACTIVE, ABOVE])


def test_size_drop_down_changes_map(window):
    w = window
    drag_from_palette(w, "rotv.grass.1", 5, 5)
    w.size_box.setCurrentIndex(w.size_box.findData("large"))
    assert w.model.size_name == "large"
    assert len(w.model.tiles) == 1
    assert w.is_dirty()


def test_size_drop_down_refuses_to_cut_off_tiles(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    w = window
    w.size_box.setCurrentIndex(w.size_box.findData("large"))
    w.rules_box.setChecked(False)
    drag_from_palette(w, "rotv.grass.1", 70, 70)
    assert len(w.model.tiles) == 1
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    w.size_box.setCurrentIndex(w.size_box.findData("small"))
    assert w.model.size_name == "large"
    assert w.size_box.currentData() == "large"


def test_new_map_uses_chosen_size(window):
    w = window
    w.size_box.setCurrentIndex(w.size_box.findData("large"))
    w.new_map(ask=False)
    assert w.model.size_name == "large"
    assert not w.model.tiles


def _vp(w, col, row):
    return w.map_view.viewport().mapFromGlobal(hex_global(w, col, row))


def test_ctrl_click_moves_tiles_as_one_block(window):
    w = window
    view = w.map_view
    drag_from_palette(w, "rotv.grass.1", 10, 10)
    drag_from_palette(w, "rotv.rock.2", 12, 10)
    drag_from_palette(w, "rotv.sand.1", 15, 10)  # not selected
    a, b, c = list(w.model.tiles)
    QTest.keyClick(view, Qt.Key_Escape)  # the last tile placed starts selected
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.ControlModifier, _vp(w, 10, 10))
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.ControlModifier, _vp(w, 12, 10))
    assert sorted(view.selected) == sorted([a, b])
    before = {uid: (t.q, t.r) for uid, t in w.model.tiles.items()}
    start = _vp(w, 10, 10)
    end = _vp(w, 10, 14)
    QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(view.viewport(), start + QPoint(20, 0))
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, end)
    after = {uid: (t.q, t.r) for uid, t in w.model.tiles.items()}
    shift = (after[a][0] - before[a][0], after[a][1] - before[a][1])
    assert shift != (0, 0)
    assert (after[b][0] - before[b][0], after[b][1] - before[b][1]) == shift
    assert after[c] == before[c]
    w.undo()  # one undo step puts both back
    assert {uid: (t.q, t.r) for uid, t in w.model.tiles.items()} == before


def test_plain_click_after_multi_select_selects_one(window):
    w = window
    view = w.map_view
    drag_from_palette(w, "rotv.grass.1", 10, 10)
    drag_from_palette(w, "rotv.grass.1", 12, 10)
    a, b = list(w.model.tiles)
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.ControlModifier, _vp(w, 10, 10))
    assert sorted(view.selected) == sorted([a, b])  # b was selected from being placed
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, _vp(w, 10, 10))
    assert view.selected == [a]


def test_delete_and_rotate_several(window):
    w = window
    view = w.map_view
    drag_from_palette(w, "rotv.grass.1", 10, 10)
    drag_from_palette(w, "rotv.grass.1", 11, 10)
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.ControlModifier, _vp(w, 10, 10))
    QTest.keyClick(view, Qt.Key_R)
    assert len(w.model.tiles) == 2
    QTest.keyClick(view, Qt.Key_Delete)
    assert not w.model.tiles
    w.undo()
    assert len(w.model.tiles) == 2


def test_wheel_scrolls_instead_of_rotating(window):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent

    w = window
    view = w.map_view
    drag_from_palette(w, "rotv.grass.3", 15, 15)
    uid = next(iter(w.model.tiles))

    def wheel(dy, modifiers=Qt.NoModifier):
        pos = QPointF(view.viewport().rect().center())
        event = QWheelEvent(pos, QPointF(view.viewport().mapToGlobal(pos.toPoint())), QPoint(0, 0),
                            QPoint(0, dy), Qt.NoButton, modifiers, Qt.NoScrollPhase, False)
        QApplication.sendEvent(view.viewport(), event)

    v, h = view.verticalScrollBar(), view.horizontalScrollBar()
    v.setValue(v.maximum() // 2)
    h.setValue(h.maximum() // 2)
    v0, h0 = v.value(), h.value()
    wheel(-120)
    assert v.value() > v0 and h.value() == h0
    wheel(-120, Qt.ControlModifier)
    assert h.value() > h0
    assert w.model.tiles[uid].rotation == 0


def test_zoom_slider(window):
    w = window
    w.zoom_slider.setValue(150)
    assert w.map_view.zoom == 150
    assert abs(w.map_view.transform().m11() - 1.08 * 1.5) < 1e-6
    w.zoom_slider.setValue(10)  # clamped by the slider
    assert w.map_view.zoom == 50


def test_over_limit_outline_stays_when_not_selected(window):
    w = window
    for col in (4, 10, 16):
        drag_from_palette(w, "rotv.sand.7", col, 4)
    w.map_view.clear_selection()
    over = [item for item in w.map_view.tile_items.values() if item.over_limit]
    assert len(over) == 1 and not over[0].selected
