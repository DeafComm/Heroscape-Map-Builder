import pytest

from heroscape_builder.fileio import MapFileError, load_map, map_from_dict, save_map
from heroscape_builder.hexgrid import from_offset, in_bounds, pixel_to_hex, hex_to_pixel, rotate
from heroscape_builder.history import UNDO_LIMIT, History, MoveCommand, PlaceCommand, RemoveCommand
from heroscape_builder.inventory import Inventory
from heroscape_builder.model import MapModel, PlacedTile
from heroscape_builder.pieces import load_pieces, load_sets

PIECES = load_pieces()
PIECES_BY_ID = {p.id: p for p in PIECES}


def tile(piece_id, col, row, layer=1, rotation=0):
    q, r = from_offset(col, row)
    return PlacedTile(0, piece_id, q, r, layer, rotation)


def place(model, piece_id, col, row, layer=1, rotation=0):
    t = tile(piece_id, col, row, layer, rotation)
    assert model.check(t.piece_id, t.q, t.r, t.layer, t.rotation) is None
    return model.add(t)


def test_base_set_counts():
    by_id = {p.id: p for p in PIECES}
    assert by_id["grass.24"].counts == {"rotv": 6}
    assert by_id["water.1"].counts == {"rotv": 21, "marro": 8}
    assert sum(p.counts.get("rotv", 0) for p in PIECES if p.terrain == "grass") == 37
    assert sum(p.counts.get("rotv", 0) for p in PIECES) == 87
    for p in PIECES:
        assert len(p.hexes) == p.size
        assert len(set(p.hexes)) == p.size
        assert set(p.pegs) <= set(p.hexes)


def test_expansion_counts():
    by_id = {p.id: p for p in PIECES}
    forest = {p.id: p.counts["forest"] for p in PIECES if "forest" in p.counts}
    assert forest == {"road.5": 1, "road.2": 8, "road.1": 8, "tree.10": 1, "tree.11": 2, "tree.12": 1, "tree.15": 1, "stone_wall": 2}
    assert by_id["tree.15"].height == 15 and by_id["tree.15"].size == 3
    marro = {p.id: p.counts["marro"] for p in PIECES if "marro" in p.counts}
    assert marro["swamp_water.1"] == 34 and marro["swamp.24"] == 2 and sum(marro.values()) == 75
    fort = {p.id: p.counts["archkyrie"] for p in PIECES if "archkyrie" in p.counts}
    assert fort["castle_wall.corner"] == 10 and fort["walk.1"] == 21 and fort["ladder"] == 22
    assert not by_id["battlement"].placeable
    sets = {s.id: s for s in load_sets()[0]}
    assert len(sets["rotv"].characters) == 16
    assert sets["forest"].characters == (("Dumutef Guard", 1),)
    assert sum(n for _, n in sets["marro"].characters) == 13


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
    m = MapModel(PIECES, "medium")
    place(m, "grass.7", 10, 10)
    t = tile("grass.1", 10, 10)
    assert m.check(t.piece_id, t.q, t.r, 1, 0) is not None


def test_overlap_blocked_even_without_rules():
    m = MapModel(PIECES, "medium", follow_rules=False)
    place(m, "grass.7", 10, 10)
    t = tile("grass.1", 10, 10)
    assert m.check(t.piece_id, t.q, t.r, 1, 0) is not None


def test_upper_layer_needs_full_support():
    m = MapModel(PIECES, "medium")
    place(m, "grass.1", 10, 10)
    one = tile("rock.1", 10, 10, layer=2)
    assert m.check(one.piece_id, one.q, one.r, 2, 0) is None
    two = tile("rock.2", 10, 10, layer=2)
    assert m.check(two.piece_id, two.q, two.r, 2, 0) == "Every hex needs a tile underneath it"


def test_floating_allowed_without_rules():
    m = MapModel(PIECES, "medium", follow_rules=False)
    t = tile("grass.3", 10, 10, layer=5)
    assert m.check(t.piece_id, t.q, t.r, 5, 0) is None


def test_water_on_land_but_nothing_on_water():
    m = MapModel(PIECES, "medium")
    place(m, "grass.1", 10, 10)
    place(m, "water.1", 10, 10, layer=2)
    land = tile("grass.1", 10, 10, layer=3)
    assert m.check(land.piece_id, land.q, land.r, 3, 0) == "Nothing can go on top of water"


def test_water_cannot_slide_under_land():
    m = MapModel(PIECES, "medium", follow_rules=False)
    place(m, "grass.1", 10, 10, layer=2)
    m.follow_rules = True
    w = tile("water.1", 10, 10, layer=1)
    assert m.check(w.piece_id, w.q, w.r, 1, 0) == "Water can't go under another tile"


def test_layer_limits():
    m = MapModel(PIECES, "medium", follow_rules=False)
    t = tile("grass.1", 5, 5)
    assert m.check(t.piece_id, t.q, t.r, 0, 0) is not None
    assert m.check(t.piece_id, t.q, t.r, 21, 0) is not None
    assert m.check(t.piece_id, t.q, t.r, 20, 0) is None
    # Tall pieces have to fit under the top layer too.
    assert m.check("tree.15", 5, 5, 7, 0) is not None
    assert m.check("tree.15", 5, 5, 6, 0) is None


def test_off_map_blocked():
    m = MapModel(PIECES, "medium")
    t = tile("grass.2", 29, 0)
    assert m.check(t.piece_id, t.q, t.r, 1, 0) == "Off the edge of the map"


def test_move_ignores_own_cells():
    m = MapModel(PIECES, "medium")
    t = place(m, "grass.7", 10, 10)
    assert m.check(t.piece_id, t.q, t.r, 1, 1, ignore=t.uid) is None


def test_used_and_over_limit():
    m = MapModel(PIECES, "medium")
    inv = Inventory({"rotv": 1})
    owned = inv.owned_counts(PIECES)
    tiles = [place(m, "sand.7", 3 + i * 4, 5) for i in range(3)]
    assert m.used_counts()["sand.7"] == 3
    assert owned["sand.7"] == 2
    assert m.over_limit_uids(owned) == {tiles[2].uid}
    assert Inventory({"rotv": 2}).owned_counts(PIECES)["sand.7"] == 4


def test_inventory_from_bad_settings():
    known = {s.id for s in load_sets()[0]}
    assert Inventory.from_dict({"copies": {"rotv": 3, "nope": 1}}, known).copies == {"rotv": 3}
    assert Inventory.from_dict("garbage", known).copies == {"rotv": 1}


def test_undo_redo_and_limit():
    m = MapModel(PIECES, "large")
    h = History()
    for i in range(UNDO_LIMIT + 5):
        h.push(m, PlaceCommand(tile("grass.1", i, 0)))
    assert len(m.tiles) == UNDO_LIMIT + 5
    while h.can_undo():
        h.undo(m)
    assert len(m.tiles) == 5
    h.redo(m)
    assert len(m.tiles) == 6


def test_undo_move_and_remove():
    m = MapModel(PIECES, "medium")
    h = History()
    t = tile("rock.3", 10, 10)
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
    m = MapModel(PIECES, "medium")
    h = History()
    assert not h.dirty
    h.push(m, PlaceCommand(tile("grass.1", 1, 1)))
    assert h.dirty
    h.mark_saved()
    assert not h.dirty
    h.undo(m)
    assert h.dirty
    h.redo(m)
    assert not h.dirty


def test_save_load_round_trip(tmp_path):
    m = MapModel(PIECES, "large", follow_rules=False)
    place(m, "grass.24", 20, 20, rotation=2)
    place(m, "water.1", 40, 40, layer=3)
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
        map_from_dict({"format_version": 1, "tiles": [{"piece": "lava.1", "q": 0, "r": 0, "layer": 1}]}, PIECES)


def test_24_hex_rows():
    from collections import Counter

    piece = {p.id: p for p in PIECES}["grass.24"]
    rows = Counter(r for _, r in piece.hexes)
    assert [rows[r] for r in sorted(rows)] == [6, 5, 5, 3, 3, 2]
    assert (0, 0) in piece.hexes


def test_fits_smaller_map():
    m = MapModel(PIECES, "large", follow_rules=False)
    place(m, "grass.1", 5, 5)
    assert m.fits("small")
    place(m, "grass.1", 30, 30)
    assert not m.fits("small")
    assert m.fits("large")


def test_nothing_on_top_of_a_ruin():
    m = MapModel(PIECES, "medium")
    place(m, "grass.7", 10, 10)
    place(m, "ruin.3", 10, 10, layer=2)
    t = tile("grass.1", 10, 10, layer=3)
    assert m.check(t.piece_id, t.q, t.r, 3, 0) == "Nothing can go on top of a ruin"


def test_ruin_cannot_slide_under_a_tile():
    m = MapModel(PIECES, "medium", follow_rules=False)
    place(m, "grass.1", 10, 10, layer=2)
    m.follow_rules = True
    t = tile("ruin.2", 10, 10, layer=1)
    assert m.check(t.piece_id, t.q, t.r, 1, 0) == "A ruin can't go under another tile"


def ground(m, col, row, size=24):
    return place(m, f"grass.{size}", col, row)


def test_tree_fills_its_height_and_nothing_goes_over_it():
    m = MapModel(PIECES, "medium")
    ground(m, 10, 10)
    tree = tile("tree.10", 10, 10, layer=2)
    q, r = tree.q, tree.r
    assert m.check("tree.10", q, r, 2, 0) is None
    m.add(tree)
    assert m.tile_at(q, r, 11) is tree and m.tile_at(q, r, 12) is None
    assert m.top_of(tree) == 11
    assert m.check("grass.1", q, r, 12, 0) == "Nothing can go on top of a tree"
    m.follow_rules = False
    assert m.check("grass.1", q, r, 5, 0) == "Another piece is already there"
    assert m.check("grass.1", q, r, 14, 0) is None
    m.follow_rules = True
    assert m.check("grass.1", q, r, 14, 0) is not None


def test_tree_cannot_stand_in_water():
    m = MapModel(PIECES, "medium")
    w = place(m, "water.1", 5, 5)
    assert m.check("tree.11", w.q, w.r, 2, 0) == "Nothing can go on top of water"


def test_swamp_water_acts_like_water():
    m = MapModel(PIECES, "medium")
    land = place(m, "swamp.7", 10, 10)
    place(m, "swamp_water.1", 10, 10, layer=2)
    assert m.check("road.1", land.q, land.r, 3, 0) == "Nothing can go on top of water"


def test_castle_wall_takes_walks_only():
    m = MapModel(PIECES, "medium")
    ground(m, 10, 10)
    wall = place(m, "castle_wall.straight", 10, 10, layer=2)
    assert m.top_of(wall) == 12
    assert m.check("grass.1", wall.q, wall.r, 13, 0) == "Nothing can go on top of a castle wall"
    assert m.check("walk.1", wall.q, wall.r, 13, 0) is None
    walk = m.add(PlacedTile(0, "walk.1", wall.q, wall.r, 13))
    # Tiles can then go on the walk, and the wall can't be taken away from under it.
    assert m.check("grass.1", wall.q, wall.r, 14, 0) is None
    assert m.supports_others(wall)
    assert not m.supports_others(wall, ignore={walk.uid})


def test_wall_walk_pegs_need_walls():
    m = MapModel(PIECES, "medium")
    ground(m, 10, 10)
    walk = PIECES_BY_ID["walk.7"]
    q, r = from_offset(10, 10)
    pegs = walk.support_cells(q, r, 0)
    assert len(pegs) == 4
    assert m.check("walk.7", q, r, 13, 0) == "Each peg of a wall walk must sit on top of a wall or the doorway"
    for cell in pegs[:-1]:
        m.add(PlacedTile(0, "castle_wall.end", cell[0], cell[1], 2))
    assert m.check("walk.7", q, r, 13, 0) is not None
    m.add(PlacedTile(0, "castle_wall.end", pegs[-1][0], pegs[-1][1], 2))
    # The other hexes hang free.
    assert m.check("walk.7", q, r, 13, 0) is None


def test_doorway_holds_a_walk():
    m = MapModel(PIECES, "medium")
    ground(m, 10, 10)
    door = place(m, "doorway", 10, 10, layer=2)
    assert m.check("walk.1", door.q, door.r, 13, 0) is None
    assert m.check("grass.1", door.q, door.r, 2, 0) == "Another piece is already there"


def test_stone_wall_needs_tiles_along_its_length():
    m = MapModel(PIECES, "medium")
    piece = PIECES_BY_ID["stone_wall"]
    q, r = from_offset(10, 10)
    side = piece.side_cells(q, r, 0)
    assert len(side) == 5
    for cq, cr in side[:-1]:
        m.add(PlacedTile(0, "grass.1", cq, cr, 1))
    assert m.check("stone_wall", q, r, 1, 0) == "A stone wall needs tiles on its layer along its whole length"
    m.add(PlacedTile(0, "grass.1", *side[-1], 1))
    assert m.check("stone_wall", q, r, 1, 0) is None
    m.add(PlacedTile(0, "stone_wall", q, r, 1))
    # Taking away a tile it stands against isn't allowed.
    assert m.supports_others(m.tile_at(*side[0], 1))
    cq, cr = piece.cells(q, r, 0)[0]
    m.follow_rules = False
    m.add(PlacedTile(0, "grass.1", cq, cr, 2))
    m.follow_rules = True
    assert m.check("grass.1", cq, cr, 3, 0) == "Nothing can go over a stone wall"


def test_stone_wall_up_high_can_have_tiles_under_it():
    m = MapModel(PIECES, "medium", follow_rules=False)
    piece = PIECES_BY_ID["stone_wall"]
    q, r = from_offset(10, 10)
    for cq, cr in piece.cells(q, r, 0):
        m.add(PlacedTile(0, "grass.1", cq, cr, 1))
    for cq, cr in piece.side_cells(q, r, 0):
        m.add(PlacedTile(0, "grass.1", cq, cr, 1))
        m.add(PlacedTile(0, "grass.1", cq, cr, 2))
    m.follow_rules = True
    assert m.check("stone_wall", q, r, 2, 0) is None


def test_ladder_against_a_wall_uses_eleven_rungs():
    m = MapModel(PIECES, "medium")
    ground(m, 10, 10)
    wall = place(m, "castle_wall.straight", 10, 10, layer=2)
    assert m.check("ladder", wall.q + 2, wall.r, 2, 0) == "A ladder must stand against a castle wall on the same layer"
    ladder = m.add(PlacedTile(0, "ladder", wall.q + 1, wall.r, 2))
    assert m.top_of(ladder) == m.top_of(wall)
    assert m.used_counts()["ladder"] == 11
    owned = Inventory({"rotv": 1, "archkyrie": 1}).owned_counts(PIECES)
    assert owned["ladder"] == 22
    second = m.add(PlacedTile(0, "ladder", wall.q - 1, wall.r, 2))
    third = m.add(PlacedTile(0, "ladder", wall.q, wall.r + 1, 2))
    assert m.over_limit_uids(owned) == {third.uid}
    assert second.uid not in m.over_limit_uids(owned)


def test_counted_only_items_cannot_be_placed():
    m = MapModel(PIECES, "medium")
    assert "only counted" in m.check("battlement", 3, 3, 1, 0)


def test_top_numbers_show_highest_at_or_below_layer():
    m = MapModel(PIECES, "medium")
    a = place(m, "grass.1", 5, 5)
    place(m, "grass.1", 5, 5, layer=2)
    place(m, "grass.1", 5, 5, layer=3)
    b = place(m, "grass.1", 6, 5)
    numbers = m.top_numbers(2)
    assert numbers[(a.q, a.r)][0] == 2
    assert numbers[(b.q, b.r)] == (1, b.uid)
    assert m.top_numbers(5)[(a.q, a.r)][0] == 3
    assert m.top_numbers(1)[(a.q, a.r)] == (1, a.uid)


def test_old_map_ids_still_load():
    data = {"format_version": 1, "tiles": [{"piece": "rotv.grass.7", "q": 10, "r": 10, "layer": 1}]}
    model, _ = map_from_dict(data, PIECES)
    assert next(iter(model.tiles.values())).piece_id == "grass.7"


def test_five_hex_road_bridges_on_its_ends():
    m = MapModel(PIECES, "medium")
    road = PIECES_BY_ID["road.5"]
    q, r = from_offset(10, 10)
    cells = road.cells(q, r, 0)
    m.add(PlacedTile(0, "grass.1", *cells[0], 1))
    m.add(PlacedTile(0, "water.1", *cells[2], 1))
    assert m.check("road.5", q, r, 2, 0) == "Every hex needs a tile underneath it"
    m.add(PlacedTile(0, "grass.1", *cells[-1], 1))
    assert m.check("road.5", q, r, 2, 0) is None
    bridge = m.add(PlacedTile(0, "road.5", q, r, 2))
    # Water can go under the middle of the span later too, but not under an end.
    assert m.check("swamp_water.1", *cells[1], 1, 0) is None
    assert m.supports_others(m.tile_at(*cells[0], 1))
    assert not m.supports_others(m.tile_at(*cells[2], 1))
    assert bridge.uid in m.tiles
