"""Piece types and the sets they come in, loaded from the data folder."""

import json
from dataclasses import dataclass
from pathlib import Path

from .hexgrid import rotate

DATA_DIR = Path(__file__).parent / "data"

TERRAIN_NAMES = {
    "grass": "Grass",
    "rock": "Rock",
    "sand": "Sand",
    "water": "Water",
}


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
        # Rows of 4, 5, 6, 5 and 4 hexes.
        hexes = []
        for r in range(-2, 3):
            for q in range(max(-2, -r - 2), min(2, -r + 2) + 2):
                hexes.append((q, r))
        return hexes
    raise ValueError(f"No standard shape for a {size}-hex tile")


@dataclass(frozen=True)
class PieceType:
    id: str
    set_id: str
    terrain: str
    size: int
    count: int
    hexes: tuple

    @property
    def name(self):
        return f"{TERRAIN_NAMES.get(self.terrain, self.terrain.title())} {self.size}-hex"

    @property
    def is_water(self):
        return self.terrain == "water"

    def cells(self, q, r, rotation):
        """The hexes this piece covers with its anchor at (q, r)."""
        result = []
        for dq, dr in self.hexes:
            rq, rr = rotate(dq, dr, rotation)
            result.append((q + rq, r + rr))
        return result


@dataclass(frozen=True)
class GameSet:
    id: str
    name: str
    available: bool


def load_sets():
    with open(DATA_DIR / "sets.json", encoding="utf-8") as f:
        data = json.load(f)
    return [GameSet(s["id"], s["name"], bool(s.get("pieces_file"))) for s in data["sets"]], data


def load_pieces():
    """All piece types from every set that has piece data, in display order."""
    _, data = load_sets()
    pieces = []
    for s in data["sets"]:
        if not s.get("pieces_file"):
            continue
        with open(DATA_DIR / s["pieces_file"], encoding="utf-8") as f:
            set_data = json.load(f)
        for p in set_data["pieces"]:
            hexes = p.get("hexes") or _standard_shape(p["size"])
            pieces.append(
                PieceType(
                    id=p["id"],
                    set_id=s["id"],
                    terrain=p["terrain"],
                    size=p["size"],
                    count=p["count"],
                    hexes=tuple(tuple(h) for h in hexes),
                )
            )
    return pieces
