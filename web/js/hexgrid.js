// Hex grid maths for a pointy-top hex grid using axial (q, r) coordinates.
// See https://www.redblobgames.com/grids/hexagons/ for background.

export const SQRT3 = Math.sqrt(3);

// Map sizes, as hexes across x hexes down.
export const MAP_SIZES = { small: 20, medium: 30, large: 50 };

export const mod = (a, n) => ((a % n) + n) % n;

/** Rotate (q, r) clockwise around (0, 0) by steps * 60 degrees. */
export function rotate(q, r, steps) {
  let x = q, z = r, y = -x - z;
  for (let i = 0; i < mod(steps, 6); i++) [x, y, z] = [-z, -x, -y];
  return [x + 0, z + 0]; // + 0 turns -0 into 0
}

/** Axial to "odd-r" offset (col, row), the layout of a rectangular map. */
export function toOffset(q, r) {
  return [q + Math.floor((r - (r & 1)) / 2), r];
}

export function fromOffset(col, row) {
  return [col - Math.floor((row - (row & 1)) / 2), row];
}

export function inBounds(q, r, size) {
  const [col, row] = toOffset(q, r);
  return col >= 0 && col < size && row >= 0 && row < size;
}

/** Centre of hex (q, r) in pixels. */
export function hexToPixel(q, r, radius) {
  return [radius * SQRT3 * (q + r / 2), radius * 1.5 * r];
}

/** The hex containing pixel (x, y). */
export function pixelToHex(x, y, radius) {
  const fq = ((SQRT3 / 3) * x - y / 3) / radius;
  const fr = ((2 / 3) * y) / radius;
  return roundHex(fq, fr);
}

export function roundHex(fq, fr) {
  const fs = -fq - fr;
  let q = Math.round(fq), r = Math.round(fr);
  const s = Math.round(fs);
  const dq = Math.abs(q - fq), dr = Math.abs(r - fr), ds = Math.abs(s - fs);
  if (dq > dr && dq > ds) q = -r - s;
  else if (dr > ds) r = -q - s;
  return [q + 0, r + 0];
}

/** The six corner points of a pointy-top hex centred on (cx, cy). */
export function hexCorners(cx, cy, radius) {
  const points = [];
  for (let i = 0; i < 6; i++) {
    const a = ((60 * i - 30) * Math.PI) / 180;
    points.push([cx + radius * Math.cos(a), cy + radius * Math.sin(a)]);
  }
  return points;
}

// The neighbour across each edge of hexCorners: edge i runs from corner i to corner i + 1.
export const EDGE_NEIGHBOURS = [[1, 0], [0, 1], [-1, 1], [-1, 0], [0, -1], [1, -1]];

// Axial steps to the six neighbours, matching the hex edges a castle wall can run to.
export const DIRECTIONS = [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]];

export const key = (q, r) => `${q},${r}`;
