// Colours and shapes shared by the map and the piece list.

import { DIRECTIONS, EDGE_NEIGHBOURS, hexCorners, hexToPixel, rotate } from "./hexgrid.js";
import { MAX_LAYER } from "./model.js";

export const HEX_RADIUS = 20;

// --- colours, as {r, g, b} with 0-255 channels --------------------------

export function hex(s) {
  const n = parseInt(s.slice(1), 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

export function css(c, alpha = 1) {
  return alpha >= 1 ? `rgb(${c.r},${c.g},${c.b})` : `rgba(${c.r},${c.g},${c.b},${alpha})`;
}

/** Mix amount (0 to 1) of other into colour. */
export function blend(c, o, amount) {
  return {
    r: Math.round(c.r + (o.r - c.r) * amount),
    g: Math.round(c.g + (o.g - c.g) * amount),
    b: Math.round(c.b + (o.b - c.b) * amount),
  };
}

function toHsv({ r, g, b }) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  let h = 0;
  if (d) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h /= 6;
    if (h < 0) h += 1;
  }
  return [h, max ? d / max : 0, max];
}

function fromHsv(h, s, v) {
  const i = Math.floor(h * 6), f = h * 6 - i;
  const p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s);
  const [r, g, b] = [[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][i % 6];
  return { r: Math.round(r * 255), g: Math.round(g * 255), b: Math.round(b * 255) };
}

export const TERRAIN_COLOURS = {
  grass: hex("#5aa83c"), rock: hex("#9a9590"), sand: hex("#e3c977"), water: hex("#3b86d6"),
  ruin: hex("#b07a4a"), road: hex("#b5a88f"), swamp: hex("#6f7d3c"), swamp_water: hex("#4c7b74"),
  tree: hex("#2e6b2f"), castle_wall: hex("#b8b2a7"), walk: hex("#cdc6b8"), stone_wall: hex("#d8d2c6"),
  ladder: hex("#c9a46a"),
};

export const DETAIL = hex("#2b2b2b");
export const WHITE = hex("#ffffff");

/** The terrain colour, darker on low layers and brighter on high ones. */
export function terrainColour(terrain, layer = 1) {
  const [h, s, v] = toHsv(TERRAIN_COLOURS[terrain] || hex("#c040c0"));
  const t = (layer - 1) / (MAX_LAYER - 1);
  return fromHsv(h, s * (1 - 0.35 * t), Math.min(1, v * (0.8 + 0.4 * t)));
}

export function textColour(fill) {
  const max = Math.max(fill.r, fill.g, fill.b), min = Math.min(fill.r, fill.g, fill.b);
  return (max + min) / 2 / 255 > 0.55 ? hex("#111111") : WHITE;
}

// --- shapes -------------------------------------------------------------

export function hexPath(ctx, q, r, radius = HEX_RADIUS) {
  const [cx, cy] = hexToPixel(q, r, radius);
  const pts = hexCorners(cx, cy, radius);
  ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < 6; i++) ctx.lineTo(pts[i][0], pts[i][1]);
  ctx.closePath();
}

/** Adds the outline around all the given hexes to the current path, as edge segments. */
export function outlinePath(ctx, cells, radius = HEX_RADIUS) {
  const set = new Set(cells.map(([q, r]) => `${q},${r}`));
  for (const [q, r] of cells) {
    const pts = hexCorners(...hexToPixel(q, r, radius), radius);
    EDGE_NEIGHBOURS.forEach(([dq, dr], i) => {
      if (set.has(`${q + dq},${r + dr}`)) return;
      ctx.moveTo(pts[i][0], pts[i][1]);
      ctx.lineTo(pts[(i + 1) % 6][0], pts[(i + 1) % 6][1]);
    });
  }
}

const centre = (q, r, radius) => hexToPixel(q, r, radius);

function edgePoint(q, r, [dq, dr], radius) {
  const a = centre(q, r, radius), b = centre(q + dq, r + dr, radius);
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
}

function line(ctx, a, b) {
  ctx.beginPath();
  ctx.moveTo(a[0], a[1]);
  ctx.lineTo(b[0], b[1]);
  ctx.stroke();
}

function circle(ctx, [x, y], rad) {
  ctx.beginPath();
  ctx.arc(x, y, rad, 0, Math.PI * 2);
}

/** Draw what marks out trees, walls, ladders and wall walks on top of their hexes. */
export function paintDetails(ctx, piece, q, r, rotation, radius = HEX_RADIUS, wash = 0, washColour = WHITE) {
  const colour = css(blend(DETAIL, washColour, wash));
  const cells = piece.cells(q, r, rotation);
  ctx.save();
  ctx.setLineDash([]);
  if (piece.kind === "tree") {
    ctx.strokeStyle = css(blend(hex("#1d4a1f"), washColour, wash));
    ctx.lineWidth = radius * 0.12;
    ctx.fillStyle = css(blend(hex("#3f8a3c"), washColour, wash));
    for (const [cq, cr] of cells) {
      circle(ctx, centre(cq, cr, radius), radius * 0.55);
      ctx.fill();
      ctx.stroke();
    }
  } else if (piece.kind === "castle_wall") {
    ctx.strokeStyle = colour;
    ctx.lineWidth = radius * 0.35;
    ctx.lineCap = "round";
    const [cq, cr] = cells[0];
    for (const edge of piece.walls) {
      line(ctx, centre(cq, cr, radius), edgePoint(cq, cr, rotate(...DIRECTIONS[edge], rotation), radius));
    }
  } else if (piece.kind === "doorway") {
    const ends = [centre(...cells[0], radius), centre(...cells[cells.length - 1], radius)];
    ctx.strokeStyle = colour;
    ctx.fillStyle = colour;
    ctx.lineWidth = radius * 0.35;
    ctx.lineCap = "round";
    line(ctx, ends[0], ends[1]);
    for (const p of ends) {
      circle(ctx, p, radius * 0.4);
      ctx.fill();
      ctx.stroke();
    }
    // The open way through, under the arch.
    ctx.strokeStyle = css(blend(hex("#f4f1ea"), washColour, wash));
    ctx.lineWidth = radius * 0.12;
    ctx.lineCap = "butt";
    ctx.setLineDash([radius * 0.36, radius * 0.24]);
    const pts = hexCorners(...centre(...cells[1], radius), radius * 0.55);
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.stroke();
  } else if (piece.kind === "walk") {
    ctx.fillStyle = colour;
    for (const [cq, cr] of piece.supportCells(q, r, rotation)) {
      circle(ctx, centre(cq, cr, radius), radius * 0.18);
      ctx.fill();
    }
  } else if (piece.kind === "ladder") {
    ctx.strokeStyle = css(blend(hex("#5a3a17"), washColour, wash));
    ctx.lineWidth = radius * 0.12;
    const [cx, cy] = centre(...cells[0], radius);
    const w = radius * 0.3, h = radius * 0.6;
    line(ctx, [cx - w, cy - h], [cx - w, cy + h]);
    line(ctx, [cx + w, cy - h], [cx + w, cy + h]);
    for (let i = 0; i < 4; i++) {
      const y = cy - h + ((i + 0.5) * 2 * h) / 4;
      line(ctx, [cx - w, y], [cx + w, y]);
    }
  } else if (piece.kind === "stone_wall") {
    const [a, b, n] = stoneWallLine(piece, q, r, rotation, radius);
    const ext = radius * 0.87;
    ctx.strokeStyle = colour;
    ctx.lineWidth = radius * 0.4;
    ctx.lineCap = "butt";
    const [ux, uy] = n.u;
    line(ctx, [a[0] - ux * ext + n.x, a[1] - uy * ext + n.y], [b[0] + ux * ext + n.x, b[1] + uy * ext + n.y]);
  }
  ctx.restore();
}

/** The ends of a stone wall's row of hexes, and the push out towards the tiles it stands against. */
export function stoneWallLine(piece, q, r, rotation, radius, push = 0.75) {
  const cells = piece.cells(q, r, rotation);
  const a = centre(...cells[0], radius), b = centre(...cells[cells.length - 1], radius);
  const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const ux = (b[0] - a[0]) / length, uy = (b[1] - a[1]) / length;
  const side = piece.sideCells(q, r, rotation).map(([sq, sr]) => centre(sq, sr, radius));
  const sx = side.reduce((s, p) => s + p[0], 0) / side.length - (a[0] + b[0]) / 2;
  const sy = side.reduce((s, p) => s + p[1], 0) / side.length - (a[1] + b[1]) / 2;
  const along = sx * ux + sy * uy;
  let nx = sx - along * ux, ny = sy - along * uy;
  const len = Math.hypot(nx, ny) || 1;
  nx /= len; ny /= len;
  return [a, b, { x: nx * radius * push, y: ny * radius * push, u: [ux, uy], nx, ny }];
}

/** A small picture of the piece's shape, drawn into a canvas. */
export function pieceIcon(piece, size = 56) {
  const dpr = window.devicePixelRatio || 1;
  const canvas = document.createElement("canvas");
  canvas.width = size * dpr;
  canvas.height = size * dpr;
  canvas.style.width = `${size}px`;
  canvas.style.height = `${size}px`;
  const ctx = canvas.getContext("2d");
  const radius = 10;
  const cells = piece.cells(0, 0, 0);
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [q, r] of cells) {
    for (const [x, y] of hexCorners(...hexToPixel(q, r, radius), radius)) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
  }
  const scale = Math.min((size - 4) / (maxX - minX), (size - 4) / (maxY - minY), 1.4);
  ctx.scale(dpr, dpr);
  ctx.translate(size / 2, size / 2);
  ctx.scale(scale, scale);
  ctx.translate(-(minX + maxX) / 2, -(minY + maxY) / 2);
  ctx.fillStyle = css(terrainColour(piece.terrain, 6));
  ctx.strokeStyle = "rgba(0,0,0,0.24)";
  ctx.lineWidth = 1 / scale;
  for (const [q, r] of cells) {
    ctx.beginPath();
    hexPath(ctx, q, r, radius);
    ctx.fill();
    ctx.stroke();
  }
  paintDetails(ctx, piece, 0, 0, 0, radius);
  ctx.strokeStyle = "#222";
  ctx.beginPath();
  outlinePath(ctx, cells, radius);
  ctx.stroke();
  return canvas;
}
