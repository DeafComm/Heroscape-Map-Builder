// Saving and loading maps as JSON, in the same format as the desktop app.

import { MAP_SIZES } from "./hexgrid.js";
import { MapModel, makeTile } from "./model.js";
import { OLD_PREFIX } from "./pieces.js";

export const FORMAT_VERSION = 1;
export const FILE_SUFFIX = ".hsmap.json";

export class MapFileError extends Error {}

export function mapToDict(model, name) {
  return {
    format_version: FORMAT_VERSION,
    name,
    size: model.sizeName,
    follow_game_rules: model.followRules,
    tiles: [...model.tiles.values()].map((t) => ({ piece: t.pieceId, q: t.q, r: t.r, layer: t.layer, rotation: t.rotation })),
  };
}

const toInt = (v) => {
  const n = Number(v);
  if (v === null || v === undefined || v === "" || typeof v === "boolean" || !Number.isFinite(n)) throw new TypeError("bad number");
  return Math.trunc(n);
};

export function mapFromDict(data, pieces) {
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new MapFileError("This isn't a map file");
  const version = data.format_version;
  if (!Number.isInteger(version) || version > FORMAT_VERSION) throw new MapFileError("This map was made by a newer version of the app");
  const size = data.size ?? "small";
  if (!(size in MAP_SIZES)) throw new MapFileError(`Unknown map size: ${size}`);
  const model = new MapModel(pieces, size, Boolean(data.follow_game_rules ?? true));
  (data.tiles || []).forEach((t, i) => {
    let tile;
    try {
      if (!t || t.piece === undefined) throw new TypeError("no piece");
      tile = makeTile(0, String(t.piece), toInt(t.q), toInt(t.r), toInt(t.layer), ((toInt(t.rotation ?? 0) % 6) + 6) % 6);
    } catch {
      throw new MapFileError(`Tile ${i + 1} is not valid`);
    }
    if (!(tile.pieceId in model.pieces) && tile.pieceId.startsWith(OLD_PREFIX)) tile.pieceId = tile.pieceId.slice(OLD_PREFIX.length);
    if (!(tile.pieceId in model.pieces)) throw new MapFileError(`Unknown piece: ${tile.pieceId}`);
    // Rules are off while loading so a map saved without them still opens.
    const follow = model.followRules;
    model.followRules = false;
    const problem = model.check(tile.pieceId, tile.q, tile.r, tile.layer, tile.rotation);
    model.followRules = follow;
    if (problem) throw new MapFileError(`Tile ${i + 1} (${tile.pieceId}): ${problem}`);
    model.add(tile);
  });
  return { model, name: String(data.name ?? "") };
}

export function mapFromText(text, pieces) {
  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    throw new MapFileError(`The file isn't valid JSON: ${e.message}`);
  }
  return mapFromDict(data, pieces);
}

export function mapToText(model, name) {
  return JSON.stringify(mapToDict(model, name), null, 2) + "\n";
}

export function baseName(fileName) {
  return fileName.replace(/\.hsmap\.json$/, "").replace(/\.json$/, "");
}
