// A 3D view of the map: an isometric picture of the placed tiles that spins in place and zooms,
// but can't be edited.

import { EDGE_NEIGHBOURS, hexCorners, hexToPixel } from "./hexgrid.js";
import { HEX_RADIUS, WHITE, blend, css, hex, stoneWallLine, terrainColour } from "./drawing.js";

const LAYER_HEIGHT = HEX_RADIUS * 0.5; // a bit thicker than the real tiles, so layers read clearly
const ELEVATION = (30 * Math.PI) / 180; // the fixed tilt of the camera
export const TURN_STEP = 15; // degrees per press of Q or E
const DRAG_TURN = 0.4; // degrees per pixel of right-drag
const MIN_SCALE = 0.2, MAX_SCALE = 6.0;
const SEAM_SCALE = 1.6; // zoomed in at least this far, the lines between stacked layers show

const BACKGROUND = "#3a3f44";
const SIDE_TAN = hex("#c9a777"); // the sides of the real tiles
const SIDE_STONE = hex("#a9a397"); // castle parts and roads are grey plastic
const TOP_STONE = hex("#c9c3b7");
const TRUNK = hex("#7a5230");
const LEAVES = hex("#2f6b35");
const LADDER = hex("#9a6a3a");
const OUTLINE = "rgba(40,30,20,0.47)";
const STONE_KINDS = ["castle_wall", "doorway", "walk", "stone_wall"];

function prism(points, z0, z1, top, side, { hidden = [], coverTop = false, seam = false } = {}) {
  const n = points.length;
  return {
    type: "prism", points, z0, z1, top, side, hidden: new Set(hidden), coverTop, seam,
    centre: [points.reduce((s, p) => s + p[0], 0) / n, points.reduce((s, p) => s + p[1], 0) / n],
  };
}

function cone(cx, cy, radius, z0, z1, colour) {
  return { type: "cone", centre: [cx, cy], radius, z0, z1, colour };
}

/** Convex hull of 2D points (monotone chain). */
function hull(points) {
  const seen = new Map();
  for (const [x, y] of points) seen.set(`${x.toFixed(2)},${y.toFixed(2)}`, [Number(x.toFixed(2)), Number(y.toFixed(2))]);
  const pts = [...seen.values()].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (pts.length < 3) return pts;
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower = [], upper = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  for (const p of [...pts].reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  return lower.slice(0, -1).concat(upper.slice(0, -1));
}

/** Turn the map into solids to draw. Only tiles starting at or below maxLayer, if given. */
export function buildSolids(model, maxLayer = null) {
  const tiles = [...model.tiles.values()].filter((t) => maxLayer === null || t.layer <= maxLayer);
  const occupied = new Map(); // "q,r,layer" -> tile, for working out hidden faces
  for (const t of tiles) {
    for (const [q, r] of model.cellsOf(t)) {
      for (let layer = t.layer; layer <= model.topOf(t); layer++) occupied.set(`${q},${r},${layer}`, t);
    }
  }
  const solidTile = (q, r, layer) => {
    const other = occupied.get(`${q},${r},${layer}`);
    return Boolean(other) && ["tile", "walk"].includes(model.piece(other).kind);
  };

  const solids = [];
  const R = HEX_RADIUS, T = LAYER_HEIGHT;
  for (const t of tiles) {
    const piece = model.piece(t);
    const cells = model.cellsOf(t);
    const z0 = (t.layer - 1) * T;
    const z1 = model.topOf(t) * T;
    const kind = piece.kind;
    const stone = STONE_KINDS.includes(kind) || piece.terrain === "road";
    const side = stone ? SIDE_STONE : SIDE_TAN;
    const top = STONE_KINDS.includes(kind) ? TOP_STONE : terrainColour(piece.terrain, t.layer);
    if (kind === "tile" || kind === "walk") {
      for (const [q, r] of cells) {
        const points = hexCorners(...hexToPixel(q, r, R), R);
        const hidden = [];
        EDGE_NEIGHBOURS.forEach(([dq, dr], i) => solidTile(q + dq, r + dr, t.layer) && hidden.push(i));
        solids.push(prism(points, z0, z1, top, side, { hidden, coverTop: solidTile(q, r, t.layer + 1), seam: true }));
      }
    } else if (kind === "tree") {
      const px = cells.map(([q, r]) => hexToPixel(q, r, R));
      const cx = px.reduce((s, p) => s + p[0], 0) / px.length, cy = px.reduce((s, p) => s + p[1], 0) / px.length;
      const spread = cells.length === 1 ? 1 : 1.9;
      const height = z1 - z0;
      solids.push(prism(hexCorners(cx, cy, R * 0.16 * spread), z0, z0 + height * 0.3, TRUNK, TRUNK));
      solids.push(cone(cx, cy, R * 0.85 * spread, z0 + height * 0.15, z0 + height * 0.7, LEAVES));
      solids.push(cone(cx, cy, R * 0.6 * spread, z0 + height * 0.45, z1, blend(LEAVES, WHITE, 0.08)));
    } else if (kind === "castle_wall") {
      solids.push(prism(hexCorners(...hexToPixel(...cells[0], R), R * 0.9), z0, z1, top, side));
    } else if (kind === "doorway") {
      cells.forEach(([q, r], i) => {
        if (i === 0 || i === cells.length - 1) {
          solids.push(prism(hexCorners(...hexToPixel(q, r, R), R * 0.9), z0, z1, top, side));
        } else {
          // The arch over the way through.
          solids.push(prism(hexCorners(...hexToPixel(q, r, R), R), z1 - 2 * T, z1, top, side));
        }
      });
    } else if (kind === "ladder") {
      solids.push(prism(hexCorners(...hexToPixel(...cells[0], R), R * 0.3), z0, z1, LADDER, LADDER));
    } else if (kind === "stone_wall") {
      solids.push(prism(stoneWallFootprint(piece, t), z0, z0 + 3 * T, top, side));
    }
  }
  return solids;
}

/** A thin slab along the edge of the row of tiles the wall stands against. */
function stoneWallFootprint(piece, tile) {
  const R = HEX_RADIUS;
  const [a0, b0, n] = stoneWallLine(piece, tile.q, tile.r, tile.rotation, R, 1);
  const [ux, uy] = n.u, nx = n.nx, ny = n.ny;
  const ext = R * 0.87, off = R * 0.75, half = R * 0.15;
  const a = [a0[0] - ux * ext + nx * off, a0[1] - uy * ext + ny * off];
  const b = [b0[0] + ux * ext + nx * off, b0[1] + uy * ext + ny * off];
  return [
    [a[0] - nx * half, a[1] - ny * half],
    [b[0] - nx * half, b[1] - ny * half],
    [b[0] + nx * half, b[1] + ny * half],
    [a[0] + nx * half, a[1] + ny * half],
  ];
}

export class Map3DView {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.model = null;
    this.angle = 0; // degrees, turned around the middle of the map
    this.scale = 1;
    this.cutLayer = null; // only show tiles starting at or below this layer
    this.solids = [];
    this.drag = null; // last x of a right-drag
    this.centre = [0, 0];
    this.midHeight = 0;
    this.needsFit = true;
    this.visible = false;
    canvas.addEventListener("contextmenu", (e) => e.preventDefault());
    canvas.addEventListener("pointerdown", (e) => {
      // Only the right button does anything: it spins the map in place.
      if (e.button === 2) {
        this.drag = e.clientX;
        canvas.setPointerCapture(e.pointerId);
        canvas.style.cursor = "ew-resize";
      }
    });
    canvas.addEventListener("pointermove", (e) => {
      if (this.drag === null) return;
      this.turn((e.clientX - this.drag) * DRAG_TURN);
      this.drag = e.clientX;
    });
    canvas.addEventListener("pointerup", (e) => {
      if (e.button === 2) {
        this.drag = null;
        canvas.style.cursor = "";
      }
    });
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const steps = -e.deltaY / (e.deltaMode === 1 ? 3 : 100);
      if (steps) this.zoomBy(1.15 ** steps);
    }, { passive: false });
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
  }

  setModel(model) {
    this.model = model;
    this.needsFit = true;
    this.refresh();
  }

  setCutLayer(layer) {
    this.cutLayer = layer;
    this.refresh();
  }

  refresh() {
    if (!this.model || !this.visible) return;
    this.solids = buildSolids(this.model, this.cutLayer);
    this.update();
  }

  update() {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = null;
      this.draw();
    });
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
    if (this.needsFit) this.fit();
    this.update();
  }

  /** The middle of the placed tiles, which the view spins around. */
  tilesCentre() {
    const pts = [];
    for (const t of this.model.tiles.values()) for (const [q, r] of this.model.cellsOf(t)) pts.push(hexToPixel(q, r, HEX_RADIUS));
    if (!pts.length) return [0, 0];
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
  }

  /** Turn back to the start and zoom so the tiles fit, however the view is spun. */
  fit() {
    if (!this.model || !this.width || this.width < 10) return;
    this.angle = 0;
    this.centre = this.tilesCentre();
    let reach = HEX_RADIUS * 3, top = LAYER_HEIGHT;
    for (const t of this.model.tiles.values()) {
      top = Math.max(top, this.model.topOf(t) * LAYER_HEIGHT);
      for (const [q, r] of this.model.cellsOf(t)) {
        const [x, y] = hexToPixel(q, r, HEX_RADIUS);
        reach = Math.max(reach, Math.hypot(x - this.centre[0], y - this.centre[1]) + HEX_RADIUS);
      }
    }
    const width = 2 * reach;
    const height = 2 * reach * Math.sin(ELEVATION) + top * Math.cos(ELEVATION);
    this.scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, 0.9 * Math.min(this.width / width, this.height / height)));
    this.midHeight = top / 2; // keeps tall builds in the middle of the view
    this.needsFit = false;
    this.update();
  }

  rotated(x, y) {
    const a = (this.angle * Math.PI) / 180;
    const dx = x - this.centre[0], dy = y - this.centre[1];
    return [dx * Math.cos(a) - dy * Math.sin(a), dx * Math.sin(a) + dy * Math.cos(a)];
  }

  project(x, y, z) {
    const [xr, yr] = this.rotated(x, y);
    return [
      this.width / 2 + this.scale * xr,
      this.height / 2 + this.scale * (yr * Math.sin(ELEVATION) - (z - this.midHeight) * Math.cos(ELEVATION)),
    ];
  }

  depth(solid) {
    const [, yr] = this.rotated(...solid.centre);
    return [Math.round(yr * 10) / 10, solid.z0];
  }

  draw() {
    const ctx = this.ctx;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = BACKGROUND;
    ctx.fillRect(0, 0, this.width, this.height);
    if (!this.model) return;
    if (this.needsFit) this.fit();
    this.centre = this.tilesCentre();
    ctx.lineJoin = "round";
    const keyed = this.solids.map((s) => [this.depth(s), s]);
    keyed.sort((a, b) => a[0][0] - b[0][0] || a[0][1] - b[0][1]);
    for (const [, solid] of keyed) {
      if (solid.type === "cone") this.paintCone(ctx, solid);
      else this.paintPrism(ctx, solid);
    }
  }

  /** Light the side facing direction (nx, ny) on the map: brighter facing the upper left. */
  shade(c, nx, ny) {
    const a = (this.angle * Math.PI) / 180;
    const length = Math.hypot(nx, ny) || 1;
    const sx = (nx * Math.cos(a) - ny * Math.sin(a)) / length;
    const f = 0.86 - 0.14 * sx;
    return { r: Math.min(255, Math.round(c.r * f)), g: Math.min(255, Math.round(c.g * f)), b: Math.min(255, Math.round(c.b * f)) };
  }

  polygon(ctx, pts) {
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
  }

  paintPrism(ctx, p) {
    const n = p.points.length;
    const [cx, cy] = p.centre;
    const bottom = p.points.map(([x, y]) => this.project(x, y, p.z0));
    const top = p.points.map(([x, y]) => this.project(x, y, p.z1));
    const a = (this.angle * Math.PI) / 180;
    const seam = p.seam && this.scale >= SEAM_SCALE;
    for (let i = 0; i < n; i++) {
      if (p.hidden.has(i)) continue;
      const [x0, y0] = p.points[i], [x1, y1] = p.points[(i + 1) % n];
      const nx = (x0 + x1) / 2 - cx, ny = (y0 + y1) / 2 - cy;
      // Only sides facing the camera (towards the bottom of the screen) are seen.
      if (nx * Math.sin(a) + ny * Math.cos(a) <= 0) continue;
      const colour = css(this.shade(p.side, nx, ny));
      ctx.strokeStyle = colour;
      ctx.fillStyle = colour;
      ctx.lineWidth = 1;
      this.polygon(ctx, [bottom[i], bottom[(i + 1) % n], top[(i + 1) % n], top[i]]);
      ctx.fill();
      ctx.stroke();
      if (seam) {
        ctx.strokeStyle = OUTLINE;
        ctx.lineWidth = 0.8;
        ctx.beginPath();
        ctx.moveTo(...top[i]);
        ctx.lineTo(...top[(i + 1) % n]);
        ctx.stroke();
      }
    }
    if (p.coverTop) return;
    ctx.strokeStyle = OUTLINE;
    ctx.lineWidth = 1;
    ctx.fillStyle = css(p.top);
    this.polygon(ctx, top);
    ctx.fill();
    ctx.stroke();
  }

  paintCone(ctx, c) {
    const [cx, cy] = c.centre;
    const base = [];
    for (let k = 0; k < 16; k++) {
      const t = (2 * Math.PI * k) / 16;
      base.push(this.project(cx + c.radius * Math.cos(t), cy + c.radius * Math.sin(t), c.z0));
    }
    const apex = this.project(cx, cy, c.z1);
    ctx.strokeStyle = css(blend(c.colour, hex("#000000"), 0.35));
    ctx.lineWidth = 1;
    ctx.fillStyle = css(c.colour);
    this.polygon(ctx, hull([...base, apex]));
    ctx.fill();
    ctx.stroke();
  }

  turn(degrees) {
    this.angle = (((this.angle + degrees) % 360) + 360) % 360;
    this.update();
  }

  zoomBy(factor) {
    this.scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, this.scale * factor));
    this.update();
  }
}
