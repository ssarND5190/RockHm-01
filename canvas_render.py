"""Canvas rendering: shape drawing and color visualization modes."""

from __future__ import annotations

import colorsys
import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Literal

from draw_objects import DrawObject, Line, Rectangle, Triangle

ColorVisMode = Literal["normal", "brightness", "saturation"]


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def map_color(hex_color: str, mode: ColorVisMode) -> str:
    if mode == "normal":
        return hex_color
    r, g, b = hex_to_rgb(hex_color)
    _h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if mode == "brightness":
        gray = int(round(v * 255))
    else:
        gray = int(round(s * 255))
    return rgb_to_hex(gray, gray, gray)


@dataclass
class RenderContext:
    canvas: tk.Canvas
    world_to_screen: Callable[[float, float], tuple[float, float]]
    scale: float
    color_mode: ColorVisMode = "normal"


def draw_paint_canvas_fill(paint_canvas: object, ctx: RenderContext) -> None:
    screen_corners = [ctx.world_to_screen(x, y) for x, y in paint_canvas.corners()]
    flat = [coord for pt in screen_corners for coord in pt]
    fill = map_color("#ffffff", ctx.color_mode)
    ctx.canvas.create_polygon(*flat, fill=fill, outline="")


def draw_paint_canvas_border(paint_canvas: object, ctx: RenderContext) -> None:
    screen_corners = [ctx.world_to_screen(x, y) for x, y in paint_canvas.corners()]
    for i in range(4):
        x1, y1 = screen_corners[i]
        x2, y2 = screen_corners[(i + 1) % 4]
        ctx.canvas.create_line(x1, y1, x2, y2, fill="black", width=1)


def draw_rectangle(shape: Rectangle, ctx: RenderContext) -> None:
    screen_corners = [ctx.world_to_screen(x, y) for x, y in shape.corners()]
    flat = [coord for pt in screen_corners for coord in pt]
    ctx.canvas.create_polygon(*flat, fill=map_color(shape.color, ctx.color_mode), outline="")


def draw_line(shape: Line, ctx: RenderContext) -> None:
    sx1, sy1 = ctx.world_to_screen(shape.x1, shape.y1)
    sx2, sy2 = ctx.world_to_screen(shape.x2, shape.y2)
    width = max(1, int(shape.stroke_width * ctx.scale))
    ctx.canvas.create_line(
        sx1,
        sy1,
        sx2,
        sy2,
        fill=map_color(shape.color, ctx.color_mode),
        width=width,
        capstyle=tk.ROUND,
    )


def draw_triangle(shape: Triangle, ctx: RenderContext) -> None:
    screen_verts = [ctx.world_to_screen(x, y) for x, y in shape.vertices()]
    flat = [coord for pt in screen_verts for coord in pt]
    ctx.canvas.create_polygon(*flat, fill=map_color(shape.color, ctx.color_mode), outline="")


def draw_shape(shape: DrawObject, ctx: RenderContext) -> None:
    if isinstance(shape, Rectangle):
        draw_rectangle(shape, ctx)
    elif isinstance(shape, Line):
        draw_line(shape, ctx)
    elif isinstance(shape, Triangle):
        draw_triangle(shape, ctx)


def draw_outside_mask(
    paint_canvas: object,
    ctx: RenderContext,
    *,
    canvas_width: int,
    canvas_height: int,
    mask_color: str,
) -> None:
    x1, y1, x2, y2 = paint_canvas.bounds()
    sx1, sy1 = ctx.world_to_screen(x1, y1)
    sx2, sy2 = ctx.world_to_screen(x2, y2)
    left, right = min(sx1, sx2), max(sx1, sx2)
    top, bottom = min(sy1, sy2), max(sy1, sy2)
    w = max(canvas_width, 1)
    h = max(canvas_height, 1)
    canvas = ctx.canvas
    canvas.create_rectangle(0, 0, w, top, fill=mask_color, outline="")
    canvas.create_rectangle(0, bottom, w, h, fill=mask_color, outline="")
    canvas.create_rectangle(0, top, left, bottom, fill=mask_color, outline="")
    canvas.create_rectangle(right, top, w, bottom, fill=mask_color, outline="")
