#!/usr/bin/env python3
"""Draw the OSM-ATLAS sync badge and write static/header/sync-badge.svg and static/favicon.svg.

The badge is a red disc with the Swiss cross, ringed by two arrows: green (OpenStreetMap) running
clockwise over the top and blue (ATLAS) running clockwise under the bottom. The arrows are one
shape, the blue turned 180 degrees, so the badge stays exactly symmetric. Each arrow thickens
towards its head, and its tail is cut parallel to the other head's inner edge, so one straight
white stripe runs through each joint. The cross has the official proportions: arms 7/6 as long
as they are wide.

Coordinates are centred on the disc. Angles are SVG degrees: clockwise from +x, with y pointing
down. The poster's figures/sync-badge.pdf is an export of the badge SVG:
    inkscape static/header/sync-badge.svg --export-type=pdf --export-filename=<poster>/figures/sync-badge.pdf
"""
from __future__ import annotations

import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

R_RED = 172                # red disc radius
GAP = 13                   # white ring around the disc, and the stripe at each joint
BAND_TAIL = (36, 160)      # arrow thickness at an angle near the tail ...
BAND_HEAD = (60, 310)      # ... growing linearly to this near the head
INNER_BARB = (142, 306)    # head corners, (radius, angle)
OUTER_BARB = (40, 314)     # (distance outside the arrow's outer edge, angle)
TIP = (234, 344)           # (radius, angle)
ARM = 64                   # Swiss cross arm width
ROUND = 10                 # corner rounding: a same-colour stroke this wide
TILE_MARGIN = 16           # favicon: space between the badge and its tile's edge

WHITE, RED, GREEN, BLUE = "#fcfcfc", "#c12e22", "#5ba04a", "#173f8a"

R_IN = R_RED + GAP
# The drawn path is inset by K and stroked ROUND wide, which rounds its corners
# while the visible shape keeps the dimensions above.
K = ROUND / 2


def polar(r: float, a: float) -> tuple[float, float]:
    return r * math.cos(math.radians(a)), r * math.sin(math.radians(a))


def angle_of(p: tuple[float, float]) -> float:
    return math.degrees(math.atan2(p[1], p[0])) % 360


def outer_radius(a: float) -> float:
    (b0, a0), (b1, a1) = BAND_TAIL, BAND_HEAD
    return R_IN + b0 + (b1 - b0) * (a - a0) / (a1 - a0)


def angle_gap(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


class Line:
    def __init__(self, p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        n = math.hypot(dx, dy)
        self.p, self.d = p, (dx / n, dy / n)

    def shifted(self, dist: float, toward) -> Line:
        """This line moved `dist` towards the point `toward` (away from it if dist < 0)."""
        nx, ny = -self.d[1], self.d[0]
        if (toward[0] - self.p[0]) * nx + (toward[1] - self.p[1]) * ny < 0:
            nx, ny = -nx, -ny
        p = (self.p[0] + nx * dist, self.p[1] + ny * dist)
        return Line(p, (p[0] + self.d[0], p[1] + self.d[1]))

    def turned(self) -> Line:
        """This line turned 180 degrees about the centre."""
        return Line((-self.p[0], -self.p[1]), (-self.p[0] - self.d[0], -self.p[1] - self.d[1]))

    def meet(self, other: Line) -> tuple[float, float]:
        (px, py), (dx, dy) = self.p, self.d
        (qx, qy), (ex, ey) = other.p, other.d
        t = ((qx - px) * ey - (qy - py) * ex) / (dx * ey - dy * ex)
        return px + t * dx, py + t * dy

    def at_radius(self, radius, near: float) -> tuple[float, float]:
        """Where the line crosses the curve r = radius(angle), on the side nearest angle `near`."""
        guess = near
        for _ in range(50):
            r = radius(guess)
            (px, py), (dx, dy) = self.p, self.d
            b = px * dx + py * dy
            disc = b * b - (px * px + py * py - r * r)
            hits = [(px + t * dx, py + t * dy) for t in (-b - math.sqrt(disc), -b + math.sqrt(disc))]
            hit = min(hits, key=lambda h: angle_gap(angle_of(h), near))
            if abs(angle_of(hit) - guess) < 1e-9:
                break
            guess = angle_of(hit)
        return hit


def fmt(x: float) -> str:
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def xy(p) -> str:
    return f"{fmt(p[0])} {fmt(p[1])}"


def spiral(a0: float, a1: float, segments: int) -> str:
    """Cubic Beziers along the arrow's (inset) outer edge from angle a0 to a1."""
    def point(a):
        return polar(outer_radius(a) - K, a)

    def tangent(a):
        (x0, y0), (x1, y1) = point(a - 1e-4), point(a + 1e-4)
        return (x1 - x0) / 2e-4, (y1 - y0) / 2e-4

    h, out = (a1 - a0) / segments, ""
    for i in range(segments):
        s, e = a0 + i * h, a0 + (i + 1) * h
        (sx, sy), (ex, ey) = point(s), point(e)
        (tx, ty), (ux, uy) = tangent(s), tangent(e)
        out += f"C{xy((sx + tx * h / 3, sy + ty * h / 3))} {xy((ex - ux * h / 3, ey - uy * h / 3))} {xy((ex, ey))}"
    return out


def arrow_path() -> tuple[str, tuple]:
    inner_barb = polar(*INNER_BARB)
    outer_barb = polar(outer_radius(OUTER_BARB[1]) + OUTER_BARB[0], OUTER_BARB[1])
    tip = polar(*TIP)
    centre = tuple((inner_barb[i] + outer_barb[i] + tip[i]) / 3 for i in (0, 1))

    back = Line(inner_barb, outer_barb).shifted(K, centre)
    outer_edge = Line(outer_barb, tip).shifted(K, centre)
    inner_edge = Line(tip, inner_barb)
    path_inner_edge = inner_edge.shifted(K, centre)

    # The other arrow's tail runs GAP away from this head's inner edge; this tail is that cut turned.
    tail_cut = inner_edge.shifted(-(GAP + K), centre).turned()

    def inner(_):
        return R_IN + K

    def outer(a):
        return outer_radius(a) - K

    tail_out = tail_cut.at_radius(outer, BAND_TAIL[1])
    tail_in = tail_cut.at_radius(inner, BAND_TAIL[1])
    back_out = back.at_radius(outer, OUTER_BARB[1])
    back_in = back.at_radius(inner, INNER_BARB[1])
    large_arc = int((angle_of(back_in) - angle_of(tail_in)) % 360 > 180)

    return (
        f"M{xy(tail_out)}"
        + spiral(angle_of(tail_out), angle_of(back_out), 8)
        + f"L{xy(back.meet(outer_edge))}"
        + f"L{xy(outer_edge.meet(path_inner_edge))}"
        + f"L{xy(path_inner_edge.meet(back))}"
        + f"L{xy(back_in)}"
        + f"A{fmt(R_IN + K)} {fmt(R_IN + K)} 0 {large_arc} 0 {xy(tail_in)}Z"
    ), (tip, outer_barb, inner_barb)


def cross_path() -> str:
    w, arm = ARM, ARM * 7 / 6
    h = w / 2 + arm
    return (
        f"M{fmt(-w / 2)} {fmt(-h)}h{fmt(w)}v{fmt(arm)}h{fmt(arm)}v{fmt(w)}h{fmt(-arm)}"
        f"v{fmt(arm)}h{fmt(-w)}v{fmt(-arm)}h{fmt(-arm)}v{fmt(-w)}h{fmt(arm)}Z"
    )


def extent(head) -> tuple[int, int]:
    """Half width and half height of the badge, which is symmetric about the centre."""
    tip, outer_barb, inner_barb = head
    points = [tip, outer_barb, inner_barb]
    points += [polar(outer_radius(a), a) for a in range(BAND_TAIL[1], OUTER_BARB[1] + 1)]
    return (
        math.ceil(max(abs(x) for x, _ in points)),
        math.ceil(max(abs(y) for _, y in points)),
    )


def main() -> None:
    arrow, head = arrow_path()
    half_w, half_h = extent(head)
    note = (
        "  <!-- Generated by scripts/sync_badge.py: edit the script and rerun it. The green (OSM) and\n"
        "       blue (ATLAS) arrows are one shape, the blue turned 180 degrees. -->\n"
    )
    body = f"""  <defs>
    <path id="arrow" d="{arrow}"/>
    <clipPath id="inside"><circle r="{fmt(R_IN)}"/></clipPath>
  </defs>
  <circle r="{fmt(R_IN + 1)}" fill="{WHITE}"/>
  <circle r="{fmt(R_RED)}" fill="{RED}"/>
  <g clip-path="url(#inside)" fill="{WHITE}" stroke="{WHITE}" stroke-width="{fmt(2 * (GAP + K))}" stroke-linejoin="round">
    <use href="#arrow"/>
    <use href="#arrow" transform="rotate(180)"/>
  </g>
  <g stroke-width="{fmt(ROUND)}" stroke-linejoin="round">
    <use href="#arrow" fill="{GREEN}" stroke="{GREEN}"/>
    <use href="#arrow" fill="{BLUE}" stroke="{BLUE}" transform="rotate(180)"/>
  </g>
  <path d="{cross_path()}" fill="{WHITE}"/>
</svg>
"""
    badge = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-half_w} {-half_h} {2 * half_w} {2 * half_h}">\n'
    (ROOT / "static/header/sync-badge.svg").write_text(badge + note + body)

    tile = max(half_w, half_h) + TILE_MARGIN
    favicon = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="{-tile} {-tile} {2 * tile} {2 * tile}">\n'
        + note
        + f'  <rect x="{-tile}" y="{-tile}" width="{2 * tile}" height="{2 * tile}" rx="80" fill="{WHITE}"/>\n'
    )
    (ROOT / "static/favicon.svg").write_text(favicon + body)
    print(f"sync-badge.svg: {2 * half_w} x {2 * half_h}; favicon.svg: {2 * tile} x {2 * tile}")


if __name__ == "__main__":
    main()
