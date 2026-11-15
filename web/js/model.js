// The map being built: placed tiles, layers and the placement rules.

import { MAP_SIZES, inBounds } from "./hexgrid.js";

export const MIN_LAYER = 1;
export const MAX_LAYER = 20;

function blockerName(piece) {
  if (piece.isWater) return "water";
  return {
    tree: "a tree", castle_wall: "a castle wall", doorway: "the doorway",
    stone_wall: "a stone wall", ladder: "a ladder",
  }[piece.kind] || "a ruin";
}

const capitalize = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const ck = (q, r, layer) => `${q},${r},${layer}`;

export function makeTile(uid, pieceId, q, r, layer, rotation = 0) {
  return { uid, pieceId, q, r, layer, rotation };
}

export class MapModel {
  constructor(pieces, sizeName = "small", followRules = true) {
    this.pieces = Object.fromEntries(pieces.map((p) => [p.id, p]));
    this.sizeName = sizeName;
    this.followRules = followRules;
    this.tiles = new Map(); // uid -> tile, in placement order
    this.cellMap = new Map(); // "q,r,layer" -> uid
    this.nextUid = 1;
  }

  get size() { return MAP_SIZES[this.sizeName]; }

  piece(tile) { return this.pieces[tile.pieceId]; }

  cellsOf(tile) { return this.piece(tile).cells(tile.q, tile.r, tile.rotation); }

  /** The highest layer the tile fills. */
  topOf(tile) { return tile.layer + this.piece(tile).height - 1; }

  /** The piece filling this hex on this layer, if any (tall pieces fill several layers). */
  tileAt(q, r, layer) {
    const uid = this.cellMap.get(ck(q, r, layer));
    return uid === undefined ? null : this.tiles.get(uid);
  }

  /** The pieces in this hex at any layer, as [layer, tile], lowest first. */
  column(q, r, ignore) {
    const result = [];
    for (let layer = MIN_LAYER; layer <= MAX_LAYER; layer++) {
      const uid = this.cellMap.get(ck(q, r, layer));
      if (uid !== undefined && !ignore.has(uid) && (!result.length || result[result.length - 1][1].uid !== uid)) {
        result.push([layer, this.tiles.get(uid)]);
      }
    }
    return result;
  }

  /**
   * Return null if the piece can go here, or a reason why it can't.
   * Tiles in ignore (a uid or a collection of uids) are treated as already gone.
   */
  check(pieceId, q, r, layer, rotation, ignore = []) {
    ignore = new Set(typeof ignore === "number" ? [ignore] : ignore);
    const piece = this.pieces[pieceId];
    if (!piece.placeable) return `${piece.name} is only counted, not placed on the map`;
    const top = layer + piece.height - 1;
    if (layer < MIN_LAYER || layer > MAX_LAYER) return `Layers go from ${MIN_LAYER} to ${MAX_LAYER}`;
    if (top > MAX_LAYER) return `Too tall: it would go above layer ${MAX_LAYER}`;
    const cells = piece.cells(q, r, rotation);
    for (const [cq, cr] of cells) {
      if (!inBounds(cq, cr, this.size)) return "Off the edge of the map";
      for (let level = layer; level <= top; level++) {
        const other = this.cellMap.get(ck(cq, cr, level));
        if (other !== undefined && !ignore.has(other)) return "Another piece is already there";
      }
    }
    if (!this.followRules) return null;

    for (const [cq, cr] of piece.supportCells(q, r, rotation)) {
      const below = this.cellMap.get(ck(cq, cr, layer - 1));
      if (below === undefined || ignore.has(below)) {
        if (piece.kind === "walk") return "Each peg of a wall walk must sit on top of a wall or the doorway";
        if (layer > MIN_LAYER) return "Every hex needs a tile underneath it";
        continue;
      }
      const belowPiece = this.piece(this.tiles.get(below));
      if (piece.kind === "walk" && belowPiece.kind !== "castle_wall" && belowPiece.kind !== "doorway") {
        return "Each peg of a wall walk must sit on top of a wall or the doorway";
      }
      if (!belowPiece.acceptsOnTop(piece)) return `Nothing can go on top of ${blockerName(belowPiece)}`;
    }

    if (piece.kind === "stone_wall") {
      for (const [cq, cr] of piece.sideCells(q, r, rotation)) {
        const beside = this.cellMap.get(ck(cq, cr, layer));
        if (beside === undefined || ignore.has(beside)) return "A stone wall needs tiles on its layer along its whole length";
      }
    }
    if (piece.kind === "ladder" && !this.besideWall(cells[0], layer, ignore)) {
      return "A ladder must stand against a castle wall on the same layer";
    }

    for (const [cq, cr] of cells) {
      for (const [level, other] of this.column(cq, cr, ignore)) {
        const otherPiece = this.piece(other);
        if (this.topOf(other) < layer && otherPiece.blocksColumn) return `Nothing can go over ${blockerName(otherPiece)}`;
        if (level > top) {
          if (piece.blocksColumn) return `${capitalize(blockerName(piece))} can't go under another tile`;
          const restsHere = otherPiece.supportCells(other.q, other.r, other.rotation).some(([sq, sr]) => sq === cq && sr === cr);
          if (level === top + 1 && restsHere && !piece.acceptsOnTop(otherPiece)) {
            return `${capitalize(blockerName(piece))} can't go under another tile`;
          }
        }
      }
    }
    return null;
  }

  besideWall([q, r], layer, ignore) {
    for (const [dq, dr] of [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]]) {
      const uid = this.cellMap.get(ck(q + dq, r + dr, layer));
      if (uid === undefined || ignore.has(uid)) continue;
      const other = this.tiles.get(uid);
      const kind = this.piece(other).kind;
      if (other.layer === layer && (kind === "castle_wall" || kind === "doorway")) return true;
    }
    return false;
  }

  /**
   * The layer a wall walk snaps to here: one above the walls under its pegs.
   * null if a peg has no wall or doorway under it, or the walls aren't all the same height.
   */
  walkLayer(pieceId, q, r, rotation, ignore = []) {
    ignore = new Set(ignore);
    const piece = this.pieces[pieceId];
    const tops = new Set();
    for (const [cq, cr] of piece.supportCells(q, r, rotation)) {
      const walls = this.column(cq, cr, ignore)
        .map(([, t]) => t)
        .filter((t) => ["castle_wall", "doorway"].includes(this.piece(t).kind))
        .map((t) => this.topOf(t));
      if (!walls.length) return null;
      tops.add(Math.max(...walls));
    }
    return tops.size === 1 ? [...tops][0] + 1 : null;
  }

  /** Wall walks resting on this wall or doorway. */
  walksOn(tile) {
    if (!["castle_wall", "doorway"].includes(this.piece(tile).kind)) return [];
    const cells = new Set(this.cellsOf(tile).map(([q, r]) => `${q},${r}`));
    const top = this.topOf(tile);
    const result = [];
    for (const other of this.tiles.values()) {
      const piece = this.piece(other);
      if (piece.kind === "walk" && other.layer === top + 1) {
        if (piece.supportCells(other.q, other.r, other.rotation).some(([q, r]) => cells.has(`${q},${r}`))) result.push(other);
      }
    }
    return result;
  }

  /** True if every tile would still be on a map of this size. */
  fits(sizeName) {
    const size = MAP_SIZES[sizeName];
    for (const t of this.tiles.values()) {
      for (const [q, r] of this.cellsOf(t)) if (!inBounds(q, r, size)) return false;
    }
    return true;
  }

  /** True if another piece (not in ignore) needs this one to stay where it is. */
  supportsOthers(tile, ignore = []) {
    ignore = new Set([...ignore, tile.uid]);
    for (const other of this.tiles.values()) {
      if (ignore.has(other.uid)) continue;
      const args = [other.pieceId, other.q, other.r, other.layer, other.rotation];
      if (this.check(...args, [other.uid]) === null && this.check(...args, [other.uid, tile.uid])) return true;
    }
    return false;
  }

  /** Add a tile without checking the rules. Assigns a uid if it has none. */
  add(tile) {
    if (!tile.uid) tile.uid = this.nextUid;
    this.nextUid = Math.max(this.nextUid, tile.uid + 1);
    this.tiles.set(tile.uid, tile);
    for (const [cq, cr] of this.cellsOf(tile)) {
      for (let layer = tile.layer; layer <= this.topOf(tile); layer++) this.cellMap.set(ck(cq, cr, layer), tile.uid);
    }
    // Keep placement order when a tile is put back by undo.
    this.tiles = new Map([...this.tiles.entries()].sort((a, b) => a[0] - b[0]));
    return tile;
  }

  remove(uid) {
    const tile = this.tiles.get(uid);
    this.tiles.delete(uid);
    for (const [cq, cr] of this.cellsOf(tile)) {
      for (let layer = tile.layer; layer <= this.topOf(tile); layer++) {
        if (this.cellMap.get(ck(cq, cr, layer)) === uid) this.cellMap.delete(ck(cq, cr, layer));
      }
    }
    return tile;
  }

  move(uid, q, r, rotation, layer = null) {
    const tile = this.remove(uid);
    tile.q = q;
    tile.r = r;
    tile.rotation = ((rotation % 6) + 6) % 6;
    if (layer !== null) tile.layer = layer;
    this.add(tile);
    return tile;
  }

  usedCounts() {
    const counts = Object.fromEntries(Object.keys(this.pieces).map((id) => [id, 0]));
    for (const tile of this.tiles.values()) counts[tile.pieceId] += this.piece(tile).uses;
    return counts;
  }

  /** Tiles placed beyond what is owned: the most recently placed ones. */
  overLimitUids(owned) {
    const seen = {};
    const over = new Set();
    for (const tile of this.tiles.values()) {
      seen[tile.pieceId] = (seen[tile.pieceId] || 0) + this.piece(tile).uses;
      if (seen[tile.pieceId] > (owned[tile.pieceId] || 0)) over.add(tile.uid);
    }
    return over;
  }

  /**
   * For each hex, the highest layer filled by a piece starting at or below this layer.
   * Returns Map "q,r" -> [top layer, uid of that piece].
   */
  topNumbers(layer) {
    const result = new Map();
    for (const tile of this.tiles.values()) {
      if (tile.layer > layer) continue;
      const top = this.topOf(tile);
      for (const [q, r] of this.cellsOf(tile)) {
        const k = `${q},${r}`;
        if (!result.has(k) || top > result.get(k)[0]) result.set(k, [top, tile.uid]);
      }
    }
    return result;
  }
}
