"""The map being built: placed tiles, layers and the placement rules."""

from dataclasses import dataclass

from .hexgrid import MAP_SIZES, in_bounds

MIN_LAYER = 1
MAX_LAYER = 20


def _blocker_name(piece):
    if piece.is_water:
        return "water"
    return {
        "tree": "a tree",
        "castle_wall": "a castle wall",
        "doorway": "the doorway",
        "stone_wall": "a stone wall",
        "ladder": "a ladder",
    }.get(piece.kind, "a ruin")


@dataclass
class PlacedTile:
    uid: int
    piece_id: str
    q: int
    r: int
    layer: int
    rotation: int = 0


class MapModel:
    def __init__(self, pieces, size_name="small", follow_rules=True):
        self.pieces = {p.id: p for p in pieces}
        self.size_name = size_name
        self.follow_rules = follow_rules
        self.tiles = {}  # uid -> PlacedTile, in placement order
        self._cells = {}  # (q, r, layer) -> uid
        self._next_uid = 1

    @property
    def size(self):
        return MAP_SIZES[self.size_name]

    def piece(self, tile):
        return self.pieces[tile.piece_id]

    def cells_of(self, tile):
        return self.piece(tile).cells(tile.q, tile.r, tile.rotation)

    def top_of(self, tile):
        """The highest layer the tile fills."""
        return tile.layer + self.piece(tile).height - 1

    def tile_at(self, q, r, layer):
        """The piece filling this hex on this layer, if any (tall pieces fill several layers)."""
        uid = self._cells.get((q, r, layer))
        return self.tiles.get(uid)

    def _column(self, q, r, ignore):
        """The pieces in this hex at any layer, as (layer, tile), lowest first."""
        result = []
        for layer in range(MIN_LAYER, MAX_LAYER + 1):
            uid = self._cells.get((q, r, layer))
            if uid is not None and uid not in ignore and (not result or result[-1][1].uid != uid):
                result.append((layer, self.tiles[uid]))
        return result

    def check(self, piece_id, q, r, layer, rotation, ignore=()):
        """Return None if the piece can go here, or a reason why it can't.

        Tiles in ignore (a uid or a collection of uids) are treated as already gone,
        for tiles that are being moved.
        """
        ignore = {ignore} if isinstance(ignore, int) else set(ignore)
        piece = self.pieces[piece_id]
        if not piece.placeable:
            return f"{piece.name} is only counted, not placed on the map"
        top = layer + piece.height - 1
        if not MIN_LAYER <= layer <= MAX_LAYER:
            return f"Layers go from {MIN_LAYER} to {MAX_LAYER}"
        if top > MAX_LAYER:
            return f"Too tall: it would go above layer {MAX_LAYER}"
        cells = piece.cells(q, r, rotation)
        for cq, cr in cells:
            if not in_bounds(cq, cr, self.size):
                return "Off the edge of the map"
            for level in range(layer, top + 1):
                other = self._cells.get((cq, cr, level))
                if other is not None and other not in ignore:
                    return "Another piece is already there"
        if not self.follow_rules:
            return None

        for cq, cr in piece.support_cells(q, r, rotation):
            below = self._cells.get((cq, cr, layer - 1))
            if below is None or below in ignore:
                if piece.kind == "walk":
                    return "Each peg of a wall walk must sit on top of a wall or the doorway"
                if layer > MIN_LAYER:
                    return "Every hex needs a tile underneath it"
                continue
            below_tile = self.tiles[below]
            below_piece = self.piece(below_tile)
            if piece.kind == "walk" and below_piece.kind not in ("castle_wall", "doorway"):
                return "Each peg of a wall walk must sit on top of a wall or the doorway"
            if not below_piece.accepts_on_top(piece):
                return f"Nothing can go on top of {_blocker_name(below_piece)}"

        if piece.kind == "stone_wall":
            for cq, cr in piece.side_cells(q, r, rotation):
                beside = self._cells.get((cq, cr, layer))
                if beside is None or beside in ignore:
                    return "A stone wall needs tiles on its layer along its whole length"
        if piece.kind == "ladder":
            if not self._beside_wall(cells[0], layer, ignore):
                return "A ladder must stand against a castle wall on the same layer"

        for cq, cr in cells:
            for level, other in self._column(cq, cr, ignore):
                other_piece = self.piece(other)
                other_top = self.top_of(other)
                if other_top < layer and other_piece.blocks_column:
                    return f"Nothing can go over {_blocker_name(other_piece)}"
                if level > top:
                    if piece.blocks_column:
                        return f"{_blocker_name(piece).capitalize()} can't go under another tile"
                    rests_here = (cq, cr) in other_piece.support_cells(other.q, other.r, other.rotation)
                    if level == top + 1 and rests_here and not piece.accepts_on_top(other_piece):
                        return f"{_blocker_name(piece).capitalize()} can't go under another tile"
        return None

    def _beside_wall(self, cell, layer, ignore):
        q, r = cell
        for dq, dr in ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)):
            uid = self._cells.get((q + dq, r + dr, layer))
            if uid is None or uid in ignore:
                continue
            other = self.tiles[uid]
            if other.layer == layer and self.piece(other).kind in ("castle_wall", "doorway"):
                return True
        return False

    def fits(self, size_name):
        """True if every tile would still be on a map of this size."""
        size = MAP_SIZES[size_name]
        return all(in_bounds(q, r, size) for t in self.tiles.values() for q, r in self.cells_of(t))

    def supports_others(self, tile, ignore=()):
        """True if another piece (not in ignore) needs this one to stay where it is."""
        ignore = set(ignore) | {tile.uid}
        for other in self.tiles.values():
            if other.uid in ignore:
                continue
            args = (other.piece_id, other.q, other.r, other.layer, other.rotation)
            if self.check(*args, ignore={other.uid}) is None and self.check(*args, ignore={other.uid, tile.uid}):
                return True
        return False

    def add(self, tile):
        """Add a tile without checking the rules. Assigns a uid if it has none."""
        if not tile.uid:
            tile.uid = self._next_uid
        self._next_uid = max(self._next_uid, tile.uid + 1)
        self.tiles[tile.uid] = tile
        for cq, cr in self.cells_of(tile):
            for layer in range(tile.layer, self.top_of(tile) + 1):
                self._cells[(cq, cr, layer)] = tile.uid
        # Keep placement order when a tile is put back by undo.
        self.tiles = dict(sorted(self.tiles.items()))
        return tile

    def remove(self, uid):
        tile = self.tiles.pop(uid)
        for cq, cr in self.cells_of(tile):
            for layer in range(tile.layer, self.top_of(tile) + 1):
                if self._cells.get((cq, cr, layer)) == uid:
                    del self._cells[(cq, cr, layer)]
        return tile

    def move(self, uid, q, r, rotation):
        tile = self.remove(uid)
        tile.q, tile.r, tile.rotation = q, r, rotation % 6
        self.add(tile)
        return tile

    def used_counts(self):
        counts = {pid: 0 for pid in self.pieces}
        for tile in self.tiles.values():
            counts[tile.piece_id] += self.piece(tile).uses
        return counts

    def over_limit_uids(self, owned):
        """Tiles placed beyond what is owned: the most recently placed ones."""
        seen = {}
        over = set()
        for tile in self.tiles.values():
            seen[tile.piece_id] = seen.get(tile.piece_id, 0) + self.piece(tile).uses
            if seen[tile.piece_id] > owned.get(tile.piece_id, 0):
                over.add(tile.uid)
        return over

    def top_numbers(self, layer):
        """For each hex, the highest layer filled by a piece starting at or below this layer.

        Returns {(q, r): (top layer, uid of that piece)}.
        """
        result = {}
        for tile in self.tiles.values():
            if tile.layer > layer:
                continue
            top = self.top_of(tile)
            for cell in self.cells_of(tile):
                if cell not in result or top > result[cell][0]:
                    result[cell] = (top, tile.uid)
        return result
