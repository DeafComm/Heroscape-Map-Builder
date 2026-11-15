// The map space: draws the hex grid and tiles, and handles placing tiles.

import { fromOffset, hexCorners, hexToPixel, pixelToHex, rotate } from "./hexgrid.js";
import { GroupCommand, MoveCommand, PlaceCommand, RemoveCommand } from "./history.js";
import { MAX_LAYER, makeTile } from "./model.js";
import { HEX_RADIUS, WHITE, blend, css, hex, hexPath, outlinePath, paintDetails, terrainColour, textColour } from "./drawing.js";

const BACKGROUND = "#3a3f44";
const GRID_FILL = "#f4f1ea";
const GRID_LINE = "#d6d0c4";
const OVER_LIMIT = "#e01b1b";
const SELECTED = "#ffd400";
const GHOST_OK = "#1f9d3a";
const OUTLINE = hex("#1d1d1d");
// Tiles below the current layer are washed towards white: the layer just below a little,
// and each layer further down a little more, up to a limit so the colour still shows.
const WHITE_WASH_STEP = 0.25;
const WHITE_WASH_MAX = 0.6;

// Scene units are scaled by this at 100% zoom, so a hex is about 22 pixels from centre to corner.
const VIEW_SCALE = 1.08;
export const MIN_ZOOM = 75;
export const MAX_ZOOM = 125;
const DRAG_DISTANCE = 4; // pixels the mouse moves before a press becomes a drag

const ACTIVE = "active", BELOW = "below", ABOVE = "above";

export class MapView {
  constructor(canvas, paletteElement) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.paletteElement = paletteElement; // dropping a tile here removes it
    this.model = null;
    this.history = null;
    this.owned = {};
    this.showOverLimit = true; // the Red Border checkbox
    this.activeLayer = 1;
    this.zoom = 100;
    this.centre = [0, 0]; // the scene point in the middle of the view
    this.selected = []; // uids of selected tiles; the last one is the one clicked most recently
    this.lastPlaced = null; // [uid, pieceId, rotation] of the newest tile, for right-click copies
    this.carry = null;
    this.press = null; // {uid, x, y, hex} of a press on a placed tile
    this.pan = null;
    this.enabled = true;
    // Things the app listens for.
    this.onChanged = () => {};
    this.onMessage = () => {};

    canvas.addEventListener("pointerdown", (e) => this.pointerDown(e));
    window.addEventListener("pointermove", (e) => this.pointerMove(e));
    window.addEventListener("pointerup", (e) => this.pointerUp(e));
    canvas.addEventListener("contextmenu", (e) => e.preventDefault());
    canvas.addEventListener("wheel", (e) => this.wheel(e), { passive: false });
    canvas.addEventListener("pointerleave", () => {
      if (this.carry && this.carry.sticky) {
        this.carry.pos = null;
        this.refresh();
      }
    });
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
  }

  // --- document -----------------------------------------------------

  setDocument(model, history) {
    this.model = model;
    this.history = history;
    this.selected = [];
    this.lastPlaced = null;
    this.cancelCarry();
    this.rebuild();
  }

  /** Redraw the grid after a new map or a change of map size. */
  rebuild() {
    const size = this.model.size;
    const grid = new Path2D();
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (let row = 0; row < size; row++) {
      for (let col = 0; col < size; col++) {
        const [q, r] = fromOffset(col, row);
        const pts = hexCorners(...hexToPixel(q, r, HEX_RADIUS), HEX_RADIUS);
        grid.moveTo(...pts[0]);
        for (let i = 1; i < 6; i++) grid.lineTo(...pts[i]);
        grid.closePath();
        for (const [x, y] of pts) {
          minX = Math.min(minX, x); maxX = Math.max(maxX, x);
          minY = Math.min(minY, y); maxY = Math.max(maxY, y);
        }
      }
    }
    this.grid = grid;
    const m = HEX_RADIUS;
    this.sceneRect = { x0: minX - m, y0: minY - m, x1: maxX + m, y1: maxY + m };
    this.centre = [(this.sceneRect.x0 + this.sceneRect.x1) / 2, (this.sceneRect.y0 + this.sceneRect.y1) / 2];
    this.refresh();
  }

  setActiveLayer(layer) {
    this.activeLayer = layer;
    this.refresh();
  }

  setShowOverLimit(show) {
    this.showOverLimit = show;
    this.refresh();
  }

  setOwned(owned) {
    this.owned = owned;
    this.refresh();
  }

  get scale() { return (VIEW_SCALE * this.zoom) / 100; }

  /** Zoom to percent of the normal tile size, keeping the same spot in the middle. */
  setZoom(percent) {
    this.zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.round(percent)));
    this.refresh();
  }

  resize() {
    const box = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.width = Math.max(1, Math.floor(box.width));
    this.height = Math.max(1, Math.floor(box.height));
    this.canvas.width = this.width * dpr;
    this.canvas.height = this.height * dpr;
    this.canvas.style.width = `${this.width}px`;
    this.canvas.style.height = `${this.height}px`;
    this.refresh();
  }

  /** Keep the view over the map, like scroll bars do. */
  clampCentre() {
    if (!this.sceneRect) return;
    const s = this.scale, rect = this.sceneRect;
    const halfW = this.width / 2 / s, halfH = this.height / 2 / s;
    const fit = (c, lo, hi, half) => (hi - lo <= 2 * half ? (lo + hi) / 2 : Math.max(lo + half, Math.min(hi - half, c)));
    this.centre = [fit(this.centre[0], rect.x0, rect.x1, halfW), fit(this.centre[1], rect.y0, rect.y1, halfH)];
  }

  refresh() {
    if (!this.model) return;
    this.selected = this.selected.filter((uid) => this.model.tiles.has(uid));
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = null;
      this.draw();
    });
  }

  // --- coordinates --------------------------------------------------

  toScene(clientX, clientY) {
    const box = this.canvas.getBoundingClientRect();
    const s = this.scale;
    return [(clientX - box.left - this.width / 2) / s + this.centre[0], (clientY - box.top - this.height / 2) / s + this.centre[1]];
  }

  hexAt(clientX, clientY) {
    return pixelToHex(...this.toScene(clientX, clientY), HEX_RADIUS);
  }

  overCanvas(clientX, clientY) {
    const b = this.canvas.getBoundingClientRect();
    return clientX >= b.left && clientX < b.right && clientY >= b.top && clientY < b.bottom;
  }

  overPalette(clientX, clientY) {
    const el = this.paletteElement;
    if (!el || !el.offsetParent) return false;
    const b = el.getBoundingClientRect();
    return clientX >= b.left && clientX < b.right && clientY >= b.top && clientY < b.bottom;
  }

  // --- drawing ------------------------------------------------------

  draw() {
    const ctx = this.ctx;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = BACKGROUND;
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    if (!this.model) return;
    this.clampCentre();
    const s = this.scale;
    ctx.setTransform(dpr * s, 0, 0, dpr * s, dpr * (this.width / 2 - this.centre[0] * s), dpr * (this.height / 2 - this.centre[1] * s));
    ctx.lineJoin = "round";

    ctx.fillStyle = GRID_FILL;
    ctx.fill(this.grid);
    ctx.strokeStyle = GRID_LINE;
    ctx.lineWidth = 1;
    ctx.stroke(this.grid);

    const model = this.model;
    const over = this.showOverLimit ? model.overLimitUids(this.owned) : new Set();
    const moving = this.movingUids();
    // Each hex shows the number of the highest layer filled at or below the current one.
    const numbers = new Map();
    for (const [cell, [top, uid]] of model.topNumbers(this.activeLayer)) {
      if (!numbers.has(uid)) numbers.set(uid, []);
      numbers.get(uid).push([cell, top]);
    }
    const items = [];
    let order = 0;
    for (const [uid, tile] of model.tiles) {
      if (moving.has(uid)) continue;
      const piece = model.piece(tile);
      const item = { piece, tile, numbers: numbers.get(uid) || [], state: ACTIVE, wash: 0, order: order++ };
      // Overages only show on the layer being worked on.
      item.overLimit = over.has(uid) && tile.layer === this.activeLayer;
      item.selected = this.selected.includes(uid);
      if (tile.layer > this.activeLayer) item.state = ABOVE;
      else if (tile.layer < this.activeLayer) {
        item.state = BELOW;
        item.wash = Math.min(WHITE_WASH_STEP * (this.activeLayer - tile.layer), WHITE_WASH_MAX);
      }
      // Tall pieces sit over the tiles beside them.
      item.z = (tile.layer + piece.height - 1) * 10;
      items.push(item);
    }
    for (const ghost of this.ghosts()) items.push({ ...ghost, order: order++ });
    items.sort((a, b) => a.z - b.z || a.order - b.order);
    for (const item of items) this.paintTile(ctx, item);
  }

  paintTile(ctx, item) {
    const { piece, tile } = item;
    const cells = piece.cells(tile.q, tile.r, tile.rotation);
    ctx.save();
    if (item.state === ABOVE) ctx.globalAlpha = 0.25;
    let fill = terrainColour(piece.terrain, tile.layer);
    if (item.wash) fill = blend(fill, WHITE, item.wash);
    ctx.fillStyle = css(fill, item.ghost ? 150 / 255 : 1);
    ctx.strokeStyle = "rgba(0,0,0,0.2)";
    ctx.lineWidth = 0.8;
    for (const [q, r] of cells) {
      ctx.beginPath();
      hexPath(ctx, q, r);
      ctx.fill();
      ctx.stroke();
    }
    paintDetails(ctx, piece, tile.q, tile.r, tile.rotation, HEX_RADIUS, item.wash, WHITE);

    ctx.beginPath();
    outlinePath(ctx, cells);
    if (item.ghost) {
      ctx.strokeStyle = item.blocked ? OVER_LIMIT : GHOST_OK;
      ctx.lineWidth = 3;
      ctx.setLineDash([12, 6]);
    } else if (item.overLimit) {
      ctx.strokeStyle = OVER_LIMIT;
      ctx.lineWidth = 6;
    } else if (item.state === BELOW) {
      // Edges fade with the wash, so the layer just below keeps clear outlines.
      ctx.strokeStyle = css(blend(OUTLINE, WHITE, item.wash));
      ctx.lineWidth = 1.5;
    } else {
      ctx.strokeStyle = css(OUTLINE);
      ctx.lineWidth = 1.8;
    }
    ctx.stroke();
    ctx.setLineDash([]);
    if (item.selected && !item.ghost) {
      // Drawn on top so a tile that is over the inventory keeps its red edge.
      ctx.strokeStyle = SELECTED;
      ctx.lineWidth = item.overLimit ? 3 : 4;
      ctx.stroke();
    }

    if (item.numbers.length) {
      ctx.font = `bold ${Math.floor(HEX_RADIUS * 0.75)}px system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const text = textColour(fill);
      const light = text === WHITE;
      for (const [cell, number] of item.numbers) {
        const [q, r] = cell.split(",").map(Number);
        const [cx, cy] = hexToPixel(q, r, HEX_RADIUS);
        // A dark outline keeps the number readable over tree tops and wall lines.
        ctx.strokeStyle = light ? "rgba(0,0,0,0.67)" : "rgba(255,255,255,0.67)";
        ctx.lineWidth = 2.2;
        ctx.strokeText(String(number), cx, cy + 1);
        ctx.fillStyle = css(text);
        ctx.fillText(String(number), cx, cy + 1);
      }
    }
    ctx.restore();
  }

  // --- selection ----------------------------------------------------

  get selectedUid() {
    return this.selected.length ? this.selected[this.selected.length - 1] : null;
  }

  select(uids) {
    this.selected = [...uids];
    this.refresh();
  }

  clearSelection() { this.select([]); }

  // --- carrying tiles -----------------------------------------------

  /** Pick up a new piece from the piece list. */
  startCarry(pieceId, { rotation = 0, grab = [0, 0], sticky = false, from = null } = {}) {
    this.cancelCarry();
    this.carry = {
      pieceId,
      rotation: ((rotation % 6) + 6) % 6,
      grab, // offset from the piece's anchor to the hex under the cursor
      members: null,
      sticky, // keeps placing copies until cancelled
      from, // where a press on the piece list started, to tell a click from a drag
      pos: from,
    };
    this.canvas.style.cursor = "grabbing";
    document.body.classList.add("carrying");
    this.refresh();
  }

  /** Pick up placed tiles to move them together, holding them at grabHex. */
  startMove(uids, [gq, gr]) {
    this.cancelCarry();
    const members = uids.map((uid) => {
      const tile = this.model.tiles.get(uid);
      return { uid, off: [tile.q - gq, tile.r - gr], rotation: tile.rotation };
    });
    this.carry = { pieceId: null, members, sticky: false, from: null, pos: null };
    this.canvas.style.cursor = "grabbing";
    document.body.classList.add("carrying");
    this.refresh();
  }

  movingUids() {
    if (!this.carry || !this.carry.members) return new Set();
    return new Set(this.carry.members.map((m) => m.uid));
  }

  makeSticky() {
    if (this.carry && !this.carry.members) {
      this.carry.sticky = true;
      this.carry.from = null;
      this.onMessage("Click on the map to place copies. Right-click or press Esc to stop.");
    }
  }

  cancelCarry() {
    if (!this.carry) return;
    this.carry = null;
    this.canvas.style.cursor = "";
    document.body.classList.remove("carrying");
    this.refresh();
  }

  carryMove(clientX, clientY) {
    if (!this.carry) return;
    this.carry.pos = [clientX, clientY];
    this.refresh();
  }

  /** Drop what is being carried at the given point. */
  carryRelease(clientX, clientY) {
    if (!this.carry) return;
    const carry = this.carry;
    const moving = this.movingUids();
    if (this.overCanvas(clientX, clientY)) {
      this.drop(clientX, clientY);
      if (!carry.sticky) this.cancelCarry();
    } else if (moving.size && this.overPalette(clientX, clientY)) {
      this.cancelCarry();
      this.deleteTiles([...moving]);
    } else {
      this.cancelCarry();
    }
  }

  /** [pieceId, q, r, layer, rotation, uid] for everything carried, dropped at the given point. */
  targets(clientX, clientY) {
    const [q, r] = this.hexAt(clientX, clientY);
    const carry = this.carry;
    if (!carry.members) {
      const [gq, gr] = carry.grab;
      const layer = this.layerFor(carry.pieceId, q - gq, r - gr, carry.rotation, this.activeLayer);
      return [[carry.pieceId, q - gq, r - gr, layer, carry.rotation, null]];
    }
    const moving = this.movingUids();
    return carry.members.map((m) => {
      const tile = this.model.tiles.get(m.uid);
      const [oq, or] = m.off;
      const layer = this.layerFor(tile.pieceId, q + oq, r + or, m.rotation, tile.layer, moving);
      return [tile.pieceId, q + oq, r + or, layer, m.rotation, m.uid];
    });
  }

  /** Wall walks go on top of the walls under them, whatever layer is showing. */
  layerFor(pieceId, q, r, rotation, fallback, ignore = []) {
    if (this.model.pieces[pieceId].kind === "walk") return this.model.walkLayer(pieceId, q, r, rotation, ignore) || fallback;
    return fallback;
  }

  problem(targets) {
    const ignore = targets.map((t) => t[5]).filter((uid) => uid !== null);
    for (const [pieceId, q, r, layer, rotation] of targets) {
      const problem = this.model.check(pieceId, q, r, layer, rotation, ignore);
      if (problem) return problem;
    }
    return null;
  }

  drop(clientX, clientY) {
    const targets = this.targets(clientX, clientY);
    const problem = this.problem(targets);
    if (this.carry.members) {
      if (problem) return this.onMessage(`Can't move there: ${problem}`);
      const moves = [];
      for (const [, q, r, layer, rotation, uid] of targets) {
        const tile = this.model.tiles.get(uid);
        if (q !== tile.q || r !== tile.r || rotation !== tile.rotation || layer !== tile.layer) {
          moves.push(new MoveCommand(tile, q, r, rotation, layer));
        }
      }
      if (moves.length) {
        this.history.push(this.model, new GroupCommand(moves));
        this.selected = targets.map((t) => t[5]);
        this.onChanged();
      }
      return;
    }
    if (problem) return this.onMessage(`Can't place there: ${problem}`);
    const [pieceId, q, r, layer, rotation] = targets[0];
    this.place(pieceId, q, r, rotation, layer);
  }

  /** Place a new tile (on the current layer unless told otherwise) and leave it selected. */
  place(pieceId, q, r, rotation, layer = null) {
    const tile = makeTile(0, pieceId, q, r, layer ?? this.activeLayer, rotation);
    this.history.push(this.model, new PlaceCommand(tile));
    this.selected = [tile.uid];
    this.lastPlaced = [tile.uid, pieceId, rotation];
    this.onChanged();
  }

  /** Right-click: place another of the most recently placed tile at the mouse. */
  placeCopy(clientX, clientY) {
    if (!this.lastPlaced) return this.onMessage("Place a tile first, then right-click to place more of it");
    let [uid, pieceId, rotation] = this.lastPlaced;
    if (this.model.tiles.has(uid)) rotation = this.model.tiles.get(uid).rotation; // follow any rotation since
    const [q, r] = this.hexAt(clientX, clientY);
    const layer = this.layerFor(pieceId, q, r, rotation, this.activeLayer);
    const problem = this.model.check(pieceId, q, r, layer, rotation);
    if (problem) return this.onMessage(`Can't place there: ${problem}`);
    this.place(pieceId, q, r, rotation, layer);
  }

  ghosts() {
    if (!this.carry || !this.carry.pos) return [];
    const [x, y] = this.carry.pos;
    if (!this.overCanvas(x, y)) return [];
    const targets = this.targets(x, y);
    const blocked = this.problem(targets) !== null;
    return targets.map(([pieceId, q, r, layer, rotation]) => {
      const piece = this.model.pieces[pieceId];
      return {
        piece, tile: { q, r, layer, rotation }, ghost: true, blocked, numbers: [], state: ACTIVE, wash: 0,
        z: (layer + piece.height - 1) * 10 + 5,
      };
    });
  }

  // --- editing placed tiles -----------------------------------------

  /** Turn what is carried, or the selected tiles as one block, by 60 degree steps. */
  rotate(steps = 1) {
    if (this.carry) {
      if (!this.carry.members) {
        this.carry.rotation = (((this.carry.rotation + steps) % 6) + 6) % 6;
        this.carry.grab = rotate(...this.carry.grab, steps);
      } else {
        for (const m of this.carry.members) {
          m.off = rotate(...m.off, steps);
          m.rotation = (((m.rotation + steps) % 6) + 6) % 6;
        }
      }
      this.refresh();
      return;
    }
    if (!this.selected.length) return;
    // Turn around the most recently clicked tile.
    const pivot = this.model.tiles.get(this.selectedUid);
    const targets = this.selected.map((uid) => {
      const tile = this.model.tiles.get(uid);
      const [oq, or] = rotate(tile.q - pivot.q, tile.r - pivot.r, steps);
      const q = pivot.q + oq, r = pivot.r + or, rotation = (((tile.rotation + steps) % 6) + 6) % 6;
      const layer = this.layerFor(tile.pieceId, q, r, rotation, tile.layer, this.selected);
      return [tile.pieceId, q, r, layer, rotation, uid];
    });
    const problem = this.problem(targets);
    if (problem) return this.onMessage(`Can't rotate: ${problem}`);
    const moves = targets.map((t) => new MoveCommand(this.model.tiles.get(t[5]), t[1], t[2], t[4], t[3]));
    this.history.push(this.model, new GroupCommand(moves));
    this.onChanged();
  }

  /** Remove the given tiles, or the selected ones. */
  deleteTiles(uids = null) {
    uids = [...(uids ?? this.selected)];
    if (!uids.length) return;
    // Walks resting on a wall go with it.
    for (const uid of [...uids]) {
      for (const walk of this.model.walksOn(this.model.tiles.get(uid))) {
        if (!uids.includes(walk.uid)) uids.push(walk.uid);
      }
    }
    if (this.model.followRules) {
      for (const uid of uids) {
        if (this.model.supportsOthers(this.model.tiles.get(uid), uids)) {
          this.onMessage("Can't remove a piece that other pieces rest on or stand against");
          this.refresh();
          return;
        }
      }
    }
    const removes = uids.map((uid) => new RemoveCommand(this.model.tiles.get(uid)));
    this.history.push(this.model, new GroupCommand(removes));
    this.selected = this.selected.filter((uid) => !uids.includes(uid));
    this.onChanged();
  }

  // --- mouse --------------------------------------------------------

  /**
   * The piece a click on this hex picks up.
   * A wall walk can be picked from any layer, except that on a wall's own layer the wall is
   * picked. Otherwise it's the piece standing on the current layer (tall pieces are picked on
   * the layer they stand on).
   */
  pick(q, r) {
    let tile = this.model.tileAt(q, r, this.activeLayer);
    if (tile && tile.layer !== this.activeLayer) tile = null;
    if (tile && ["castle_wall", "doorway", "walk"].includes(this.model.piece(tile).kind)) return tile;
    for (let layer = MAX_LAYER; layer > 0; layer--) {
      const other = this.model.tileAt(q, r, layer);
      if (other && this.model.piece(other).kind === "walk") return other;
    }
    return tile;
  }

  pointerDown(e) {
    if (!this.model || !this.enabled) return;
    this.canvas.focus();
    const { clientX: x, clientY: y } = e;
    if (e.button === 1) {
      // Middle-drag scrolls the map.
      e.preventDefault();
      this.pan = { x, y, centre: [...this.centre] };
      return;
    }
    if (this.carry) {
      if (e.button === 0 && this.carry.sticky) this.drop(x, y);
      else if (e.button === 2) this.cancelCarry();
      return;
    }
    if (e.button === 2) return this.placeCopy(x, y);
    if (e.button !== 0) return;
    const [q, r] = this.hexAt(x, y);
    const tile = this.pick(q, r);
    this.press = null;
    if (e.ctrlKey || e.metaKey) {
      // Ctrl+click adds a tile to the selection, or takes it out.
      if (tile) {
        const i = this.selected.indexOf(tile.uid);
        if (i >= 0) this.selected.splice(i, 1);
        else {
          this.selected.push(tile.uid);
          this.press = { uid: tile.uid, x, y, hex: [q, r], ctrl: true };
        }
      }
      this.refresh();
      return;
    }
    if (!tile) return this.clearSelection();
    if (this.selected.includes(tile.uid)) {
      // Keep a multi-selection so it can be dragged as one block.
      this.selected = this.selected.filter((uid) => uid !== tile.uid);
      this.selected.push(tile.uid);
    } else {
      this.selected = [tile.uid];
    }
    this.press = { uid: tile.uid, x, y, hex: [q, r], ctrl: false };
    this.refresh();
  }

  pointerMove(e) {
    const { clientX: x, clientY: y } = e;
    if (this.pan) {
      const s = this.scale;
      this.centre = [this.pan.centre[0] - (x - this.pan.x) / s, this.pan.centre[1] - (y - this.pan.y) / s];
      this.refresh();
      return;
    }
    if (this.carry) return this.carryMove(x, y);
    if (this.press && e.buttons & 1) {
      if (Math.abs(x - this.press.x) + Math.abs(y - this.press.y) >= DRAG_DISTANCE) {
        const grab = this.press.hex;
        this.press = null;
        this.startMove([...this.selected], grab);
        this.carryMove(x, y);
      }
    }
  }

  pointerUp(e) {
    const { clientX: x, clientY: y } = e;
    if (e.button === 1) {
      this.pan = null;
      return;
    }
    if (this.press && e.button === 0 && !this.press.ctrl) {
      // A plain click without dragging selects just that tile.
      const uid = this.press.uid;
      if (this.selected.length !== 1 || this.selected[0] !== uid) this.select([uid]);
    }
    this.press = null;
    if (!this.carry || this.carry.sticky || e.button !== 0) return;
    const from = this.carry.from;
    if (from) {
      // Let go of a piece picked up from the piece list.
      const moved = Math.abs(x - from[0]) + Math.abs(y - from[1]) >= DRAG_DISTANCE;
      if (!moved && !this.overCanvas(x, y)) {
        // A click: keep the piece and place copies with each click on the map.
        this.makeSticky();
        return;
      }
    }
    this.carryRelease(x, y);
  }

  /** The wheel scrolls up and down; Ctrl or Shift + wheel (or a sideways wheel) scrolls left and right. */
  wheel(e) {
    e.preventDefault();
    let dx = e.deltaX, dy = e.deltaY;
    if (e.deltaMode === 1) { dx *= 40; dy *= 40; }
    if (e.ctrlKey || e.shiftKey) {
      dx = dx || dy;
      dy = 0;
    }
    const s = this.scale;
    this.centre = [this.centre[0] + dx / s, this.centre[1] + dy / s];
    this.refresh();
  }
}
