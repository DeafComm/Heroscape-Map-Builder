import pytest

from heroscape_builder.fileio import MapFileError, load_map, map_from_dict, save_map
from heroscape_builder.hexgrid import from_offset, in_bounds, pixel_to_hex, hex_to_pixel, rotate
from heroscape_builder.history import UNDO_LIMIT, History, MoveCommand, PlaceCommand, RemoveCommand
from heroscape_builder.inventory import Inventory
from heroscape_builder.model import MapModel, PlacedTile
from heroscape_builder.pieces import load_pieces, load_sets

PIECES = load_pieces()


def tile(piece_id, col, row, layer=1, rotation=0):
    q, r = from_offset(col, row)
    return PlacedTile(0, piece_id, q, r, layer, rotation)


def place(model, piece_id, col, row, layer=1, rotation=0):
    t = tile(piece_id, col, row, layer, rotation)
    assert model.check(t.piece_id, t.q, t.r, t.layer, t.rotation) is None
    return model.add(t)


def test_base_set_counts():
    by_id = {p.id: p for p in PIECES}
    assert len(PIECES) == 17
    assert sum(p.category == "trees_ruins" for p in PIECES) == 2
    assert by_id["rotv.grass.24"].count == 6
    assert by_id["rotv.water.1"].count == 21
    assert sum(p.count for p in PIECES if p.terrain == "grass") == 37
    for p in PIECES:
        assert len(p.hexes) == p.size
        assert len(set(p.hexes)) == p.size


def test_rotation_cycles_back():
    for q, r in [(1, 0), (2, -1), (-3, 2)]:
        assert rotate(q, r, 6) == (q, r)
        assert rotate(q, r, 3) == (-q, -r)


def test_rotated_shapes_keep_their_size():
    for p in PIECES:
        for rot in range(6):
            assert len(set(p.cells(10, 10, rot))) == p.size


def test_pixel_round_trip():
    for q, r in [(0, 0), (3, -2), (-4, 7)]:
        x, y = hex_to_pixel(q, r, 20)
        assert pixel_to_hex(x + 3, y - 4, 20) == (q, r)


def test_bounds():
    assert in_bounds(*from_offset(0, 0), 30)
    assert in_bounds(*from_offset(29, 29), 30)
    assert not in_bounds(*from_offset(30, 0), 30)
    assert not in_bounds(*from_offset(0, -1), 30)


def test_no_overlap_on_same_layer():
    m = MapModel(PIECES, "small")
    place(m, "rotv.grass.7", 10, 10)
    t = tile("rotv.grass.1", 10, 10)
    assert m.check(t.piece_id, t.q, t.r, 1, 0) is not None


def test_overlap_blocked_even_without_rules():
    m = MapModel(PIECES, "small", follow_rules=False)
    place(m, "rotv.grass.7", 10, 10)
    t = tile("rotv.grass.1", 10, 10)
    assert m.check(t.piece_id, t.q, t.r, 1, 0) is not None


def test_upper_layer_needs_full_support():
    m = MapModel(PIECES, "small")
    place(m, "rotv.grass.1", 10, 10)
    one = tile("rotv.rock.1", 10, 10, layer=2)
    assert m.check(one.piece_id, one.q, one.r, 2, 0) is None
    two = tile("rotv.rock.2", 10, 10, layer=2)
    assert m.check(two.piece_id, two.q, two.r, 2, 0) == "Every hex needs a tile underneath it"


def test_floating_allowed_without_rules():
    m = MapModel(PIECES, "small", follow_rules=False)
    t = tile("rotv.grass.3", 10, 10, layer=5)
    assert m.check(t.piece_id, t.q, t.r, 5, 0) is None


def test_water_on_land_but_nothing_on_water():
    m = MapModel(PIECES, "small")
    place(m, "rotv.grass.1", 10, 10)
    place(m, "rotv.water.1", 10, 10, layer=2)
    land = tile("rotv.grass.1", 10, 10, layer=3)
    assert m.check(land.piece_id, land.q, land.r, 3, 0) == "Nothing can go on top of water"


def test_water_cannot_slide_under_land():
    m = MapModel(PIECES, "small", follow_rules=False)
    place(m, "rotv.grass.1", 10, 10, layer=2)
    m.follow_rules = True
    w = tile("rotv.water.1", 10, 10, layer=1)
    assert m.check(w.piece_id, w.q, w.r, 1, 0) == "Water can't go under another tile"


def test_layer_limits():
    m = MapModel(PIECES, "small", follow_rules=False)
    t = tile("rotv.grass.1", 5, 5)
    assert m.check(t.piece_id, t.q, t.r, 0, 0) is not None
    assert m.check(t.piece_id, t.q, t.r, 16, 0) is not None
    assert m.check(t.piece_id, t.q, t.r, 15, 0) is None


def test_off_map_blocked():
    m = MapModel(PIECES, "small")
    t = tile("rotv.grass.2", 29, 0)
    assert m.check(t.piece_id, t.q, t.r, 1, 0) == "Off the edge of the map"


def test_move_ignores_own_cells():
    m = MapModel(PIECES, "small")
    t = place(m, "rotv.grass.7", 10, 10)
    assert m.check(t.piece_id, t.q, t.r, 1, 1, ignore=t.uid) is None


def test_used_and_over_limit():
    m = MapModel(PIECES, "small")
    inv = Inventory({"rotv": 1})
    owned = inv.owned_counts(PIECES)
    tiles = [place(m, "rotv.sand.7", 3 + i * 4, 5) for i in range(3)]
    assert m.used_counts()["rotv.sand.7"] == 3
    assert owned["rotv.sand.7"] == 2
    assert m.over_limit_uids(owned) == {tiles[2].uid}
    assert Inventory({"rotv": 2}).owned_counts(PIECES)["rotv.sand.7"] == 4


def test_inventory_from_bad_settings():
    known = {s.id for s in load_sets()[0]}
    assert Inventory.from_dict({"copies": {"rotv": 3, "nope": 1}}, known).copies == {"rotv": 3}
    assert Inventory.from_dict("garbage", known).copies == {"rotv": 1}


def test_undo_redo_and_limit():
    m = MapModel(PIECES, "large")
    h = History()
    for i in range(UNDO_LIMIT + 5):
        h.push(m, PlaceCommand(tile("rotv.grass.1", i, 0)))
    assert len(m.tiles) == UNDO_LIMIT + 5
    while h.can_undo():
        h.undo(m)
    assert len(m.tiles) == 5
    h.redo(m)
    assert len(m.tiles) == 6


def test_undo_move_and_remove():
    m = MapModel(PIECES, "small")
    h = History()
    t = tile("rotv.rock.3", 10, 10)
    h.push(m, PlaceCommand(t))
    h.push(m, MoveCommand(t, t.q + 2, t.r, 3))
    assert (m.tiles[t.uid].q, m.tiles[t.uid].rotation) == (t.q, 3)
    h.push(m, RemoveCommand(m.tiles[t.uid]))
    assert not m.tiles
    h.undo(m)
    h.undo(m)
    restored = m.tiles[t.uid]
    assert restored.rotation == 0
    assert m.tile_at(restored.q, restored.r, 1) is restored


def test_dirty_tracking():
    m = MapModel(PIECES, "small")
    h = History()
    assert not h.dirty
    h.push(m, PlaceCommand(tile("rotv.grass.1", 1, 1)))
    assert h.dirty
    h.mark_saved()
    assert not h.dirty
    h.undo(m)
    assert h.dirty
    h.redo(m)
    assert not h.dirty


def test_save_load_round_trip(tmp_path):
    m = MapModel(PIECES, "large", follow_rules=False)
    place(m, "rotv.grass.24", 20, 20, rotation=2)
    place(m, "rotv.water.1", 40, 40, layer=3)
    path = tmp_path / "valley.hsmap.json"
    save_map(path, m)
    loaded, name = load_map(path, PIECES)
    assert name == "valley"
    assert loaded.size_name == "large"
    assert loaded.follow_rules is False
    assert [(t.piece_id, t.q, t.r, t.layer, t.rotation) for t in loaded.tiles.values()] == [
        (t.piece_id, t.q, t.r, t.layer, t.rotation) for t in m.tiles.values()
    ]


def test_load_rejects_bad_files(tmp_path):
    bad = tmp_path / "bad.hsmap.json"
    bad.write_text("not json")
    with pytest.raises(MapFileError):
        load_map(bad, PIECES)
    with pytest.raises(MapFileError):
        map_from_dict({"format_version": 99}, PIECES)
    with pytest.raises(MapFileError):
        map_from_dict({"format_version": 1, "tiles": [{"piece": "rotv.lava.1", "q": 0, "r": 0, "layer": 1}]}, PIECES)


def test_24_hex_rows():
    from collections import Counter

    piece = {p.id: p for p in PIECES}["rotv.grass.24"]
    rows = Counter(r for _, r in piece.hexes)
    assert [rows[r] for r in sorted(rows)] == [6, 5, 5, 3, 3, 2]
    assert (0, 0) in piece.hexes


def test_fits_smaller_map():
    m = MapModel(PIECES, "large", follow_rules=False)
    place(m, "rotv.grass.1", 5, 5)
    assert m.fits("small")
    place(m, "rotv.grass.1", 60, 60)
    assert not m.fits("small")
    assert m.fits("large")


def test_nothing_on_top_of_a_ruin():
    m = MapModel(PIECES, "small")
    place(m, "rotv.grass.7", 10, 10)
    place(m, "rotv.ruin.3", 10, 10, layer=2)
    t = tile("rotv.grass.1", 10, 10, layer=3)
    assert m.check(t.piece_id, t.q, t.r, 3, 0) == "Nothing can go on top of a ruin"


def test_ruin_cannot_slide_under_a_tile():
    m = MapModel(PIECES, "small", follow_rules=False)
    place(m, "rotv.grass.1", 10, 10, layer=2)
    m.follow_rules = True
    t = tile("rotv.ruin.2", 10, 10, layer=1)
    assert m.check(t.piece_id, t.q, t.r, 1, 0) == "A ruin can't go under another tile"
