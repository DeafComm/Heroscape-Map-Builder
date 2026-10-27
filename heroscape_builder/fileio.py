"""Saving and loading maps as JSON files."""

import json
from pathlib import Path

from .hexgrid import MAP_SIZES
from .model import MapModel, PlacedTile
from .pieces import OLD_PREFIX

FORMAT_VERSION = 1
FILE_SUFFIX = ".hsmap.json"


class MapFileError(Exception):
    pass


def map_to_dict(model, name):
    return {
        "format_version": FORMAT_VERSION,
        "name": name,
        "size": model.size_name,
        "follow_game_rules": model.follow_rules,
        "tiles": [
            {
                "piece": t.piece_id,
                "q": t.q,
                "r": t.r,
                "layer": t.layer,
                "rotation": t.rotation,
            }
            for t in model.tiles.values()
        ],
    }


def map_from_dict(data, pieces):
    if not isinstance(data, dict):
        raise MapFileError("This isn't a map file")
    version = data.get("format_version")
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise MapFileError("This map was made by a newer version of the app")
    size = data.get("size", "small")
    if size not in MAP_SIZES:
        raise MapFileError(f"Unknown map size: {size}")
    model = MapModel(pieces, size, bool(data.get("follow_game_rules", True)))
    for i, t in enumerate(data.get("tiles", [])):
        try:
            tile = PlacedTile(
                uid=0,
                piece_id=str(t["piece"]),
                q=int(t["q"]),
                r=int(t["r"]),
                layer=int(t["layer"]),
                rotation=int(t.get("rotation", 0)) % 6,
            )
        except (KeyError, TypeError, ValueError) as e:
            raise MapFileError(f"Tile {i + 1} is not valid") from e
        if tile.piece_id not in model.pieces and tile.piece_id.startswith(OLD_PREFIX):
            tile.piece_id = tile.piece_id.removeprefix(OLD_PREFIX)
        if tile.piece_id not in model.pieces:
            raise MapFileError(f"Unknown piece: {tile.piece_id}")
        # Rules are off while loading so a map saved without them still opens.
        follow = model.follow_rules
        model.follow_rules = False
        problem = model.check(tile.piece_id, tile.q, tile.r, tile.layer, tile.rotation)
        model.follow_rules = follow
        if problem:
            raise MapFileError(f"Tile {i + 1} ({tile.piece_id}): {problem}")
        model.add(tile)
    return model, str(data.get("name", ""))


def save_map(path, model):
    path = Path(path)
    name = path.name.removesuffix(FILE_SUFFIX).removesuffix(".json")
    text = json.dumps(map_to_dict(model, name), indent=2)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text + "\n", encoding="utf-8")
    tmp.replace(path)


def load_map(path, pieces):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        raise MapFileError(f"Couldn't read the file: {e}") from e
    except json.JSONDecodeError as e:
        raise MapFileError(f"The file isn't valid JSON: {e}") from e
    return map_from_dict(data, pieces)
