"""The map being built: placed tiles, layers and the placement rules."""

from dataclasses import dataclass

from .hexgrid import MAP_SIZES, in_bounds

MIN_LAYER = 1
MAX_LAYER = 15


@dataclass
class PlacedTile:
    uid: int
    piece_id: str
    q: int
    r: int
    layer: int
    rotation: int = 0


class MapModel:
    def __init__(self, pieces, size_name="medium", follow_rules=True):
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

    def tile_at(self, q, r, layer):
        uid = self._cells.get((q, r, layer))
        return self.tiles.get(uid)

    def check(self, piece_id, q, r, layer, rotation, ignore=()):
        """Return None if the piece can go here, or a reason why it can't.

        Tiles in ignore (a uid or a collection of uids) are treated as already gone,
        for tiles that are being moved.
        """
        ignore = {ignore} if isinstance(ignore, int) else set(ignore)
        piece = self.pieces[piece_id]
        if not MIN_LAYER <= layer <= MAX_LAYER:
            return f"Layers go from {MIN_LAYER} to {MAX_LAYER}"
        cells = piece.cells(q, r, rotation)
        for cq, cr in cells:
            if not in_bounds(cq, cr, self.size):
                return "Off the edge of the map"
            other = self._cells.get((cq, cr, layer))
            if other is not None and other not in ignore:
                return "Another tile is already there"
        if not self.follow_rules:
            return None
        for cq, cr in cells:
            if layer > MIN_LAYER:
                below = self._cells.get((cq, cr, layer - 1))
                if below is None or below in ignore:
                    return "Every hex needs a tile underneath it"
                if self.piece(self.tiles[below]).is_water:
                    return "Nothing can go on top of water"
            if piece.is_water:
                above = self._cells.get((cq, cr, layer + 1))
                if above is not None and above not in ignore:
                    return "Water can't go under another tile"
        return None

    def fits(self, size_name):
        """True if every tile would still be on a map of this size."""
        size = MAP_SIZES[size_name]
        return all(in_bounds(q, r, size) for t in self.tiles.values() for q, r in self.cells_of(t))

    def supports_others(self, tile):
        """True if any other tile rests on this one."""
        for cq, cr in self.cells_of(tile):
            if (cq, cr, tile.layer + 1) in self._cells:
                return True
        return False

    def add(self, tile):
        """Add a tile without checking the rules. Assigns a uid if it has none."""
        if not tile.uid:
            tile.uid = self._next_uid
        self._next_uid = max(self._next_uid, tile.uid + 1)
        self.tiles[tile.uid] = tile
        for cq, cr in self.cells_of(tile):
            self._cells[(cq, cr, tile.layer)] = tile.uid
        # Keep placement order when a tile is put back by undo.
        self.tiles = dict(sorted(self.tiles.items()))
        return tile

    def remove(self, uid):
        tile = self.tiles.pop(uid)
        for cq, cr in self.cells_of(tile):
            if self._cells.get((cq, cr, tile.layer)) == uid:
                del self._cells[(cq, cr, tile.layer)]
        return tile

    def move(self, uid, q, r, rotation):
        tile = self.remove(uid)
        tile.q, tile.r, tile.rotation = q, r, rotation % 6
        self.add(tile)
        return tile

    def used_counts(self):
        counts = {pid: 0 for pid in self.pieces}
        for tile in self.tiles.values():
            counts[tile.piece_id] += 1
        return counts

    def over_limit_uids(self, owned):
        """Tiles placed beyond what is owned: the most recently placed ones."""
        seen = {}
        over = set()
        for tile in self.tiles.values():
            seen[tile.piece_id] = seen.get(tile.piece_id, 0) + 1
            if seen[tile.piece_id] > owned.get(tile.piece_id, 0):
                over.add(tile.uid)
        return over
