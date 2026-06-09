"""Vector rectangle drawing tool with color palette, canvas, and layer panel."""

from __future__ import annotations

import colorsys
import math
import tkinter as tk
from dataclasses import dataclass, replace
from typing import Callable, Optional

from PIL import Image, ImageTk


HANDLE_RADIUS = 4
ROTATION_HANDLE_RADIUS = 10
ROTATION_HANDLE_OFFSET = 28
HANDLE_FILL = "#f0f0f0"
HANDLE_HOVER_FILL = "#404040"
HANDLE_OUTLINE = "#333333"
HANDLE_TEXT = "#333333"
DRAW_PREVIEW_OUTLINE = "#666666"
MIN_RECT_SIZE = 4
MIN_ZOOM = 0.1
MAX_ZOOM = 8.0
ZOOM_FACTOR = 1.1
MIN_PAINT_SIZE = 50
MAX_PAINT_SIZE = 5000
DEFAULT_PAINT_WIDTH = 960
DEFAULT_PAINT_HEIGHT = 540


@dataclass(frozen=True)
class Theme:
    app_bg: str
    panel_bg: str
    text: str
    canvas_bg: str
    canvas_border: str
    list_bg: str
    list_border: str
    layer_selected: str
    layer_normal: str
    swatch_border: str
    wheel_hole: tuple[int, int, int]
    slider_outline: str
    thumb_fill: str
    thumb_outline: str
    preview_outline: str
    selection_line: str
    handle_fill: str
    handle_hover: str
    handle_outline: str
    handle_text: str
    draw_preview: str
    entry_bg: str
    entry_fg: str
    button_bg: str
    button_fg: str
    button_active_bg: str


LIGHT_THEME = Theme(
    app_bg="#e8e8e8",
    panel_bg="#f0f0f0",
    text="#000000",
    canvas_bg="#d8d8d8",
    canvas_border="#aaaaaa",
    list_bg="#ffffff",
    list_border="#cccccc",
    layer_selected="#c8c8c8",
    layer_normal="#ffffff",
    swatch_border="#888888",
    wheel_hole=(240, 240, 240),
    slider_outline="#888888",
    thumb_fill="#333333",
    thumb_outline="#111111",
    preview_outline="#888888",
    selection_line="#333333",
    handle_fill="#ffffff",
    handle_hover="#b0b0b0",
    handle_outline="#333333",
    handle_text="#333333",
    draw_preview="#666666",
    entry_bg="#ffffff",
    entry_fg="#000000",
    button_bg="#f0f0f0",
    button_fg="#000000",
    button_active_bg="#e0e0e0",
)

DARK_THEME = Theme(
    app_bg="#1e1e1e",
    panel_bg="#2b2b2b",
    text="#e0e0e0",
    canvas_bg="#3a3a3a",
    canvas_border="#555555",
    list_bg="#353535",
    list_border="#555555",
    layer_selected="#4a4a4a",
    layer_normal="#353535",
    swatch_border="#888888",
    wheel_hole=(43, 43, 43),
    slider_outline="#666666",
    thumb_fill="#cccccc",
    thumb_outline="#999999",
    preview_outline="#666666",
    selection_line="#cccccc",
    handle_fill="#555555",
    handle_hover="#888888",
    handle_outline="#dddddd",
    handle_text="#dddddd",
    draw_preview="#999999",
    entry_bg="#404040",
    entry_fg="#e0e0e0",
    button_bg="#404040",
    button_fg="#e0e0e0",
    button_active_bg="#505050",
)


def _style_button(btn: tk.Button, theme: Theme) -> None:
    btn.config(
        bg=theme.button_bg,
        fg=theme.button_fg,
        activebackground=theme.button_active_bg,
        activeforeground=theme.button_fg,
    )


def _style_entry(entry: tk.Entry, theme: Theme) -> None:
    entry.config(bg=theme.entry_bg, fg=theme.entry_fg, insertbackground=theme.entry_fg)


def _style_label(label: tk.Label, theme: Theme) -> None:
    label.config(bg=theme.panel_bg, fg=theme.text)


@dataclass
class PaintCanvas:
    cx: float = 400.0
    cy: float = 320.0
    width: float = DEFAULT_PAINT_WIDTH
    height: float = DEFAULT_PAINT_HEIGHT

    def bounds(self) -> tuple[float, float, float, float]:
        hw, hh = self.width / 2, self.height / 2
        return self.cx - hw, self.cy - hh, self.cx + hw, self.cy + hh

    def corners(self) -> list[tuple[float, float]]:
        x1, y1, x2, y2 = self.bounds()
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


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


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _gradient_pixels(
    width: int, height: int, sample: Callable[[float], tuple[int, int, int]]
) -> list[tuple[int, int, int]]:
    pixels: list[tuple[int, int, int]] = []
    denom = max(width - 1, 1)
    for _y in range(height):
        for x in range(width):
            pixels.append(sample(x / denom))
    return pixels


class GradientSlider(tk.Frame):
    """Slider with a gradient bar that can be updated to reflect the current color."""

    def __init__(
        self,
        master: tk.Misc,
        label: str,
        from_: int,
        to_: int,
        on_change: Callable[[float], None],
    ) -> None:
        super().__init__(master, bg=LIGHT_THEME.panel_bg)
        self.from_ = from_
        self.to_ = to_
        self.on_change = on_change
        self._value = from_
        self._updating = False
        self._bar_w = 130
        self._bar_h = 12
        self._gradient_photo: Optional[ImageTk.PhotoImage] = None
        self._gradient_image_id: Optional[int] = None
        self._border_id: Optional[int] = None
        self.theme = LIGHT_THEME

        self.label = tk.Label(self, text=label, width=2, font=("Segoe UI", 9))
        self.label.pack(side="left")
        self.canvas = tk.Canvas(
            self,
            width=self._bar_w,
            height=self._bar_h + 10,
            highlightthickness=0,
        )
        self.canvas.pack(side="left", padx=4)
        self._border_id = self.canvas.create_rectangle(0, 0, self._bar_w, self._bar_h, width=1)
        self._thumb_id = self.canvas.create_polygon(0, 0, 0, 0, 0, 0)

        self.value_label = tk.Label(self, text="000", width=4, font=("Consolas", 9))
        self.value_label.pack(side="left")
        self.apply_theme(LIGHT_THEME)

        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_press)

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.config(bg=theme.panel_bg)
        _style_label(self.label, theme)
        self.canvas.config(bg=theme.panel_bg)
        _style_label(self.value_label, theme)
        if self._border_id is not None:
            self.canvas.itemconfig(self._border_id, outline=theme.slider_outline)
        self.canvas.itemconfig(
            self._thumb_id, fill=theme.thumb_fill, outline=theme.thumb_outline
        )

    def set_gradient(self, sample: Callable[[float], tuple[int, int, int]]) -> None:
        pixels = _gradient_pixels(self._bar_w, self._bar_h, sample)
        img = Image.new("RGB", (self._bar_w, self._bar_h))
        img.putdata(pixels)
        self._gradient_photo = ImageTk.PhotoImage(img)
        if self._gradient_image_id is None:
            self._gradient_image_id = self.canvas.create_image(
                0, 0, anchor="nw", image=self._gradient_photo
            )
        else:
            self.canvas.itemconfig(self._gradient_image_id, image=self._gradient_photo)
        self.canvas.tag_lower(self._gradient_image_id)

    def set_value(self, value: float) -> None:
        self._updating = True
        self._value = clamp(value, self.from_, self.to_)
        self._draw_thumb()
        self.value_label.config(text=f"{int(self._value):03d}")
        self._updating = False

    def get_value(self) -> float:
        return self._value

    def _draw_thumb(self) -> None:
        t = (self._value - self.from_) / max(self.to_ - self.from_, 1)
        x = t * (self._bar_w - 1)
        y = self._bar_h + 2
        self.canvas.coords(self._thumb_id, x - 5, y, x + 5, y, x, y + 6)

    def _on_press(self, event: tk.Event) -> None:
        if self._updating:
            return
        t = clamp(event.x / max(self._bar_w - 1, 1), 0, 1)
        self._value = round(self.from_ + t * (self.to_ - self.from_))
        self._draw_thumb()
        self.value_label.config(text=f"{int(self._value):03d}")
        self.on_change(self._value)


class ColorPalette(tk.Frame):
    """Left panel: hue ring, SV square, and RGB/HSV sliders."""

    def __init__(
        self,
        master: tk.Misc,
        on_color_change: Callable[[str], None],
        on_picker_toggle: Callable[[], None],
    ) -> None:
        super().__init__(master, bg=LIGHT_THEME.panel_bg, width=220)
        self.on_color_change = on_color_change
        self._updating = False
        self.theme = LIGHT_THEME

        self.hue = 0.55
        self.sat = 0.65
        self.val = 0.75
        self.r, self.g, self.b = 74, 144, 217

        self._wheel_size = 160
        self._square_size = 72
        self._wheel_photo: Optional[ImageTk.PhotoImage] = None
        self._square_photo: Optional[ImageTk.PhotoImage] = None
        self._cached_hue: Optional[float] = None

        self.picker_frame = tk.Frame(self)
        self.picker_frame.pack(pady=(12, 8))

        self.wheel_canvas = tk.Canvas(
            self.picker_frame,
            width=self._wheel_size,
            height=self._wheel_size,
            highlightthickness=0,
        )
        self.wheel_canvas.pack()
        self.wheel_canvas.bind("<Button-1>", self._on_wheel_click)
        self.wheel_canvas.bind("<B1-Motion>", self._on_wheel_click)

        inset = (self._wheel_size - self._square_size) // 2
        self.square_canvas = tk.Canvas(
            self.picker_frame,
            width=self._square_size,
            height=self._square_size,
            highlightthickness=0,
        )
        self.square_canvas.place(
            x=inset + 1, y=inset + 1, width=self._square_size, height=self._square_size
        )
        self.square_canvas.bind("<Button-1>", self._on_square_click)
        self.square_canvas.bind("<B1-Motion>", self._on_square_click)

        self.preview = tk.Canvas(self, width=200, height=28, highlightthickness=0)
        self.preview.pack(pady=(4, 6))

        self.picker_row = tk.Frame(self)
        self.picker_row.pack(fill="x", padx=10, pady=(0, 8))
        self.picker_btn = tk.Button(
            self.picker_row,
            text="Pick Color (hold Alt)",
            command=on_picker_toggle,
            font=("Segoe UI", 9),
        )
        self.picker_btn.pack(fill="x")

        self.sliders: dict[str, GradientSlider] = {}
        for label, from_, to_, key in [
            ("R", 0, 255, "r"),
            ("G", 0, 255, "g"),
            ("B", 0, 255, "b"),
            ("H", 0, 360, "h"),
            ("S", 0, 100, "s"),
            ("V", 0, 100, "v"),
        ]:
            row = GradientSlider(
                self,
                label=label,
                from_=from_,
                to_=to_,
                on_change=lambda v, k=key: self._on_slider(k, float(v)),
            )
            row.pack(fill="x", padx=10, pady=2)
            self.sliders[key] = row

        self.sliders["h"].set_gradient(
            lambda t: tuple(int(c * 255) for c in colorsys.hsv_to_rgb(t, 1, 1))
        )
        self._build_wheel_image()
        self._refresh_sv_square()
        self._update_markers()
        self._sync_sliders_from_hsv()
        self.apply_theme(LIGHT_THEME)

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.config(bg=theme.panel_bg)
        self.picker_frame.config(bg=theme.panel_bg)
        self.picker_row.config(bg=theme.panel_bg)
        self.wheel_canvas.config(bg=theme.panel_bg)
        self.square_canvas.config(bg=theme.panel_bg)
        self.preview.config(bg=theme.panel_bg)
        _style_button(self.picker_btn, theme)
        for slider in self.sliders.values():
            slider.apply_theme(theme)
        self._cached_hue = None
        self._build_wheel_image()
        self._refresh_sv_square()
        self._update_markers()
        self._draw_preview(rgb_to_hex(self.r, self.g, self.b))

    def get_color(self) -> str:
        return rgb_to_hex(self.r, self.g, self.b)

    def set_color(self, hex_color: str) -> None:
        self._updating = True
        self.r, self.g, self.b = hex_to_rgb(hex_color)
        self.hue, self.sat, self.val = colorsys.rgb_to_hsv(self.r / 255, self.g / 255, self.b / 255)
        self._refresh_sv_square()
        self._update_markers()
        self._sync_sliders_from_hsv()
        self._draw_preview(hex_color)
        self._updating = False

    def set_picker_active(self, active: bool) -> None:
        self.picker_btn.config(relief=tk.SUNKEN if active else tk.RAISED)

    def _emit_color(self) -> None:
        if self._updating:
            return
        hex_color = rgb_to_hex(self.r, self.g, self.b)
        self._draw_preview(hex_color)
        self.on_color_change(hex_color)

    def _draw_preview(self, hex_color: str) -> None:
        self.preview.delete("all")
        self.preview.create_rectangle(
            2, 2, 198, 26, fill=hex_color, outline=self.theme.preview_outline
        )

    def _build_wheel_image(self) -> None:
        size = self._wheel_size
        cx, cy = size / 2, size / 2
        r_outer = size / 2 - 2
        r_inner = self._square_size / 2 + 4
        pixels: list[tuple[int, int, int]] = []
        for y in range(size):
            dy = y - cy
            for x in range(size):
                dx = x - cx
                dist = math.hypot(dx, dy)
                if r_inner <= dist <= r_outer:
                    angle = (math.degrees(math.atan2(dy, dx)) + 90) % 360
                    rgb = colorsys.hsv_to_rgb(angle / 360, 1, 1)
                    pixels.append(tuple(int(c * 255) for c in rgb))
                else:
                    pixels.append(self.theme.wheel_hole)
        img = Image.new("RGB", (size, size))
        img.putdata(pixels)
        self._wheel_photo = ImageTk.PhotoImage(img)
        self.wheel_canvas.delete("all")
        self.wheel_canvas.create_image(0, 0, anchor="nw", image=self._wheel_photo)

    def _refresh_sv_square(self) -> None:
        if self._cached_hue == self.hue and self._square_photo is not None:
            return
        self._cached_hue = self.hue
        sq = self._square_size
        pixels: list[tuple[int, int, int]] = []
        for y in range(sq):
            v = 1 - y / (sq - 1)
            for x in range(sq):
                s = x / (sq - 1)
                rgb = colorsys.hsv_to_rgb(self.hue, s, v)
                pixels.append(tuple(int(c * 255) for c in rgb))
        sq_img = Image.new("RGB", (sq, sq))
        sq_img.putdata(pixels)
        self._square_photo = ImageTk.PhotoImage(sq_img)
        self.square_canvas.delete("all")
        self.square_canvas.create_image(0, 0, anchor="nw", image=self._square_photo)

    def _update_markers(self) -> None:
        self.wheel_canvas.delete("marker")
        self.square_canvas.delete("marker")
        size = self._wheel_size
        cx, cy = size / 2, size / 2
        r_mid = (size / 2 - 2 + self._square_size / 2 + 4) / 2
        angle = math.radians(self.hue * 360 - 90)
        wx = cx + r_mid * math.cos(angle)
        wy = cy + r_mid * math.sin(angle)
        self.wheel_canvas.create_oval(
            wx - 4, wy - 4, wx + 4, wy + 4, outline="white", width=2, tags="marker"
        )

        sq = self._square_size
        sx = self.sat * (sq - 1)
        sy = (1 - self.val) * (sq - 1)
        self.square_canvas.create_oval(
            sx - 4, sy - 4, sx + 4, sy + 4, outline="white", width=2, tags="marker"
        )
        self._draw_preview(rgb_to_hex(self.r, self.g, self.b))

    def _on_wheel_click(self, event: tk.Event) -> None:
        size = self._wheel_size
        cx, cy = size / 2, size / 2
        dx, dy = event.x - cx, event.y - cy
        dist = math.hypot(dx, dy)
        r_inner = self._square_size / 2 + 4
        r_outer = size / 2 - 2
        if dist < r_inner or dist > r_outer:
            return
        angle = (math.degrees(math.atan2(dy, dx)) + 90) % 360
        self.hue = angle / 360
        self._apply_hsv(refresh_square=True)

    def _on_square_click(self, event: tk.Event) -> None:
        sq = self._square_size
        self.sat = clamp(event.x / (sq - 1), 0, 1)
        self.val = clamp(1 - event.y / (sq - 1), 0, 1)
        self._apply_hsv(refresh_square=False)

    def _apply_hsv(self, refresh_square: bool = False) -> None:
        self.r, self.g, self.b = (
            int(c * 255) for c in colorsys.hsv_to_rgb(self.hue, self.sat, self.val)
        )
        self._sync_sliders_from_hsv()
        if refresh_square:
            self._refresh_sv_square()
        self._update_markers()
        self._emit_color()

    def _slider_gradient(self, key: str) -> Callable[[float], tuple[int, int, int]]:
        r, g, b = self.r, self.g, self.b
        h, s, v = self.hue, self.sat, self.val
        if key == "r":
            return lambda t, g=g, b=b: (int(t * 255), g, b)
        if key == "g":
            return lambda t, r=r, b=b: (r, int(t * 255), b)
        if key == "b":
            return lambda t, r=r, g=g: (r, g, int(t * 255))
        if key == "s":
            return lambda t, h=h, v=v: tuple(
                int(c * 255) for c in colorsys.hsv_to_rgb(h, t, v)
            )
        if key == "v":
            return lambda t, h=h, s=s: tuple(
                int(c * 255) for c in colorsys.hsv_to_rgb(h, s, t)
            )
        raise KeyError(key)

    def _refresh_slider_gradients(self) -> None:
        for key in ("r", "g", "b", "s", "v"):
            self.sliders[key].set_gradient(self._slider_gradient(key))

    def _sync_sliders_from_hsv(self) -> None:
        self._updating = True
        self._refresh_slider_gradients()
        self.sliders["r"].set_value(self.r)
        self.sliders["g"].set_value(self.g)
        self.sliders["b"].set_value(self.b)
        self.sliders["h"].set_value(int(self.hue * 360))
        self.sliders["s"].set_value(int(self.sat * 100))
        self.sliders["v"].set_value(int(self.val * 100))
        self._updating = False

    def _on_slider(self, key: str, value: float) -> None:
        if self._updating:
            return
        if key == "r":
            self.r = int(value)
        elif key == "g":
            self.g = int(value)
        elif key == "b":
            self.b = int(value)
        elif key == "h":
            self.hue = value / 360
        elif key == "s":
            self.sat = value / 100
        elif key == "v":
            self.val = value / 100

        if key in ("r", "g", "b"):
            self.hue, self.sat, self.val = colorsys.rgb_to_hsv(
                self.r / 255, self.g / 255, self.b / 255
            )
        else:
            self.r, self.g, self.b = (
                int(c * 255) for c in colorsys.hsv_to_rgb(self.hue, self.sat, self.val)
            )

        hue_changed = key in ("h", "r", "g", "b")
        self._sync_sliders_from_hsv()
        if hue_changed:
            self._refresh_sv_square()
        self._update_markers()
        self._emit_color()


class LayerPanel(tk.Frame):
    """Right panel: layer list ordered top-to-bottom."""

    def __init__(
        self,
        master: tk.Misc,
        on_select: Callable[[int], None],
        on_reorder: Callable[[], None],
        on_delete: Callable[[], None],
    ) -> None:
        super().__init__(master, bg=LIGHT_THEME.panel_bg, width=160)
        self.theme = LIGHT_THEME
        self.title_label = tk.Label(self, text="Layers", font=("Segoe UI", 10, "bold"))
        self.title_label.pack(anchor="w", padx=10, pady=(12, 6))
        self.btn_row = tk.Frame(self)
        self.btn_row.pack(fill="x", padx=8, pady=(0, 6))
        self.up_btn = tk.Button(self.btn_row, text="▲", width=3, command=lambda: self._move(-1))
        self.up_btn.pack(side="left", padx=2)
        self.down_btn = tk.Button(self.btn_row, text="▼", width=3, command=lambda: self._move(1))
        self.down_btn.pack(side="left", padx=2)
        self.delete_btn = tk.Button(self.btn_row, text="Delete", command=on_delete)
        self.delete_btn.pack(side="right", padx=2)

        self._list_container = tk.Frame(self, highlightthickness=1)
        self._list_container.pack(fill="both", expand=True, padx=8, pady=4)

        self.on_select = on_select
        self.on_reorder = on_reorder
        self._rects: list[Rectangle] = []
        self._selected_id: Optional[int] = None
        self._rows: dict[int, tuple[tk.Frame, tk.Canvas, tk.Label]] = {}
        self._layer_order: list[int] = []
        self.apply_theme(LIGHT_THEME)

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.config(bg=theme.panel_bg)
        _style_label(self.title_label, theme)
        self.btn_row.config(bg=theme.panel_bg)
        for btn in (self.up_btn, self.down_btn, self.delete_btn):
            _style_button(btn, theme)
        self._list_container.config(bg=theme.list_bg, highlightbackground=theme.list_border)
        if self._rects:
            self.set_rectangles(self._rects, self._selected_id)

    def set_rectangles(self, rects: list[Rectangle], selected_id: Optional[int]) -> None:
        self._rects = sorted(rects, key=lambda r: r.z_index, reverse=True)
        self._selected_id = selected_id
        order = [rect.id for rect in self._rects]

        if order == self._layer_order and self._rows:
            for rect in self._rects:
                row, swatch, label = self._rows[rect.id]
                swatch.configure(bg=rect.color)
                bg = (
                    self.theme.layer_selected
                    if rect.id == selected_id
                    else self.theme.layer_normal
                )
                row.configure(bg=bg)
                label.configure(bg=bg, fg=self.theme.text)
            return

        for row, _, _ in self._rows.values():
            row.destroy()
        self._rows.clear()
        self._layer_order = order

        for rect in self._rects:
            is_selected = rect.id == selected_id
            row_bg = self.theme.layer_selected if is_selected else self.theme.layer_normal
            row = tk.Frame(self._list_container, bg=row_bg, cursor="hand2")
            row.pack(fill="x", pady=1)
            swatch = tk.Canvas(
                row,
                width=14,
                height=14,
                bg=rect.color,
                highlightthickness=1,
                highlightbackground=self.theme.swatch_border,
            )
            swatch.pack(side="left", padx=(6, 6), pady=4)
            swatch.bind("<Button-1>", lambda _e, rid=rect.id: self.on_select(rid))
            label = tk.Label(
                row,
                text=rect.name,
                anchor="w",
                bg=row_bg,
                fg=self.theme.text,
                font=("Segoe UI", 10),
                width=12,
            )
            label.pack(side="left", fill="x", expand=True)
            for widget in (row, label):
                widget.bind("<Button-1>", lambda _e, rid=rect.id: self.on_select(rid))
            self._rows[rect.id] = (row, swatch, label)

    def _selected_index(self) -> Optional[int]:
        if self._selected_id is None:
            return None
        for i, rect in enumerate(self._rects):
            if rect.id == self._selected_id:
                return i
        return None

    def _move(self, direction: int) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._rects):
            return
        ordered = list(self._rects)
        ordered[idx], ordered[new_idx] = ordered[new_idx], ordered[idx]
        base = len(ordered)
        for i, rect in enumerate(ordered):
            rect.z_index = base - i
        self.on_reorder()


class DrawingCanvas(tk.Canvas):
    """Center canvas: draw, select, resize, move, and rotate rectangles."""

    def __init__(
        self,
        master: tk.Misc,
        on_selection_change: Callable[[Optional[int]], None],
        on_rects_change: Callable[[], None],
        get_new_rect_color: Callable[[], str],
        on_pick_color: Callable[[str], None],
        is_on_layer_draw: Callable[[], bool],
        on_layer_draw_complete: Callable[[], None],
    ) -> None:
        super().__init__(master, highlightthickness=1)
        self.on_selection_change = on_selection_change
        self.on_rects_change = on_rects_change
        self.get_new_rect_color = get_new_rect_color
        self.on_pick_color = on_pick_color
        self.is_on_layer_draw = is_on_layer_draw
        self.on_layer_draw_complete = on_layer_draw_complete
        self.theme = LIGHT_THEME

        self.rectangles: list[Rectangle] = []
        self._picker_mode = False
        self._next_id = 1
        self._next_name = 1
        self.selected_id: Optional[int] = None

        self._drag_mode: Optional[str] = None
        self._drag_start: Optional[tuple[float, float]] = None
        self._drag_rect_snapshot: Optional[Rectangle] = None
        self._draw_start: Optional[tuple[float, float]] = None
        self._preview_id: Optional[int] = None

        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._hovered_handle: Optional[str] = None

        self.paint_canvas = PaintCanvas()
        self.show_canvas_only = False
        self.apply_theme(LIGHT_THEME)

        self.bind("<Button-1>", self._on_left_press)
        self.bind("<B1-Motion>", self._on_left_drag)
        self.bind("<ButtonRelease-1>", self._on_left_release)
        self.bind("<Button-3>", self._on_right_press)
        self.bind("<B3-Motion>", self._on_right_drag)
        self.bind("<ButtonRelease-3>", self._on_right_release)
        self.bind("<MouseWheel>", self._on_mousewheel)
        self.bind("<Button-4>", self._on_mousewheel)
        self.bind("<Button-5>", self._on_mousewheel)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Enter>", lambda _e: self.focus_set())
        self.bind("<Configure>", self._on_configure)

    def _on_configure(self, event: tk.Event) -> None:
        if event.widget is self and self.show_canvas_only:
            self._redraw()

    def _screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx - self._offset_x) / self._scale, (sy - self._offset_y) / self._scale

    def _world_to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        return wx * self._scale + self._offset_x, wy * self._scale + self._offset_y

    def _on_mousewheel(self, event: tk.Event) -> None:
        if hasattr(event, "delta") and event.delta != 0:
            factor = ZOOM_FACTOR if event.delta > 0 else 1 / ZOOM_FACTOR
        elif getattr(event, "num", None) == 4:
            factor = ZOOM_FACTOR
        elif getattr(event, "num", None) == 5:
            factor = 1 / ZOOM_FACTOR
        else:
            return

        mx, my = float(event.x), float(event.y)
        wx, wy = self._screen_to_world(mx, my)
        new_scale = clamp(self._scale * factor, MIN_ZOOM, MAX_ZOOM)
        if new_scale == self._scale:
            return

        self._scale = new_scale
        self._offset_x = mx - wx * new_scale
        self._offset_y = my - wy * new_scale
        self._redraw()

    def get_selected(self) -> Optional[Rectangle]:
        if self.selected_id is None:
            return None
        return next((r for r in self.rectangles if r.id == self.selected_id), None)

    def select(self, rect_id: Optional[int]) -> None:
        self.selected_id = rect_id
        self._hovered_handle = None
        self._redraw()
        self.on_selection_change(rect_id)

    def _handle_hit_radius(self, name: str) -> float:
        if name == "rotate":
            return ROTATION_HANDLE_RADIUS + 8
        return HANDLE_RADIUS + 8

    def set_color(self, hex_color: str) -> None:
        rect = self.get_selected()
        if rect:
            rect.color = hex_color
            self._redraw()
            self.on_rects_change()

    def delete_selected(self) -> None:
        if self.selected_id is None:
            return
        self.rectangles = [r for r in self.rectangles if r.id != self.selected_id]
        self.select(None)
        self.on_rects_change()

    def set_picker_mode(self, active: bool) -> None:
        self._picker_mode = active
        self.config(cursor="crosshair" if active else "")

    def set_paint_size(self, width: float, height: float) -> None:
        self.paint_canvas.width = clamp(width, MIN_PAINT_SIZE, MAX_PAINT_SIZE)
        self.paint_canvas.height = clamp(height, MIN_PAINT_SIZE, MAX_PAINT_SIZE)
        self._redraw()

    def set_show_canvas_only(self, active: bool) -> None:
        self.show_canvas_only = active
        self._redraw()

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.config(bg=theme.canvas_bg, highlightbackground=theme.canvas_border)
        self._redraw()

    def _rect_intersects_paint_canvas(self, rect: Rectangle) -> bool:
        px1, py1, px2, py2 = self.paint_canvas.bounds()
        corners = rect.corners()
        rx1 = min(c[0] for c in corners)
        ry1 = min(c[1] for c in corners)
        rx2 = max(c[0] for c in corners)
        ry2 = max(c[1] for c in corners)
        return not (rx2 < px1 or rx1 > px2 or ry2 < py1 or ry1 > py2)

    def _sorted_rects(self) -> list[Rectangle]:
        return sorted(self.rectangles, key=lambda r: r.z_index)

    def _z_index_above(self, ref_id: int) -> int:
        selected = next(r for r in self.rectangles if r.id == ref_id)
        target = selected.z_index + 1
        for rect in self.rectangles:
            if rect.z_index >= target:
                rect.z_index += 1
        return target

    def _next_top_z_index(self) -> int:
        return max((r.z_index for r in self.rectangles), default=0) + 1

    def _hit_handle(self, rect: Rectangle, sx: float, sy: float) -> Optional[str]:
        for name, (hx, hy) in rect.handle_positions().items():
            screen_hx, screen_hy = self._world_to_screen(hx, hy)
            if math.hypot(sx - screen_hx, sy - screen_hy) <= self._handle_hit_radius(name):
                return name
        return None

    def _update_hovered_handle(self, handle: Optional[str]) -> None:
        if handle != self._hovered_handle:
            self._hovered_handle = handle
            self._redraw()

    def _on_motion(self, event: tk.Event) -> None:
        if self._picker_mode or self._drag_mode:
            self._update_hovered_handle(None)
            return
        selected = self.get_selected()
        if not selected:
            self._update_hovered_handle(None)
            return
        self._update_hovered_handle(self._hit_handle(selected, event.x, event.y))

    def _on_leave(self, _event: tk.Event) -> None:
        self._update_hovered_handle(None)

    def _hit_rect(self, wx: float, wy: float) -> Optional[Rectangle]:
        for rect in reversed(self._sorted_rects()):
            if rect.contains_point(wx, wy):
                return rect
        return None

    def _on_left_press(self, event: tk.Event) -> None:
        px, py = self._screen_to_world(event.x, event.y)

        if self._picker_mode:
            hit = self._hit_rect(px, py)
            if hit:
                self.on_pick_color(hit.color)
            return

        selected = self.get_selected()

        if selected:
            handle = self._hit_handle(selected, event.x, event.y)
            if handle:
                self._drag_mode = handle
                self._drag_start = (px, py)
                self._drag_rect_snapshot = replace(selected)
                return

        hit = self._hit_rect(px, py)
        if hit:
            self.select(hit.id)
            self._drag_mode = "move"
            self._drag_start = (px, py)
            self._drag_rect_snapshot = replace(hit)
            return

        self.select(None)

    def _on_right_press(self, event: tk.Event) -> None:
        px, py = self._screen_to_world(event.x, event.y)
        self._draw_start = (px, py)
        self._drag_mode = "draw"

    def _on_right_drag(self, event: tk.Event) -> None:
        if self._drag_mode != "draw" or not self._draw_start:
            return
        px, py = self._screen_to_world(event.x, event.y)
        x1, y1 = self._draw_start
        sx1, sy1 = self._world_to_screen(x1, y1)
        sx2, sy2 = self._world_to_screen(px, py)
        if self._preview_id:
            self.delete(self._preview_id)
        self._preview_id = self.create_rectangle(
            sx1,
            sy1,
            sx2,
            sy2,
            outline=DRAW_PREVIEW_OUTLINE,
            dash=(4, 4),
            width=1,
        )

    def _on_left_drag(self, event: tk.Event) -> None:
        if self._picker_mode:
            return
        px, py = self._screen_to_world(event.x, event.y)

        rect = self.get_selected()
        if not rect or not self._drag_start or not self._drag_rect_snapshot:
            return

        sx, sy = self._drag_start
        snap = self._drag_rect_snapshot

        if self._drag_mode == "move":
            rect.cx = snap.cx + (px - sx)
            rect.cy = snap.cy + (py - sy)
        elif self._drag_mode == "rotate":
            rect.rotation = math.degrees(
                math.atan2(py - rect.cy, px - rect.cx)
            ) + 90
        elif self._drag_mode in ("nw", "ne", "se", "sw", "n", "s", "e", "w"):
            self._resize_from_handle(rect, snap, self._drag_mode, px, py)
        else:
            return

        self._redraw()

    def _resize_from_handle(
        self,
        rect: Rectangle,
        snap: Rectangle,
        handle: str,
        px: float,
        py: float,
    ) -> None:
        rad = math.radians(-snap.rotation)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        dx, dy = px - snap.cx, py - snap.cy
        lx = dx * cos_a - dy * sin_a
        ly = dx * sin_a + dy * cos_a

        hw, hh = snap.width / 2, snap.height / 2
        left, right = -hw, hw
        top, bottom = -hh, hh

        if "e" in handle:
            right = max(lx, left + MIN_RECT_SIZE)
        if "w" in handle:
            left = min(lx, right - MIN_RECT_SIZE)
        if "s" in handle:
            bottom = max(ly, top + MIN_RECT_SIZE)
        if "n" in handle:
            top = min(ly, bottom - MIN_RECT_SIZE)

        off_x = (left + right) / 2
        off_y = (top + bottom) / 2

        rad_fwd = math.radians(snap.rotation)
        cos_f, sin_f = math.cos(rad_fwd), math.sin(rad_fwd)
        rect.cx = snap.cx + off_x * cos_f - off_y * sin_f
        rect.cy = snap.cy + off_x * sin_f + off_y * cos_f
        rect.width = right - left
        rect.height = bottom - top

    def _on_right_release(self, event: tk.Event) -> None:
        if self._drag_mode == "draw" and self._draw_start:
            x1, y1 = self._draw_start
            x2, y2 = self._screen_to_world(event.x, event.y)
            if self._preview_id:
                self.delete(self._preview_id)
                self._preview_id = None
            w, h = abs(x2 - x1), abs(y2 - y1)
            if w >= MIN_RECT_SIZE and h >= MIN_RECT_SIZE:
                ref_id = self.selected_id
                on_layer = self.is_on_layer_draw() and ref_id is not None
                z_index = self._z_index_above(ref_id) if on_layer else self._next_top_z_index()
                rect = Rectangle(
                    id=self._next_id,
                    name=f"rect{self._next_name}",
                    cx=(x1 + x2) / 2,
                    cy=(y1 + y2) / 2,
                    width=w,
                    height=h,
                    color=self.get_new_rect_color(),
                    z_index=z_index,
                )
                self._next_id += 1
                self._next_name += 1
                self.rectangles.append(rect)
                self.select(rect.id)
                self.on_rects_change()
                if on_layer:
                    self.on_layer_draw_complete()
            self._draw_start = None

        self._drag_mode = None
        self._redraw()

    def _on_left_release(self, _event: tk.Event) -> None:
        if self._picker_mode:
            return
        finished_mode = self._drag_mode
        if finished_mode and finished_mode != "draw":
            self.on_rects_change()

        self._drag_mode = None
        self._drag_start = None
        self._drag_rect_snapshot = None
        self._redraw()

    def _draw_paint_canvas_fill(self) -> None:
        screen_corners = [self._world_to_screen(x, y) for x, y in self.paint_canvas.corners()]
        flat = [coord for pt in screen_corners for coord in pt]
        self.create_polygon(*flat, fill="white", outline="")

    def _draw_paint_canvas_border(self) -> None:
        screen_corners = [self._world_to_screen(x, y) for x, y in self.paint_canvas.corners()]
        for i in range(4):
            x1, y1 = screen_corners[i]
            x2, y2 = screen_corners[(i + 1) % 4]
            self.create_line(x1, y1, x2, y2, fill="black", width=1)

    def _draw_outside_mask(self) -> None:
        x1, y1, x2, y2 = self.paint_canvas.bounds()
        sx1, sy1 = self._world_to_screen(x1, y1)
        sx2, sy2 = self._world_to_screen(x2, y2)
        left, right = min(sx1, sx2), max(sx1, sx2)
        top, bottom = min(sy1, sy2), max(sy1, sy2)
        w = max(self.winfo_width(), 1)
        h = max(self.winfo_height(), 1)
        mask_color = self.theme.canvas_bg
        self.create_rectangle(0, 0, w, top, fill=mask_color, outline="")
        self.create_rectangle(0, bottom, w, h, fill=mask_color, outline="")
        self.create_rectangle(0, top, left, bottom, fill=mask_color, outline="")
        self.create_rectangle(right, top, w, bottom, fill=mask_color, outline="")

    def _should_draw_rect(self, rect: Rectangle) -> bool:
        if not self.show_canvas_only:
            return True
        return self._rect_intersects_paint_canvas(rect)

    def _redraw(self) -> None:
        self.delete("all")
        self._draw_paint_canvas_fill()

        for rect in self._sorted_rects():
            if not self._should_draw_rect(rect):
                continue
            screen_corners = [self._world_to_screen(x, y) for x, y in rect.corners()]
            flat = [coord for pt in screen_corners for coord in pt]
            self.create_polygon(*flat, fill=rect.color, outline="")

        if self.show_canvas_only:
            self._draw_outside_mask()

        selected = self.get_selected()
        if selected and self._should_draw_rect(selected):
            corners = [self._world_to_screen(x, y) for x, y in selected.corners()]
            for i in range(4):
                x1, y1 = corners[i]
                x2, y2 = corners[(i + 1) % 4]
                self.create_line(x1, y1, x2, y2, fill=self.theme.selection_line, width=1)

            handles = {
                name: self._world_to_screen(hx, hy)
                for name, (hx, hy) in selected.handle_positions().items()
            }
            for name, (hx, hy) in handles.items():
                fill = HANDLE_HOVER_FILL if name == self._hovered_handle else HANDLE_FILL
                if name == "rotate":
                    top_mid = handles["n"]
                    self.create_line(
                        top_mid[0], top_mid[1], hx, hy, fill=self.theme.selection_line, width=1
                    )
                    radius = ROTATION_HANDLE_RADIUS
                    self.create_oval(
                        hx - radius,
                        hy - radius,
                        hx + radius,
                        hy + radius,
                        fill=fill,
                        outline=HANDLE_OUTLINE,
                    )
                    self.create_text(
                        hx,
                        hy - 12,
                        text="↻",
                        fill=HANDLE_TEXT,
                        font=("Segoe UI", 9),
                    )
                else:
                    self.create_oval(
                        hx - HANDLE_RADIUS,
                        hy - HANDLE_RADIUS,
                        hx + HANDLE_RADIUS,
                        hy + HANDLE_RADIUS,
                        fill=fill,
                        outline=HANDLE_OUTLINE,
                    )

        self._draw_paint_canvas_border()


class DrawingApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Rectangle Drawing Tool")
        self.root.geometry("1100x650")
        self.root.minsize(540, 360)

        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self._picker_button_active = False
        self._alt_held = False
        self._on_layer_button_armed = False
        self._ctrl_held = False
        self._show_canvas_only_active = False
        self._dark_mode = False
        self.theme = LIGHT_THEME

        self.palette = ColorPalette(
            self.root,
            on_color_change=self._on_color_change,
            on_picker_toggle=self._on_picker_toggle,
        )
        self.palette.grid(row=0, column=0, sticky="ns", padx=(8, 4), pady=8)

        self.canvas_frame = tk.Frame(self.root)
        self.canvas_frame.grid(row=0, column=1, sticky="nsew", pady=8, padx=4)
        self.canvas_frame.rowconfigure(1, weight=1)
        self.canvas_frame.columnconfigure(0, weight=1)

        self.toolbar = tk.Frame(self.canvas_frame)
        self.toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.width_label = tk.Label(self.toolbar, text="Canvas Width:", font=("Segoe UI", 9))
        self.width_label.pack(side="left", padx=(4, 2))
        self.width_entry = tk.Entry(self.toolbar, width=7, font=("Consolas", 9))
        self.width_entry.pack(side="left", padx=(0, 10))
        self.width_entry.insert(0, str(int(DEFAULT_PAINT_WIDTH)))

        self.height_label = tk.Label(self.toolbar, text="Height:", font=("Segoe UI", 9))
        self.height_label.pack(side="left", padx=(0, 2))
        self.height_entry = tk.Entry(self.toolbar, width=7, font=("Consolas", 9))
        self.height_entry.pack(side="left", padx=(0, 10))
        self.height_entry.insert(0, str(int(DEFAULT_PAINT_HEIGHT)))

        self.show_canvas_btn = tk.Button(
            self.toolbar,
            text="Show Canvas Only (Tab)",
            command=self._toggle_show_canvas_only,
            font=("Segoe UI", 9),
        )
        self.show_canvas_btn.pack(side="left", padx=4)

        self.on_layer_btn = tk.Button(
            self.toolbar,
            text="On Layer (Ctrl)",
            command=self._on_on_layer_arm,
            font=("Segoe UI", 9),
            state="disabled",
        )
        self.on_layer_btn.pack(side="left", padx=4)

        self.dark_mode_btn = tk.Button(
            self.toolbar,
            text="Dark Mode",
            command=self._toggle_dark_mode,
            font=("Segoe UI", 9),
        )
        self.dark_mode_btn.pack(side="right", padx=4)

        for entry in (self.width_entry, self.height_entry):
            entry.bind("<Return>", self._on_paint_size_apply)
            entry.bind("<FocusOut>", self._on_paint_size_apply)

        self.canvas = DrawingCanvas(
            self.canvas_frame,
            on_selection_change=self._on_selection_change,
            on_rects_change=self._on_rects_change,
            get_new_rect_color=self.palette.get_color,
            on_pick_color=self._on_pick_color,
            is_on_layer_draw=self._is_on_layer_draw,
            on_layer_draw_complete=self._on_layer_draw_complete,
        )
        self.canvas.grid(row=1, column=0, sticky="nsew")

        self.root.bind_all("<Alt_L>", self._on_alt_press)
        self.root.bind_all("<Alt_R>", self._on_alt_press)
        self.root.bind_all("<KeyRelease-Alt_L>", self._on_alt_release)
        self.root.bind_all("<KeyRelease-Alt_R>", self._on_alt_release)
        self.root.bind_all("<Control_L>", self._on_ctrl_press)
        self.root.bind_all("<Control_R>", self._on_ctrl_press)
        self.root.bind_all("<KeyRelease-Control_L>", self._on_ctrl_release)
        self.root.bind_all("<KeyRelease-Control_R>", self._on_ctrl_release)
        self.root.bind_all("<Tab>", self._on_tab_press)

        self.layers = LayerPanel(
            self.root,
            on_select=self._on_layer_select,
            on_reorder=self._on_rects_change,
            on_delete=self._on_delete,
        )
        self.layers.grid(row=0, column=2, sticky="ns", padx=(4, 8), pady=8)

        self._syncing_color = False
        self._apply_theme()
        self._seed_demo_rects()

    def _seed_demo_rects(self) -> None:
        demos = [
            Rectangle(1, "rect1", 180, 420, 200, 70, 0, "#3b6fc7", 1),
            Rectangle(2, "rect2", 520, 340, 90, 220, -18, "#e8a87c", 2),
            Rectangle(3, "rect3", 300, 200, 55, 55, 0, "#5cb85c", 3),
            Rectangle(4, "rect4", 420, 130, 160, 45, 0, "#5bc0de", 4),
        ]
        self.canvas.rectangles = demos
        self.canvas._next_id = 5
        self.canvas._next_name = 5
        self.canvas.select(2)
        self._on_rects_change()

    def _on_selection_change(self, rect_id: Optional[int]) -> None:
        rect = self.canvas.get_selected()
        self.layers.set_rectangles(self.canvas.rectangles, rect_id)
        self.layers.delete_btn.config(state="normal" if rect_id is not None else "disabled")
        if rect_id is None:
            self._on_layer_button_armed = False
        self._update_on_layer_mode()
        if rect and not self._syncing_color:
            self._syncing_color = True
            self.palette.set_color(rect.color)
            self._syncing_color = False

    def _on_color_change(self, hex_color: str) -> None:
        if self._syncing_color:
            return
        self.canvas.set_color(hex_color)
        self.layers.set_rectangles(self.canvas.rectangles, self.canvas.selected_id)

    def _on_layer_select(self, rect_id: int) -> None:
        self.canvas.select(rect_id)
        self._on_selection_change(rect_id)

    def _on_rects_change(self) -> None:
        self.layers.set_rectangles(self.canvas.rectangles, self.canvas.selected_id)

    def _on_delete(self) -> None:
        self.canvas.delete_selected()

    def _update_picker_mode(self) -> None:
        active = self._picker_button_active or self._alt_held
        self.canvas.set_picker_mode(active)
        self.palette.set_picker_active(active)

    def _on_picker_toggle(self) -> None:
        self._picker_button_active = not self._picker_button_active
        self._update_picker_mode()

    def _on_alt_press(self, _event: tk.Event) -> str:
        self._alt_held = True
        self._update_picker_mode()
        return "break"

    def _on_alt_release(self, _event: tk.Event) -> None:
        self._alt_held = False
        self._update_picker_mode()

    def _is_on_layer_draw(self) -> bool:
        if self.canvas.selected_id is None:
            return False
        return self._on_layer_button_armed or self._ctrl_held

    def _update_on_layer_mode(self) -> None:
        has_selection = self.canvas.selected_id is not None
        active = self._is_on_layer_draw()
        self.on_layer_btn.config(
            state="normal" if has_selection else "disabled",
            relief=tk.SUNKEN if active else tk.RAISED,
        )

    def _on_on_layer_arm(self) -> None:
        if self.canvas.selected_id is None:
            return
        self._on_layer_button_armed = True
        self._update_on_layer_mode()

    def _on_layer_draw_complete(self) -> None:
        self._on_layer_button_armed = False
        self._update_on_layer_mode()

    def _on_ctrl_press(self, event: tk.Event) -> Optional[str]:
        if isinstance(event.widget, tk.Entry):
            return None
        self._ctrl_held = True
        self._update_on_layer_mode()
        return "break"

    def _on_ctrl_release(self, _event: tk.Event) -> None:
        self._ctrl_held = False
        self._update_on_layer_mode()

    def _on_pick_color(self, hex_color: str) -> None:
        self._syncing_color = True
        self.palette.set_color(hex_color)
        self._syncing_color = False
        self.canvas.set_color(hex_color)
        self.layers.set_rectangles(self.canvas.rectangles, self.canvas.selected_id)

    def _on_paint_size_apply(self, _event: Optional[tk.Event] = None) -> None:
        try:
            width = float(self.width_entry.get())
            height = float(self.height_entry.get())
        except ValueError:
            self.width_entry.delete(0, tk.END)
            self.width_entry.insert(0, str(int(self.canvas.paint_canvas.width)))
            self.height_entry.delete(0, tk.END)
            self.height_entry.insert(0, str(int(self.canvas.paint_canvas.height)))
            return
        self.canvas.set_paint_size(width, height)
        self.width_entry.delete(0, tk.END)
        self.width_entry.insert(0, str(int(self.canvas.paint_canvas.width)))
        self.height_entry.delete(0, tk.END)
        self.height_entry.insert(0, str(int(self.canvas.paint_canvas.height)))

    def _update_show_canvas_only(self) -> None:
        self.canvas.set_show_canvas_only(self._show_canvas_only_active)
        self.show_canvas_btn.config(
            relief=tk.SUNKEN if self._show_canvas_only_active else tk.RAISED
        )

    def _toggle_show_canvas_only(self) -> None:
        self._show_canvas_only_active = not self._show_canvas_only_active
        self._update_show_canvas_only()

    def _on_tab_press(self, event: tk.Event) -> Optional[str]:
        if isinstance(event.widget, tk.Entry):
            return None
        self._toggle_show_canvas_only()
        return "break"

    def _toggle_dark_mode(self) -> None:
        self._dark_mode = not self._dark_mode
        self._apply_theme()

    def _apply_theme(self) -> None:
        self.theme = DARK_THEME if self._dark_mode else LIGHT_THEME
        self.root.config(bg=self.theme.app_bg)
        self.canvas_frame.config(bg=self.theme.app_bg)
        self.toolbar.config(bg=self.theme.app_bg)
        for label in (self.width_label, self.height_label):
            label.config(bg=self.theme.app_bg, fg=self.theme.text)
        for entry in (self.width_entry, self.height_entry):
            _style_entry(entry, self.theme)
        for btn in (self.show_canvas_btn, self.on_layer_btn, self.dark_mode_btn):
            _style_button(btn, self.theme)
        self._update_on_layer_mode()
        self.dark_mode_btn.config(
            text="Light Mode" if self._dark_mode else "Dark Mode",
            relief=tk.SUNKEN if self._dark_mode else tk.RAISED,
        )
        self.palette.apply_theme(self.theme)
        self.canvas.apply_theme(self.theme)
        self.layers.apply_theme(self.theme)

    def run(self) -> None:
        self.root.mainloop()
