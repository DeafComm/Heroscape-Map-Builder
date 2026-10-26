"""Piece types and the sets they come in, loaded from the data folder."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from .hexgrid import rotate

DATA_DIR = Path(__file__).parent / "data"

TERRAIN_NAMES = {
    "grass": "Grass",
    "rock": "Rock",
    "sand": "Sand",
    "water": "Water",
    "ruin": "Ruin",
    "road": "Road",
    "swamp": "Swamp",
    "swamp_water": "Swamp water",
}

# The groups pieces are shown in, as (id, label), in drop-down order.
CATEGORIES = [
    ("terrain", "Terrain"),
    ("castle", "Castle"),
    ("trees_ruins", "Trees/Ruins"),
]


def _standard_shape(size):
    """Hex offsets of the standard tile shapes, with (0, 0) as the anchor."""
    if size == 1:
        return [(0, 0)]
    if size == 2:
        return [(0, 0), (1, 0)]
    if size == 3:
        return [(0, 0), (1, 0), (0, 1)]
    if size == 7:
        return [(0, 0), (1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
    if size == 24:
        # Rows of 6, 5, 5, 3, 3 and 2 hexes, matching the real tile. Seen with its long
        # edge at the top, the right-hand ends line up and the left side steps in.
        # Anchored near the middle.
        hexes = []
        for r, (start, length) in enumerate(((0, 6), (0, 5), (0, 5), (1, 3), (1, 3), (1, 2))):
            for q in range(start, start + length):
                hexes.append((q - 2, r - 2))
        return hexes
    raise ValueError(f"No standard shape for a {size}-hex tile")


@dataclass(frozen=True)
class PieceType:
    """A kind of piece. The same piece can come in several sets, with a count for each.

    kind is what the piece is, which decides its rules:
      tile         land, road, swamp, water and ruins, one layer thick
      tree         fills height layers, and nothing can ever go over it
      castle_wall  a base and wall section, height layers tall; only wall walks go on top
      doorway      like a castle wall, three hexes wide
      walk         a wall walk; only its peg hexes need a wall or doorway under them
      stone_wall   stands beside a row of tiles (the side hexes); nothing can go over it
      ladder       stands against a castle wall, as tall as the wall
      item         counted in the inventory but not placed on the map
    """

    id: str
    terrain: str
    size: int
    hexes: tuple
    counts: dict = field(default_factory=dict, compare=False, hash=False)  # set id -> count
    category: str = "terrain"
    kind: str = "tile"
    height: int = 1
    uses: int = 1  # how many of the counted parts one placed piece uses, like a ladder's rungs
    label: str = ""
    pegs: tuple = ()
    side: tuple = ()
    walls: tuple = ()  # for castle walls, the hex edges (0-5) the wall runs to

    @property
    def name(self):
        return self.label or f"{TERRAIN_NAMES.get(self.terrain, self.terrain.title())} {self.size}-hex"

    @property
    def count(self):
        return sum(self.counts.values())

    @property
    def placeable(self):
        return self.kind != "item"

    @property
    def is_water(self):
        return self.terrain in ("water", "swamp_water")

    @property
    def blocks_above(self):
        """True if nothing can rest directly on top (castle walls still take wall walks)."""
        return self.is_water or self.kind in ("tree", "castle_wall", "doorway", "stone_wall", "ladder") or self.terrain == "ruin"

    @property
    def blocks_column(self):
        """True if nothing can go anywhere above it, even hanging over it."""
        return self.kind in ("tree", "stone_wall")

    def accepts_on_top(self, other):
        if self.kind in ("castle_wall", "doorway"):
            return other.kind == "walk"
        return not self.blocks_above

    def support_offsets(self):
        """The hexes that need something under them."""
        if self.kind == "walk":
            return self.pegs
        if self.kind == "stone_wall":
            return ()
        return self.hexes

    def _place(self, offsets, q, r, rotation):
        result = []
        for dq, dr in offsets:
            rq, rr = rotate(dq, dr, rotation)
            result.append((q + rq, r + rr))
        return result

    def cells(self, q, r, rotation):
        """The hexes this piece covers with its anchor at (q, r)."""
        return self._place(self.hexes, q, r, rotation)

    def support_cells(self, q, r, rotation):
        return self._place(self.support_offsets(), q, r, rotation)

    def side_cells(self, q, r, rotation):
        """For a stone wall, the hexes of the row of tiles it stands against."""
        return self._place(self.side, q, r, rotation)


@dataclass(frozen=True)
class GameSet:
    id: str
    name: str
    available: bool
    characters: tuple = ()  # (name, count) for each army card


# Old maps named pieces after the base set, like "rotv.grass.24".
OLD_PREFIX = "rotv."


def _read(name):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def load_sets():
    data = _read("sets.json")
    sets = []
    for s in data["sets"]:
        characters = ()
        if s.get("pieces_file"):
            characters = tuple((c["name"], int(c.get("count", 1))) for c in _read(s["pieces_file"]).get("characters", []))
        sets.append(GameSet(s["id"], s["name"], bool(s.get("pieces_file")), characters))
    return sets, data


def load_pieces():
    """Every piece type that comes in a set with piece data, in display order."""
    _, data = load_sets()
    counts = {}
    for s in data["sets"]:
        if s.get("pieces_file"):
            for piece_id, n in _read(s["pieces_file"])["counts"].items():
                counts.setdefault(piece_id, {})[s["id"]] = n
    pieces = []
    for p in _read("pieces.json")["pieces"]:
        if p["id"] not in counts:
            continue
        hexes = p.get("hexes") or _standard_shape(p["size"])
        pieces.append(
            PieceType(
                id=p["id"],
                terrain=p["terrain"],
                size=p["size"],
                hexes=tuple(tuple(h) for h in hexes),
                counts=counts[p["id"]],
                category=p.get("category", "terrain"),
                kind=p.get("kind", "tile"),
                height=p.get("height", 1),
                uses=p.get("uses", 1),
                label=p.get("label", ""),
                pegs=tuple(tuple(h) for h in p.get("pegs", ())),
                side=tuple(tuple(h) for h in p.get("side", ())),
                walls=tuple(p.get("walls", ())),
            )
        )
    return pieces
