"""Draw object types for the vector drawing tool."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Union

ROTATION_HANDLE_OFFSET = 28
LINE_MOVE_OFFSET = 28
MIN_RECT_SIZE = 4
MIN_LINE_LENGTH = 4
MIN_TRIANGLE_AREA = 32
DEFAULT_LINE_WIDTH = 8
MIN_LINE_WIDTH = 1
MAX_LINE_WIDTH = 48

DrawObject = Union["Rectangle", "Line", "Triangle"]
DrawTool = Literal["rectangle", "line", "triangle"]


def _dist_point_to_segment(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> float:
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - x1, py - y1)
    t = clamp((px - x1) * dx + (py - y1) * dy, 0, length_sq) / length_sq
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sorted_shapes(shapes: list[DrawObject]) -> list[DrawObject]:
    return sorted(shapes, key=lambda shape: shape.z_index)


def z_index_above(shapes: list[DrawObject], ref_id: int) -> int:
    selected = next(shape for shape in shapes if shape.id == ref_id)
    target = selected.z_index + 1
    for shape in shapes:
        if shape.z_index >= target:
            shape.z_index += 1
    return target


def next_top_z_index(shapes: list[DrawObject]) -> int:
    return max((shape.z_index for shape in shapes), default=0) + 1


def intersects_paint_canvas(shape: DrawObject, bounds: tuple[float, float, float, float]) -> bool:
    px1, py1, px2, py2 = bounds
    sx1, sy1, sx2, sy2 = shape_bounds(shape)
    return not (sx2 < px1 or sx1 > px2 or sy2 < py1 or sy1 > py2)


def triangle_area(
    x1: float, y1: float, x2: float, y2: float, x3: float, y3: float
) -> float:
    return abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2


def shape_bounds(shape: DrawObject) -> tuple[float, float, float, float]:
    if isinstance(shape, Rectangle):
        corners = shape.corners()
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return min(xs), min(ys), max(xs), max(ys)
    if isinstance(shape, Triangle):
        xs = [shape.x1, shape.x2, shape.x3]
        ys = [shape.y1, shape.y2, shape.y3]
        return min(xs), min(ys), max(xs), max(ys)
    margin = shape.stroke_width / 2
    return (
        min(shape.x1, shape.x2) - margin,
        min(shape.y1, shape.y2) - margin,
        max(shape.x1, shape.x2) + margin,
        max(shape.y1, shape.y2) + margin,
    )


@dataclass
class Rectangle:
    id: int
    name: str
    cx: float
    cy: float
    width: float
    height: float
    rotation: float = 0.0
    color: str = "#4a90d9"
    z_index: int = 0

    @property
    def kind(self) -> Literal["rectangle"]:
        return "rectangle"

    def corners(self) -> list[tuple[float, float]]:
        hw, hh = self.width / 2, self.height / 2
        local = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
        rad = math.radians(self.rotation)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        return [
            (self.cx + x * cos_a - y * sin_a, self.cy + x * sin_a + y * cos_a)
            for x, y in local
        ]

    def contains_point(self, px: float, py: float) -> bool:
        rad = math.radians(-self.rotation)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        dx, dy = px - self.cx, py - self.cy
        lx = dx * cos_a - dy * sin_a
        ly = dx * sin_a + dy * cos_a
        return abs(lx) <= self.width / 2 and abs(ly) <= self.height / 2

    def handle_positions(self) -> dict[str, tuple[float, float]]:
        corners = self.corners()
        mid = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        top_mid = mid(corners[0], corners[1])
        rad = math.radians(self.rotation - 90)
        rot_x = top_mid[0] + ROTATION_HANDLE_OFFSET * math.cos(rad)
        rot_y = top_mid[1] + ROTATION_HANDLE_OFFSET * math.sin(rad)
        return {
            "nw": corners[0],
            "n": mid(corners[0], corners[1]),
            "ne": corners[1],
            "e": mid(corners[1], corners[2]),
            "se": corners[2],
            "s": mid(corners[2], corners[3]),
            "sw": corners[3],
            "w": mid(corners[3], corners[0]),
            "rotate": (rot_x, rot_y),
        }


@dataclass
class Line:
    id: int
    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    color: str = "#e88c4a"
    stroke_width: float = DEFAULT_LINE_WIDTH
    z_index: int = 0

    @property
    def kind(self) -> Literal["line"]:
        return "line"

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    def _perpendicular_offset(self) -> tuple[float, float]:
        dx, dy = self.x2 - self.x1, self.y2 - self.y1
        length = math.hypot(dx, dy) or 1.0
        px, py = -dy / length, dx / length
        if py < 0:
            px, py = -px, -py
        return px, py

    def handle_positions(self) -> dict[str, tuple[float, float]]:
        mx, my = self.cx, self.cy
        px, py = self._perpendicular_offset()
        return {
            "p1": (self.x1, self.y1),
            "p2": (self.x2, self.y2),
            "move": (mx + px * LINE_MOVE_OFFSET, my + py * LINE_MOVE_OFFSET),
        }

    def contains_point(self, px: float, py: float) -> bool:
        margin = self.stroke_width / 2
        return _dist_point_to_segment(px, py, self.x1, self.y1, self.x2, self.y2) <= margin


@dataclass
class Triangle:
    id: int
    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    x3: float
    y3: float
    color: str = "#9b59b6"
    z_index: int = 0

    @property
    def kind(self) -> Literal["triangle"]:
        return "triangle"

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2 + self.x3) / 3

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2 + self.y3) / 3

    def vertices(self) -> list[tuple[float, float]]:
        return [(self.x1, self.y1), (self.x2, self.y2), (self.x3, self.y3)]

    def reference_midpoint(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    def reference_angle(self) -> float:
        mid_x, mid_y = self.reference_midpoint()
        return math.degrees(math.atan2(mid_y - self.cy, mid_x - self.cx)) + 90

    def handle_positions(self) -> dict[str, tuple[float, float]]:
        mid_x, mid_y = self.reference_midpoint()
        dx, dy = mid_x - self.cx, mid_y - self.cy
        length = math.hypot(dx, dy) or 1.0
        rot_x = mid_x + (dx / length) * ROTATION_HANDLE_OFFSET
        rot_y = mid_y + (dy / length) * ROTATION_HANDLE_OFFSET
        return {
            "v1": (self.x1, self.y1),
            "v2": (self.x2, self.y2),
            "v3": (self.x3, self.y3),
            "rotate": (rot_x, rot_y),
        }

    def rotate_to_angle(self, snap: Triangle, target_angle: float) -> None:
        delta = math.radians(target_angle - snap.reference_angle())
        cos_d, sin_d = math.cos(delta), math.sin(delta)
        cx, cy = snap.cx, snap.cy
        for attr_x, attr_y, vx, vy in (
            ("x1", "y1", snap.x1, snap.y1),
            ("x2", "y2", snap.x2, snap.y2),
            ("x3", "y3", snap.x3, snap.y3),
        ):
            dx, dy = vx - cx, vy - cy
            setattr(self, attr_x, cx + dx * cos_d - dy * sin_d)
            setattr(self, attr_y, cy + dx * sin_d + dy * cos_d)

    def contains_point(self, px: float, py: float) -> bool:
        def sign(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
            return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)

        d1 = sign(self.x1, self.y1, self.x2, self.y2, px, py)
        d2 = sign(self.x2, self.y2, self.x3, self.y3, px, py)
        d3 = sign(self.x3, self.y3, self.x1, self.y1, px, py)
        has_neg = d1 < 0 or d2 < 0 or d3 < 0
        has_pos = d1 > 0 or d2 > 0 or d3 > 0
        return not (has_neg and has_pos)
