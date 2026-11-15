// Piece types and the sets they come in, loaded from the data folder.

import { rotate } from "./hexgrid.js";

export const TERRAIN_NAMES = {
  grass: "Grass", rock: "Rock", sand: "Sand", water: "Water", ruin: "Ruin",
  road: "Road", swamp: "Swamp", swamp_water: "Swamp water",
};

// The groups pieces are shown in, as [id, label], in drop-down order.
export const CATEGORIES = [
  ["terrain", "Terrain"],
  ["castle", "Castles/Roads"],
  ["trees_ruins", "Trees/Ruins"],
];

// Old maps named pieces after the base set, like "rotv.grass.24".
export const OLD_PREFIX = "rotv.";

function standardShape(size) {
  if (size === 1) return [[0, 0]];
  if (size === 2) return [[0, 0], [1, 0]];
  if (size === 3) return [[0, 0], [1, 0], [0, 1]];
  if (size === 7) return [[0, 0], [1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]];
  if (size === 24) {
    // Rows of 6, 5, 5, 3, 3 and 2 hexes, matching the real tile. Seen with its long
    // edge at the top, the right-hand ends line up and the left side steps in.
    const hexes = [];
    [[0, 6], [0, 5], [0, 5], [1, 3], [1, 3], [1, 2]].forEach(([start, length], r) => {
      for (let q = start; q < start + length; q++) hexes.push([q - 2, r - 2]);
    });
    return hexes;
  }
  throw new Error(`No standard shape for a ${size}-hex tile`);
}

function place(offsets, q, r, rotation) {
  return offsets.map(([dq, dr]) => {
    const [rq, rr] = rotate(dq, dr, rotation);
    return [q + rq, r + rr];
  });
}

/**
 * A kind of piece. kind decides its rules:
 *   tile         land, road, swamp, water and ruins, one layer thick; a tile with pegs
 *                (the 5-hex road) only needs support under those hexes
 *   tree         fills height layers, and nothing can ever go over it
 *   castle_wall  a base and wall section, height layers tall; only wall walks go on top
 *   doorway      like a castle wall, three hexes wide
 *   walk         a wall walk; only its peg hexes need a wall or doorway under them
 *   stone_wall   stands beside a row of tiles (the side hexes); nothing can go over it
 *   ladder       stands against a castle wall, as tall as the wall
 *   item         counted in the inventory but not placed on the map
 */
export class PieceType {
  constructor(p, counts) {
    this.id = p.id;
    this.terrain = p.terrain;
    this.size = p.size;
    this.hexes = p.hexes || standardShape(p.size);
    this.counts = counts; // set id -> count
    this.category = p.category || "terrain";
    this.kind = p.kind || "tile";
    this.height = p.height || 1;
    this.uses = p.uses || 1;
    this.label = p.label || "";
    this.pegs = p.pegs || [];
    this.side = p.side || [];
    this.walls = p.walls || [];
  }

  get name() {
    return this.label || `${TERRAIN_NAMES[this.terrain] || this.terrain} ${this.size}-hex`;
  }

  get placeable() { return this.kind !== "item"; }

  get isWater() { return this.terrain === "water" || this.terrain === "swamp_water"; }

  /** True if nothing can rest directly on top (castle walls still take wall walks). */
  get blocksAbove() {
    return this.isWater || ["tree", "castle_wall", "doorway", "stone_wall", "ladder"].includes(this.kind) || this.terrain === "ruin";
  }

  /** True if nothing can go anywhere above it, even hanging over it. */
  get blocksColumn() { return this.kind === "tree" || this.kind === "stone_wall"; }

  acceptsOnTop(other) {
    if (this.kind === "castle_wall" || this.kind === "doorway") return other.kind === "walk";
    return !this.blocksAbove;
  }

  /** The hexes that need something under them. */
  supportOffsets() {
    if (this.pegs.length) return this.pegs;
    if (this.kind === "stone_wall") return [];
    return this.hexes;
  }

  /** The hexes this piece covers with its anchor at (q, r). */
  cells(q, r, rotation) { return place(this.hexes, q, r, rotation); }

  supportCells(q, r, rotation) { return place(this.supportOffsets(), q, r, rotation); }

  /** For a stone wall, the hexes of the row of tiles it stands against. */
  sideCells(q, r, rotation) { return place(this.side, q, r, rotation); }
}

async function readJson(name) {
  const response = await fetch(`data/${name}`);
  if (!response.ok) throw new Error(`Couldn't load data/${name}`);
  return response.json();
}

/** The sets (with their characters) and every piece type that comes in a set with piece data. */
export async function loadData() {
  const setsData = await readJson("sets.json");
  const sets = [];
  const counts = {};
  for (const s of setsData.sets) {
    let characters = [];
    if (s.pieces_file) {
      const file = await readJson(s.pieces_file);
      characters = (file.characters || []).map((c) => [c.name, Number(c.count || 1)]);
      for (const [pieceId, n] of Object.entries(file.counts)) {
        (counts[pieceId] ||= {})[s.id] = n;
      }
    }
    sets.push({ id: s.id, name: s.name, available: Boolean(s.pieces_file), characters });
  }
  const piecesData = await readJson("pieces.json");
  const pieces = piecesData.pieces.filter((p) => counts[p.id]).map((p) => new PieceType(p, counts[p.id]));
  return { sets, pieces };
}
