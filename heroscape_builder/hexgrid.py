"""Hex grid maths for a pointy-top hex grid using axial (q, r) coordinates.

See https://www.redblobgames.com/grids/hexagons/ for background.
"""

import math

SQRT3 = math.sqrt(3)

# Map sizes, as hexes across x hexes down.
MAP_SIZES = {
    "small": 30,
    "medium": 50,
    "large": 80,
}


def rotate(q, r, steps):
    """Rotate (q, r) clockwise around (0, 0) by steps * 60 degrees."""
    x, z = q, r
    y = -x - z
    for _ in range(steps % 6):
        x, y, z = -z, -x, -y
    return x, z


def to_offset(q, r):
    """Axial to "odd-r" offset (col, row), the layout of a rectangular map."""
    return q + (r - (r & 1)) // 2, r


def from_offset(col, row):
    return col - (row - (row & 1)) // 2, row


def in_bounds(q, r, size):
    col, row = to_offset(q, r)
    return 0 <= col < size and 0 <= row < size


def hex_to_pixel(q, r, radius):
    """Centre of hex (q, r) in pixels."""
    return radius * SQRT3 * (q + r / 2), radius * 1.5 * r


def pixel_to_hex(x, y, radius):
    """The hex containing pixel (x, y)."""
    fq = (SQRT3 / 3 * x - y / 3) / radius
    fr = (2 / 3 * y) / radius
    return round_hex(fq, fr)


def round_hex(fq, fr):
    fs = -fq - fr
    q, r, s = round(fq), round(fr), round(fs)
    dq, dr, ds = abs(q - fq), abs(r - fr), abs(s - fs)
    if dq > dr and dq > ds:
        q = -r - s
    elif dr > ds:
        r = -q - s
    return int(q), int(r)


def hex_corners(cx, cy, radius):
    """The six corner points of a pointy-top hex centred on (cx, cy)."""
    points = []
    for i in range(6):
        angle = math.radians(60 * i - 30)
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points
