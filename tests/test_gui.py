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
from heroscape_builder.model import PlacedTile  # noqa: E402


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    w = MainWindow(settings)
    w.new_map("medium", ask=False)
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
    drag_from_palette(w, "grass.7", 10, 10)
    assert len(w.model.tiles) == 1
    tile = next(iter(w.model.tiles.values()))
    assert (tile.layer, tile.q, tile.r) == (1, *from_offset(10, 10))
    assert "Used 1" in w.palette.rows["grass.7"].counts_label.text()
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
    for _ in range(25):
        QTest.keyClick(w.map_view, Qt.Key_Plus)
    assert w.layer == 20
    QTest.keyClick(w.map_view, Qt.Key_Minus)
    assert w.layer == 19


def test_tiles_go_on_selected_layer_only(window):
    w = window
    drag_from_palette(w, "grass.7", 10, 10)
    drag_from_palette(w, "rock.1", 10, 10)  # same layer, blocked
    assert len(w.model.tiles) == 1
    w.step_layer(1)
    drag_from_palette(w, "rock.1", 10, 10)
    assert sorted(t.layer for t in w.model.tiles.values()) == [1, 2]
    w.step_layer(1)
    drag_from_palette(w, "sand.3", 20, 20)  # no support on layer 3
    assert len(w.model.tiles) == 2
    w.rules_box.setChecked(False)
    drag_from_palette(w, "sand.3", 20, 20)
    assert len(w.model.tiles) == 3


def test_click_then_place_copies(window):
    w = window
    palette_row = w.palette.rows["water.1"]
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
    drag_from_palette(w, "rock.3", 10, 10)
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
    drag_from_palette(w, "sand.7", 4, 4)
    drag_from_palette(w, "sand.7", 10, 4)
    drag_from_palette(w, "sand.7", 16, 4)
    assert len(w.model.tiles) == 3
    assert "-1" in w.palette.rows["sand.7"].counts_label.text()
    over = [item for item in w.map_view.tile_items.values() if item.over_limit]
    assert len(over) == 1


def test_save_and_reload(window, tmp_path):
    w = window
    drag_from_palette(w, "grass.24", 12, 12, rotations=1)
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
    assert not dialog.rows["volcarren"][0].isEnabled()
    for set_id in ("forest", "marro", "archkyrie"):
        assert dialog.rows[set_id][0].isEnabled() and not dialog.rows[set_id][0].isChecked()
    copies.setValue(3)
    assert dialog.inventory().copies == {"rotv": 3}


def test_large_map_builds(window):
    window.new_map("large", ask=False)
    assert window.model.size == 50


def test_placed_tile_stays_selected_for_rotating(window):
    w = window
    drag_from_palette(w, "grass.3", 10, 10)
    uid = next(iter(w.model.tiles))
    assert w.map_view.selected_uid == uid
    QTest.keyClick(w.map_view, Qt.Key_R)
    assert w.model.tiles[uid].rotation == 1


def test_right_click_places_copy_of_last_tile(window):
    w = window
    view = w.map_view
    drag_from_palette(w, "water.1", 5, 5)
    QTest.keyClick(view, Qt.Key_R)
    for col in (7, 9, 11):
        pos = view.viewport().mapFromGlobal(hex_global(w, col, 5))
        QTest.mouseClick(view.viewport(), Qt.RightButton, Qt.NoModifier, pos)
    tiles = list(w.model.tiles.values())
    assert [t.piece_id for t in tiles] == ["water.1"] * 4
    assert all(t.rotation == 1 for t in tiles)
    assert view.selected_uid == tiles[-1].uid
    assert "Used 4" in w.palette.rows["water.1"].counts_label.text()


def test_right_click_with_nothing_placed_does_nothing(window):
    view = window.map_view
    pos = view.viewport().mapFromGlobal(hex_global(window, 5, 5))
    QTest.mouseClick(view.viewport(), Qt.RightButton, Qt.NoModifier, pos)
    assert not window.model.tiles


def test_other_layers_are_tinted(window):
    from heroscape_builder.gui.map_view import ABOVE, ACTIVE, BELOW

    w = window
    w.rules_box.setChecked(False)
    drag_from_palette(w, "grass.1", 5, 5)
    w.step_layer(1)
    drag_from_palette(w, "grass.1", 8, 5)
    w.step_layer(1)
    drag_from_palette(w, "grass.1", 11, 5)
    w.step_layer(-1)
    states = sorted(item.state for item in w.map_view.tile_items.values())
    assert states == sorted([BELOW, ACTIVE, ABOVE])


def test_size_drop_down_changes_map(window):
    w = window
    drag_from_palette(w, "grass.1", 5, 5)
    w.size_box.setCurrentIndex(w.size_box.findData("large"))
    assert w.model.size_name == "large"
    assert len(w.model.tiles) == 1
    assert w.is_dirty()


def test_size_drop_down_refuses_to_cut_off_tiles(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    w = window
    w.size_box.setCurrentIndex(w.size_box.findData("large"))
    w.rules_box.setChecked(False)
    drag_from_palette(w, "grass.1", 40, 40)
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
    drag_from_palette(w, "grass.1", 10, 10)
    drag_from_palette(w, "rock.2", 12, 10)
    drag_from_palette(w, "sand.1", 15, 10)  # not selected
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
    drag_from_palette(w, "grass.1", 10, 10)
    drag_from_palette(w, "grass.1", 12, 10)
    a, b = list(w.model.tiles)
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.ControlModifier, _vp(w, 10, 10))
    assert sorted(view.selected) == sorted([a, b])  # b was selected from being placed
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, _vp(w, 10, 10))
    assert view.selected == [a]


def test_delete_and_rotate_several(window):
    w = window
    view = w.map_view
    drag_from_palette(w, "grass.1", 10, 10)
    drag_from_palette(w, "grass.1", 11, 10)
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
    drag_from_palette(w, "grass.3", 15, 15)
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
    w.zoom_slider.setValue(125)
    assert w.map_view.zoom == 125
    assert abs(w.map_view.transform().m11() - 1.08 * 1.25) < 1e-6
    w.zoom_slider.setValue(10)  # clamped by the slider
    assert w.map_view.zoom == 75


def test_over_limit_outline_stays_when_not_selected(window):
    w = window
    for col in (4, 10, 16):
        drag_from_palette(w, "sand.7", col, 4)
    w.map_view.clear_selection()
    over = [item for item in w.map_view.tile_items.values() if item.over_limit]
    assert len(over) == 1 and not over[0].selected


def test_two_piece_lists_with_drop_downs(window):
    w = window
    top, bottom = w.palette.lists
    assert top.category == "terrain" and bottom.category == "trees_ruins"
    assert top.rows["grass.7"].isVisible() and not top.rows["ruin.3"].isVisible()
    assert bottom.rows["ruin.3"].isVisible() and not bottom.rows["grass.7"].isVisible()
    assert bottom.rows["tree.15"].isVisible() and bottom.rows["stone_wall"].isVisible()
    assert top.rows["swamp_water.1"].isVisible() and not top.rows["road.5"].isVisible()
    bottom.choice.setCurrentIndex(bottom.choice.findData("castle"))
    assert bottom.rows["castle_wall.corner"].isVisible() and bottom.rows["road.5"].isVisible()
    assert bottom.choice.currentText() == "Castles/Roads"
    assert "flag" not in bottom.rows
    assert not bottom.empty_label.isVisible()
    top.choice.setCurrentIndex(top.choice.findData("trees_ruins"))
    assert top.rows["ruin.2"].isVisible()


def test_ruin_from_lower_list_blocks_tiles_above(window):
    w = window
    drag_from_palette(w, "grass.7", 10, 10)
    w.step_layer(1)
    drag_from_palette(w, "ruin.3", 10, 10)
    assert len(w.model.tiles) == 2
    assert "Used 1" in w.palette.rows["ruin.3"].counts_label.text()
    w.step_layer(1)
    drag_from_palette(w, "grass.1", 10, 10)
    assert len(w.model.tiles) == 2


def test_numbers_and_badge_follow_layer(window):
    from heroscape_builder.gui.map_view import ACTIVE

    w = window
    w.rules_box.setChecked(False)
    drag_from_palette(w, "grass.1", 5, 5)
    w.step_layer(2)
    assert w.map_view.layer_badge.text() == "Layer 3"
    assert w.map_view.layer_badge.isVisible()
    item = next(iter(w.map_view.tile_items.values()))
    assert item.state != ACTIVE  # so its number isn't drawn
    before = w.map_view.layer_badge.size()
    w.zoom_slider.setValue(125)
    assert w.map_view.layer_badge.size() == before


def test_red_border_checkbox(window):
    w = window
    for col in (4, 10, 16):
        drag_from_palette(w, "sand.7", col, 4)
    assert any(item.over_limit for item in w.map_view.tile_items.values())
    w.red_border_box.setChecked(False)
    assert not any(item.over_limit for item in w.map_view.tile_items.values())
    assert "-1" in w.palette.rows["sand.7"].counts_label.text()
    assert w.settings.value("red_border") == "false"
    w.red_border_box.setChecked(True)


def test_white_wash_grows_with_depth(window):
    w = window
    w.rules_box.setChecked(False)
    for layer, col in ((1, 4), (2, 8), (3, 12)):
        w.set_layer(layer)
        drag_from_palette(w, "grass.1", col, 4)
    w.set_layer(3)
    by_layer = {item.layer: item for item in w.map_view.tile_items.values()}
    assert by_layer[3].wash == 0
    assert 0 < by_layer[2].wash < by_layer[1].wash
    assert abs(by_layer[1].wash - 2 * by_layer[2].wash) < 1e-9  # the layer just below is washed half as much
    w.set_layer(2)
    by_layer = {item.layer: item for item in w.map_view.tile_items.values()}
    assert by_layer[1].wash > 0


def test_red_border_only_on_current_layer(window):
    w = window
    for col in (4, 10, 16):
        drag_from_palette(w, "sand.7", col, 4)
    assert any(item.over_limit for item in w.map_view.tile_items.values())
    w.step_layer(1)
    assert not any(item.over_limit for item in w.map_view.tile_items.values())


def test_armies_panel_lists_characters(window):
    armies = window.armies
    assert armies.isVisible()
    assert armies.choice.count() == 1  # only the base set is owned at first
    assert "Rise of the Valkyrie" in armies.title.text()
    armies.set_owned({"rotv", "forest", "marro", "archkyrie"})
    assert armies.choice.count() == 3  # the castle set has no characters
    assert len(armies.character_names) == 16 and "Mimring" in armies.character_names
    armies.choice.setCurrentIndex(armies.choice.findData("forest"))
    assert armies.character_names == ["Dumutef Guard"]
    armies.choice.setCurrentIndex(armies.choice.findData("marro"))
    assert "Marro Stingers \u00d72" in armies.character_names


def test_counted_only_row_cannot_be_dragged(window):
    w = window
    row = w.palette.lists[1].rows["battlement"]
    assert "counted only" in row.counts_label.text()
    w.palette.lists[1].choice.setCurrentIndex(w.palette.lists[1].choice.findData("castle"))
    QTest.mousePress(row, Qt.LeftButton)
    assert w.map_view.carry is None
    QTest.mouseRelease(row, Qt.LeftButton)


def test_castle_built_from_lists(window):
    w = window
    drag_from_palette(w, "grass.24", 10, 10)
    w.palette.lists[1].choice.setCurrentIndex(w.palette.lists[1].choice.findData("castle"))
    w.step_layer(1)
    drag_from_palette(w, "castle_wall.straight", 10, 10)
    assert len(w.model.tiles) == 2
    wall = [t for t in w.model.tiles.values() if t.piece_id == "castle_wall.straight"][0]
    # On a higher layer the wall's top number shows, and it can't be picked from there.
    w.set_layer(6)
    item = w.map_view.tile_items[wall.uid]
    assert item.numbers == {(wall.q, wall.r): 12}
    w.set_layer(13)
    drag_from_palette(w, "walk.1", 10, 10)
    assert len(w.model.tiles) == 3


def test_armies_only_from_owned_sets(window):
    armies = window.armies
    armies.set_owned({"forest"})
    assert armies.character_names == ["Dumutef Guard"]
    armies.set_owned(set())
    assert armies.choice.count() == 0 and armies.empty_label.isVisible()
    assert armies.character_names == []


def test_terrain_list_order():
    from heroscape_builder.pieces import load_pieces

    terrain = [p.id for p in load_pieces() if p.category == "terrain"]
    assert terrain[:3] == ["grass.24", "swamp.24", "rock.24"]
    assert terrain[3:7] == ["grass.7", "swamp.7", "rock.7", "sand.7"]
    assert terrain[-2:] == ["water.1", "swamp_water.1"]


def test_drag_starts_from_row_text(window):
    w = window
    row = w.palette.rows["grass.7"]
    QTest.mousePress(row.name_label, Qt.LeftButton, pos=row.name_label.rect().center())
    assert w.map_view.carry is not None and w.map_view.carry["piece_id"] == "grass.7"
    w.map_view.cancel_carry()


def test_3d_view_is_look_only(window):
    w = window
    drag_from_palette(w, "grass.24", 10, 10)
    w.step_layer(1)
    drag_from_palette(w, "rock.7", 10, 10)
    w.button_3d.click()
    assert w.in_3d and w.map_stack.currentWidget() is w.view3d
    assert w.cut_box.isVisible()
    assert len(w.view3d.solids) == 24 + 7
    # Dragging from the piece list does nothing while in 3D.
    drag_from_palette(w, "grass.1", 20, 20)
    assert len(w.model.tiles) == 2 and w.map_view.carry is None
    # Q and E turn it 15 degrees; right-drag turns it smoothly.
    QTest.keyClick(w.view3d, Qt.Key_E)
    assert w.view3d.angle == 15
    QTest.keyClick(w.view3d, Qt.Key_Q)
    QTest.keyClick(w.view3d, Qt.Key_Q)
    assert w.view3d.angle == 345
    centre = w.view3d.rect().center()
    # Left-drag does nothing: the map only spins in place.
    QTest.mousePress(w.view3d, Qt.LeftButton, pos=centre)
    QTest.mouseMove(w.view3d, centre + QPoint(40, 30))
    QTest.mouseRelease(w.view3d, Qt.LeftButton, pos=centre + QPoint(40, 30))
    assert w.view3d.angle == 345
    QTest.mousePress(w.view3d, Qt.RightButton, pos=centre)
    QTest.mouseMove(w.view3d, centre + QPoint(25, 0))
    QTest.mouseRelease(w.view3d, Qt.RightButton, pos=centre + QPoint(25, 0))
    assert w.view3d.angle == pytest.approx(355)
    w.view3d.grab()  # draws without errors
    # Showing only up to the current layer hides the rock on layer 2.
    w.set_layer(1)
    w.cut_box.setChecked(True)
    assert len(w.view3d.solids) == 24
    w.button_2d.click()
    assert not w.in_3d and not w.cut_box.isVisible()
    drag_from_palette(w, "grass.1", 20, 20)
    assert len(w.model.tiles) == 3


def test_3d_draws_every_kind_of_piece(window):
    from heroscape_builder.gui.view3d import Cone, build_solids

    w = window
    m = w.model
    m.follow_rules = False
    for i, piece in enumerate(p for p in m.pieces.values() if p.placeable):
        q, r = from_offset(3 + (i % 6) * 4, 3 + (i // 6) * 4)
        m.add(PlacedTile(0, piece.id, q, r, 1))
    solids = build_solids(m)
    assert any(isinstance(s, Cone) for s in solids)
    w.set_3d(True)
    w.view3d.grab()


def build_wall(w):
    drag_from_palette(w, "grass.24", 10, 10)
    w.palette.lists[1].choice.setCurrentIndex(w.palette.lists[1].choice.findData("castle"))
    w.step_layer(1)
    drag_from_palette(w, "castle_wall.straight", 10, 10)
    return [t for t in w.model.tiles.values() if t.piece_id == "castle_wall.straight"][0]


def test_wall_walk_snaps_on_top_from_any_layer(window):
    w = window
    wall = build_wall(w)
    w.set_layer(1)
    drag_from_palette(w, "walk.1", 10, 10)
    walk = [t for t in w.model.tiles.values() if t.piece_id == "walk.1"][0]
    assert walk.layer == 13
    # A walk can be picked up from any layer, but on the wall's own layer a click takes the wall.
    assert w.map_view._pick(wall.q, wall.r) is walk
    w.set_layer(2)
    assert w.map_view._pick(wall.q, wall.r) is wall
    # Right-click copies snap too.
    w.set_layer(5)
    assert w.map_view.last_placed[1] == "walk.1"


def test_deleting_a_wall_takes_its_walk(window):
    w = window
    wall = build_wall(w)
    drag_from_palette(w, "walk.1", 10, 10)
    assert len(w.model.tiles) == 3
    w.set_layer(2)
    w.map_view.delete_tiles([wall.uid])
    assert len(w.model.tiles) == 1
    w.undo()
    assert len(w.model.tiles) == 3


def test_moving_a_wall_leaves_its_walk(window):
    w = window
    wall = build_wall(w)
    drag_from_palette(w, "walk.1", 10, 10)
    walk = [t for t in w.model.tiles.values() if t.piece_id == "walk.1"][0]
    w.set_layer(2)
    w.map_view.start_move([wall.uid], (wall.q, wall.r))
    target = hex_global(w, 11, 11)
    w.map_view.carry_move(target)
    w.map_view.carry_release(target)
    assert (wall.q, wall.r) != (walk.q, walk.r)
    assert walk.uid in w.model.tiles and walk.layer == 13


def test_3d_view_shows_only_tiles(window):
    w = window
    drag_from_palette(w, "grass.7", 10, 10)
    w.set_3d(True)
    centre = w.view3d._tiles_centre()
    q, r = from_offset(10, 10)
    assert centre == pytest.approx(hex_to_pixel(q, r, HEX_RADIUS))
    image = w.view3d.grab().toImage()
    corner = image.pixelColor(5, image.height() - 5)
    assert corner.name() == "#3a3f44"  # just the background, no board
