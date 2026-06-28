"""Vector drawing tool with color palette, canvas, and layer panel."""

from __future__ import annotations

import colorsys
import ctypes
import json
import math
import queue
import tkinter as tk
from dataclasses import dataclass, replace
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable, Optional

from PIL import Image, ImageTk

from draw_objects import (
    DEFAULT_LINE_WIDTH,
    DrawObject,
    DrawTool,
    Line,
    MAX_LINE_WIDTH,
    MIN_LINE_LENGTH,
    MIN_LINE_WIDTH,
    MIN_RECT_SIZE,
    MIN_TRIANGLE_AREA,
    Rectangle,
    Triangle,
    intersects_paint_canvas,
    next_top_z_index,
    sorted_shapes,
    triangle_area,
    z_index_above,
)
from drawing_file import (
    FILE_EXTENSION,
    LoadedDocument,
    build_document,
    file_dialog_types,
    load_document,
    save_document,
)
from canvas_render import (
    ColorVisMode,
    RenderContext,
    draw_outside_mask,
    draw_paint_canvas_border,
    draw_paint_canvas_fill,
    draw_shape,
    hex_to_rgb,
    rgb_to_hex,
)
from lab_palette import LabColorPicker

try:
    import windnd

    _HAS_FILE_DROP = True
except ImportError:
    _HAS_FILE_DROP = False

_FILE_DROP_QUEUE: queue.Queue[list] = queue.Queue()
_PYTHONAPI = ctypes.pythonapi
_PYTHONAPI.PyGILState_Ensure.restype = ctypes.c_void_p
_PYTHONAPI.PyGILState_Release.argtypes = [ctypes.c_void_p]


def _enqueue_dropped_files(files: list) -> None:
    """Called from the Windows WndProc; must acquire the GIL before touching Python."""
    gil_state = _PYTHONAPI.PyGILState_Ensure()
    try:
        _FILE_DROP_QUEUE.put(list(files))
    finally:
        _PYTHONAPI.PyGILState_Release(gil_state)


HANDLE_RADIUS = 4
ROTATION_HANDLE_RADIUS = 10
ROTATION_HANDLE_OFFSET = 28
HANDLE_FILL = "#f0f0f0"
HANDLE_HOVER_FILL = "#404040"
HANDLE_OUTLINE = "#333333"
HANDLE_TEXT = "#333333"
DRAW_PREVIEW_OUTLINE = "#666666"
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


def _style_menubutton(btn: tk.Menubutton, theme: Theme) -> None:
    btn.config(
        bg=theme.button_bg,
        fg=theme.button_fg,
        activebackground=theme.button_active_bg,
        activeforeground=theme.button_fg,
    )


def _style_menu(menu: tk.Menu, theme: Theme) -> None:
    menu.config(
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
        on_line_width_change: Callable[[float], None],
    ) -> None:
        super().__init__(master, bg=LIGHT_THEME.panel_bg, width=220)
        self.on_color_change = on_color_change
        self.on_line_width_change = on_line_width_change
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
        self.picker_frame.pack(pady=(4, 4))

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

        self.preview = tk.Canvas(self, width=80, height=18, highlightthickness=0)
        self.preview.pack(pady=(0, 0))

        self.lab_picker = LabColorPicker(self, on_change=self._on_lab_change)
        self.lab_picker.pack(pady=(0, 2))

        self.picker_row = tk.Frame(self)
        self.picker_row.pack(fill="x", padx=10, pady=(2, 6))
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

        self.line_width_slider = GradientSlider(
            self,
            label="W",
            from_=MIN_LINE_WIDTH,
            to_=MAX_LINE_WIDTH,
            on_change=lambda v: self._on_line_width_slider(float(v)),
        )
        self.line_width_slider.set_gradient(
            lambda t: (int(t * 180), int(t * 180), int(t * 180))
        )
        self.line_width_slider.set_value(DEFAULT_LINE_WIDTH)

        self._build_wheel_image()
        self._refresh_sv_square()
        self._update_markers()
        self._sync_sliders_from_hsv()
        self.apply_theme(LIGHT_THEME)
        self.lab_picker.set_from_rgb(self.r, self.g, self.b)

    def _sync_lab_picker(self) -> None:
        self.lab_picker.set_from_rgb(self.r, self.g, self.b)

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
        self.line_width_slider.apply_theme(theme)
        self.lab_picker.apply_theme(
            theme.panel_bg,
            theme.text,
            theme.slider_outline,
            theme.thumb_fill,
            theme.thumb_outline,
        )
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
        self.lab_picker.set_from_rgb(self.r, self.g, self.b)
        self._updating = False

    def set_picker_active(self, active: bool) -> None:
        self.picker_btn.config(relief=tk.SUNKEN if active else tk.RAISED)

    def set_line_width_controls_visible(self, visible: bool) -> None:
        if visible:
            self.line_width_slider.pack(fill="x", padx=10, pady=(0, 6))
        else:
            self.line_width_slider.pack_forget()

    def set_line_width_value(self, width: float) -> None:
        self.line_width_slider.set_value(width)

    def _on_line_width_slider(self, value: float) -> None:
        self.on_line_width_change(value)

    def _on_lab_change(self) -> None:
        if self._updating:
            return
        self.r, self.g, self.b = self.lab_picker.get_rgb()
        self.hue, self.sat, self.val = colorsys.rgb_to_hsv(
            self.r / 255, self.g / 255, self.b / 255
        )
        self._sync_sliders_from_hsv()
        self._update_markers()
        self._emit_color()

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
        self._sync_lab_picker()
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
        self._sync_lab_picker()
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
        self._shapes: list[DrawObject] = []
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
        if self._shapes:
            self.set_shapes(self._shapes, self._selected_id)

    def set_shapes(self, shapes: list[DrawObject], selected_id: Optional[int]) -> None:
        self._shapes = sorted(shapes, key=lambda shape: shape.z_index, reverse=True)
        self._selected_id = selected_id
        order = [shape.id for shape in self._shapes]

        if order == self._layer_order and self._rows:
            for shape in self._shapes:
                row, swatch, label = self._rows[shape.id]
                swatch.configure(bg=shape.color)
                bg = (
                    self.theme.layer_selected
                    if shape.id == selected_id
                    else self.theme.layer_normal
                )
                row.configure(bg=bg)
                label.configure(bg=bg, fg=self.theme.text)
            return

        for row, _, _ in self._rows.values():
            row.destroy()
        self._rows.clear()
        self._layer_order = order

        for shape in self._shapes:
            is_selected = shape.id == selected_id
            row_bg = self.theme.layer_selected if is_selected else self.theme.layer_normal
            row = tk.Frame(self._list_container, bg=row_bg, cursor="hand2")
            row.pack(fill="x", pady=1)
            swatch = tk.Canvas(
                row,
                width=14,
                height=14,
                bg=shape.color,
                highlightthickness=1,
                highlightbackground=self.theme.swatch_border,
            )
            swatch.pack(side="left", padx=(6, 6), pady=4)
            swatch.bind("<Button-1>", lambda _e, sid=shape.id: self.on_select(sid))
            label = tk.Label(
                row,
                text=shape.name,
                anchor="w",
                bg=row_bg,
                fg=self.theme.text,
                font=("Segoe UI", 10),
                width=12,
            )
            label.pack(side="left", fill="x", expand=True)
            for widget in (row, label):
                widget.bind("<Button-1>", lambda _e, sid=shape.id: self.on_select(sid))
            self._rows[shape.id] = (row, swatch, label)

    def set_rectangles(self, shapes: list[DrawObject], selected_id: Optional[int]) -> None:
        self.set_shapes(shapes, selected_id)

    def _selected_index(self) -> Optional[int]:
        if self._selected_id is None:
            return None
        for i, rect in enumerate(self._shapes):
            if rect.id == self._selected_id:
                return i
        return None

    def _move(self, direction: int) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._shapes):
            return
        ordered = list(self._shapes)
        ordered[idx], ordered[new_idx] = ordered[new_idx], ordered[idx]
        base = len(ordered)
        for i, rect in enumerate(ordered):
            rect.z_index = base - i
        self.on_reorder()


class DrawingCanvas(tk.Canvas):
    """Center canvas: draw, select, and edit shapes."""

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

        self.shapes: list[DrawObject] = []
        self.draw_tool: DrawTool = "rectangle"
        self._picker_mode = False
        self._next_id = 1
        self._next_rect_name = 1
        self._next_line_name = 1
        self._next_triangle_name = 1
        self._next_line_width = DEFAULT_LINE_WIDTH
        self.selected_id: Optional[int] = None

        self._drag_mode: Optional[str] = None
        self._drag_start: Optional[tuple[float, float]] = None
        self._drag_snapshot: Optional[DrawObject] = None
        self._draw_start: Optional[tuple[float, float]] = None
        self._preview_id: Optional[int] = None
        self._preview_ids: list[int] = []
        self._triangle_vertices: list[tuple[float, float]] = []

        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._hovered_handle: Optional[str] = None

        self.paint_canvas = PaintCanvas()
        self.show_canvas_only = False
        self.color_vis_mode: ColorVisMode = "normal"
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

    def set_draw_tool(self, tool: DrawTool) -> None:
        if tool != self.draw_tool:
            self._cancel_triangle_draw()
        self.draw_tool = tool

    def _cancel_triangle_draw(self) -> None:
        self._triangle_vertices.clear()
        self._clear_draw_previews()

    def _clear_draw_previews(self) -> None:
        if self._preview_id is not None:
            self.delete(self._preview_id)
            self._preview_id = None
        for pid in self._preview_ids:
            self.delete(pid)
        self._preview_ids.clear()

    def _show_triangle_build_preview(
        self, cursor_sx: Optional[float] = None, cursor_sy: Optional[float] = None
    ) -> None:
        self._clear_draw_previews()
        verts = self._triangle_vertices
        if not verts:
            return

        for wx, wy in verts:
            sx, sy = self._world_to_screen(wx, wy)
            pid = self.create_oval(
                sx - 4,
                sy - 4,
                sx + 4,
                sy + 4,
                outline=DRAW_PREVIEW_OUTLINE,
                fill="",
                width=1,
            )
            self._preview_ids.append(pid)

        screen_verts = [self._world_to_screen(wx, wy) for wx, wy in verts]
        if len(screen_verts) >= 2 and cursor_sx is None:
            x1, y1 = screen_verts[0]
            x2, y2 = screen_verts[1]
            pid = self.create_line(
                x1, y1, x2, y2, fill=DRAW_PREVIEW_OUTLINE, dash=(4, 4), width=1
            )
            self._preview_ids.append(pid)

        if len(screen_verts) == 2 and cursor_sx is not None and cursor_sy is not None:
            x1, y1 = screen_verts[0]
            x2, y2 = screen_verts[1]
            for ax, ay, bx, by in (
                (x1, y1, x2, y2),
                (x2, y2, cursor_sx, cursor_sy),
                (cursor_sx, cursor_sy, x1, y1),
            ):
                pid = self.create_line(
                    ax, ay, bx, by, fill=DRAW_PREVIEW_OUTLINE, dash=(4, 4), width=1
                )
                self._preview_ids.append(pid)

    def _add_triangle_vertex(self, wx: float, wy: float) -> None:
        self._triangle_vertices.append((wx, wy))
        if len(self._triangle_vertices) < 3:
            self._show_triangle_build_preview()
            return

        (x1, y1), (x2, y2), (x3, y3) = self._triangle_vertices
        if triangle_area(x1, y1, x2, y2, x3, y3) < MIN_TRIANGLE_AREA:
            self._triangle_vertices = [(wx, wy)]
            self._show_triangle_build_preview()
            return

        ref_id = self.selected_id
        on_layer = self.is_on_layer_draw() and ref_id is not None
        z_index = z_index_above(self.shapes, ref_id) if on_layer else next_top_z_index(self.shapes)
        tri = Triangle(
            id=self._next_id,
            name=f"tri{self._next_triangle_name}",
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            x3=x3,
            y3=y3,
            color=self.get_new_rect_color(),
            z_index=z_index,
        )
        self._next_id += 1
        self._next_triangle_name += 1
        self.shapes.append(tri)
        self._triangle_vertices.clear()
        self._clear_draw_previews()
        self.select(tri.id)
        self.on_rects_change()
        if on_layer:
            self.on_layer_draw_complete()
        self._redraw()

    def get_selected(self) -> Optional[DrawObject]:
        if self.selected_id is None:
            return None
        return next((shape for shape in self.shapes if shape.id == self.selected_id), None)

    def select(self, shape_id: Optional[int]) -> None:
        self.selected_id = shape_id
        self._hovered_handle = None
        shape = self.get_selected()
        if isinstance(shape, Line):
            self._next_line_width = shape.stroke_width
        self._redraw()
        self.on_selection_change(shape_id)

    def _handle_hit_radius(self, name: str) -> float:
        if name == "rotate":
            return ROTATION_HANDLE_RADIUS + 8
        if name == "move":
            return HANDLE_RADIUS + 10
        return HANDLE_RADIUS + 8

    def set_color(self, hex_color: str) -> None:
        shape = self.get_selected()
        if shape:
            shape.color = hex_color
            self._redraw()
            self.on_rects_change()

    def set_line_width(self, width: float) -> None:
        width = clamp(width, MIN_LINE_WIDTH, MAX_LINE_WIDTH)
        self._next_line_width = width
        shape = self.get_selected()
        if isinstance(shape, Line):
            shape.stroke_width = width
            self._redraw()
            self.on_rects_change()

    def delete_selected(self) -> None:
        if self.selected_id is None:
            return
        self.shapes = [shape for shape in self.shapes if shape.id != self.selected_id]
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

    def set_color_vis_mode(self, mode: ColorVisMode) -> None:
        self.color_vis_mode = mode
        self._redraw()

    def _render_context(self) -> RenderContext:
        return RenderContext(
            canvas=self,
            world_to_screen=self._world_to_screen,
            scale=self._scale,
            color_mode=self.color_vis_mode,
        )

    def import_document(self, doc: LoadedDocument) -> None:
        self._cancel_triangle_draw()
        self.shapes = list(doc.shapes)
        self.paint_canvas.cx = doc.paint_canvas["cx"]
        self.paint_canvas.cy = doc.paint_canvas["cy"]
        self.paint_canvas.width = doc.paint_canvas["width"]
        self.paint_canvas.height = doc.paint_canvas["height"]
        self._next_id = doc.next_id
        self._next_rect_name = doc.next_rect_name
        self._next_line_name = doc.next_line_name
        self._next_triangle_name = doc.next_triangle_name
        self._next_line_width = doc.next_line_width
        self.draw_tool = doc.draw_tool
        self.select(doc.selected_id)

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.config(bg=theme.canvas_bg, highlightbackground=theme.canvas_border)
        self._redraw()

    def _should_draw_shape(self, shape: DrawObject) -> bool:
        if not self.show_canvas_only:
            return True
        return intersects_paint_canvas(shape, self.paint_canvas.bounds())

    def _hit_handle(self, shape: DrawObject, sx: float, sy: float) -> Optional[str]:
        for name, (hx, hy) in shape.handle_positions().items():
            screen_hx, screen_hy = self._world_to_screen(hx, hy)
            if math.hypot(sx - screen_hx, sy - screen_hy) <= self._handle_hit_radius(name):
                return name
        return None

    def _update_hovered_handle(self, handle: Optional[str]) -> None:
        if handle != self._hovered_handle:
            self._hovered_handle = handle
            self._redraw()

    def _on_motion(self, event: tk.Event) -> None:
        if (
            self.draw_tool == "triangle"
            and self._triangle_vertices
            and not self._drag_mode
            and not self._picker_mode
        ):
            self._show_triangle_build_preview(event.x, event.y)

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

    def _hit_shape(self, wx: float, wy: float) -> Optional[DrawObject]:
        for shape in reversed(sorted_shapes(self.shapes)):
            if shape.contains_point(wx, wy):
                return shape
        return None

    def _on_left_press(self, event: tk.Event) -> None:
        px, py = self._screen_to_world(event.x, event.y)

        if self._picker_mode:
            hit = self._hit_shape(px, py)
            if hit:
                self.on_pick_color(hit.color)
            return

        selected = self.get_selected()

        if selected:
            handle = self._hit_handle(selected, event.x, event.y)
            if handle:
                self._drag_mode = handle
                self._drag_start = (px, py)
                self._drag_snapshot = replace(selected)
                return

        hit = self._hit_shape(px, py)
        if hit:
            self.select(hit.id)
            self._drag_mode = "move"
            self._drag_start = (px, py)
            self._drag_snapshot = replace(hit)
            return

        self.select(None)

    def _on_right_press(self, event: tk.Event) -> None:
        px, py = self._screen_to_world(event.x, event.y)
        if self.draw_tool == "triangle":
            self._add_triangle_vertex(px, py)
            return
        self._draw_start = (px, py)
        self._drag_mode = "draw"

    def _on_right_drag(self, event: tk.Event) -> None:
        if self.draw_tool == "triangle":
            return
        if self._drag_mode != "draw" or not self._draw_start:
            return
        px, py = self._screen_to_world(event.x, event.y)
        x1, y1 = self._draw_start
        sx1, sy1 = self._world_to_screen(x1, y1)
        sx2, sy2 = self._world_to_screen(px, py)
        if self._preview_id:
            self.delete(self._preview_id)
        if self.draw_tool == "line":
            self._preview_id = self.create_line(
                sx1,
                sy1,
                sx2,
                sy2,
                fill=DRAW_PREVIEW_OUTLINE,
                dash=(4, 4),
                width=1,
            )
        else:
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

        shape = self.get_selected()
        if not shape or not self._drag_start or not self._drag_snapshot:
            return

        sx, sy = self._drag_start
        snap = self._drag_snapshot

        if isinstance(shape, Line):
            if self._drag_mode == "move":
                dx, dy = px - sx, py - sy
                shape.x1 = snap.x1 + dx
                shape.y1 = snap.y1 + dy
                shape.x2 = snap.x2 + dx
                shape.y2 = snap.y2 + dy
            elif self._drag_mode == "p1":
                shape.x1, shape.y1 = px, py
            elif self._drag_mode == "p2":
                shape.x2, shape.y2 = px, py
            else:
                return
        elif isinstance(shape, Rectangle):
            if self._drag_mode == "move":
                shape.cx = snap.cx + (px - sx)
                shape.cy = snap.cy + (py - sy)
            elif self._drag_mode == "rotate":
                shape.rotation = math.degrees(
                    math.atan2(py - shape.cy, px - shape.cx)
                ) + 90
            elif self._drag_mode in ("nw", "ne", "se", "sw", "n", "s", "e", "w"):
                self._resize_from_handle(shape, snap, self._drag_mode, px, py)
            else:
                return
        elif isinstance(shape, Triangle):
            if self._drag_mode == "move":
                dx, dy = px - sx, py - sy
                shape.x1 = snap.x1 + dx
                shape.y1 = snap.y1 + dy
                shape.x2 = snap.x2 + dx
                shape.y2 = snap.y2 + dy
                shape.x3 = snap.x3 + dx
                shape.y3 = snap.y3 + dy
            elif self._drag_mode == "v1":
                shape.x1, shape.y1 = px, py
            elif self._drag_mode == "v2":
                shape.x2, shape.y2 = px, py
            elif self._drag_mode == "v3":
                shape.x3, shape.y3 = px, py
            elif self._drag_mode == "rotate":
                target = math.degrees(math.atan2(py - snap.cy, px - snap.cx)) + 90
                shape.rotate_to_angle(snap, target)
            else:
                return
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
        if self.draw_tool == "triangle":
            return
        if self._drag_mode == "draw" and self._draw_start:
            x1, y1 = self._draw_start
            x2, y2 = self._screen_to_world(event.x, event.y)
            if self._preview_id:
                self.delete(self._preview_id)
                self._preview_id = None
            ref_id = self.selected_id
            on_layer = self.is_on_layer_draw() and ref_id is not None
            z_index = z_index_above(self.shapes, ref_id) if on_layer else next_top_z_index(self.shapes)
            created = False

            if self.draw_tool == "line":
                length = math.hypot(x2 - x1, y2 - y1)
                if length >= MIN_LINE_LENGTH:
                    line = Line(
                        id=self._next_id,
                        name=f"line{self._next_line_name}",
                        x1=x1,
                        y1=y1,
                        x2=x2,
                        y2=y2,
                        color=self.get_new_rect_color(),
                        stroke_width=self._next_line_width,
                        z_index=z_index,
                    )
                    self._next_id += 1
                    self._next_line_name += 1
                    self.shapes.append(line)
                    self.select(line.id)
                    self.on_rects_change()
                    created = True
            else:
                w, h = abs(x2 - x1), abs(y2 - y1)
                if w >= MIN_RECT_SIZE and h >= MIN_RECT_SIZE:
                    rect = Rectangle(
                        id=self._next_id,
                        name=f"rect{self._next_rect_name}",
                        cx=(x1 + x2) / 2,
                        cy=(y1 + y2) / 2,
                        width=w,
                        height=h,
                        color=self.get_new_rect_color(),
                        z_index=z_index,
                    )
                    self._next_id += 1
                    self._next_rect_name += 1
                    self.shapes.append(rect)
                    self.select(rect.id)
                    self.on_rects_change()
                    created = True

            if created and on_layer:
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
        self._drag_snapshot = None
        self._redraw()

    def _draw_paint_canvas_fill(self) -> None:
        draw_paint_canvas_fill(self.paint_canvas, self._render_context())

    def _draw_paint_canvas_border(self) -> None:
        draw_paint_canvas_border(self.paint_canvas, self._render_context())

    def _draw_outside_mask(self) -> None:
        draw_outside_mask(
            self.paint_canvas,
            self._render_context(),
            canvas_width=self.winfo_width(),
            canvas_height=self.winfo_height(),
            mask_color=self.theme.canvas_bg,
        )

    def _draw_shape(self, shape: DrawObject) -> None:
        draw_shape(shape, self._render_context())

    def _draw_selection_handles(self, shape: DrawObject) -> None:
        if isinstance(shape, Rectangle):
            corners = [self._world_to_screen(x, y) for x, y in shape.corners()]
            for i in range(4):
                x1, y1 = corners[i]
                x2, y2 = corners[(i + 1) % 4]
                self.create_line(x1, y1, x2, y2, fill=self.theme.selection_line, width=1)

            handles = {
                name: self._world_to_screen(hx, hy)
                for name, (hx, hy) in shape.handle_positions().items()
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
        elif isinstance(shape, Line):
            handles = {
                name: self._world_to_screen(hx, hy)
                for name, (hx, hy) in shape.handle_positions().items()
            }
            mid = self._world_to_screen(shape.cx, shape.cy)
            move = handles["move"]
            self.create_line(mid[0], mid[1], move[0], move[1], fill=self.theme.selection_line, width=1)
            for name in ("p1", "p2", "move"):
                hx, hy = handles[name]
                fill = HANDLE_HOVER_FILL if name == self._hovered_handle else HANDLE_FILL
                radius = HANDLE_RADIUS if name != "move" else HANDLE_RADIUS + 2
                self.create_oval(
                    hx - radius,
                    hy - radius,
                    hx + radius,
                    hy + radius,
                    fill=fill,
                    outline=HANDLE_OUTLINE,
                )
                if name == "move":
                    self.create_text(
                        hx,
                        hy,
                        text="✥",
                        fill=HANDLE_TEXT,
                        font=("Segoe UI", 10),
                    )
        elif isinstance(shape, Triangle):
            corners = [self._world_to_screen(x, y) for x, y in shape.vertices()]
            for i in range(3):
                x1, y1 = corners[i]
                x2, y2 = corners[(i + 1) % 3]
                self.create_line(x1, y1, x2, y2, fill=self.theme.selection_line, width=1)

            handles = {
                name: self._world_to_screen(hx, hy)
                for name, (hx, hy) in shape.handle_positions().items()
            }
            anchor = self._world_to_screen(*shape.reference_midpoint())
            for name, (hx, hy) in handles.items():
                fill = HANDLE_HOVER_FILL if name == self._hovered_handle else HANDLE_FILL
                if name == "rotate":
                    self.create_line(
                        anchor[0], anchor[1], hx, hy, fill=self.theme.selection_line, width=1
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

    def _redraw(self) -> None:
        self.delete("all")
        self._draw_paint_canvas_fill()

        for shape in sorted_shapes(self.shapes):
            if not self._should_draw_shape(shape):
                continue
            self._draw_shape(shape)

        if self.show_canvas_only:
            self._draw_outside_mask()

        selected = self.get_selected()
        if selected and self._should_draw_shape(selected):
            self._draw_selection_handles(selected)

        self._draw_paint_canvas_border()

        if self._triangle_vertices:
            self._show_triangle_build_preview()


class DrawingApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Drawing Tool")
        self.root.geometry("1100x650")
        self.root.minsize(540, 360)

        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self._picker_button_active = False
        self._alt_held = False
        self._on_layer_button_armed = False
        self._ctrl_held = False
        self._show_canvas_only_active = False
        self._color_vis_mode: ColorVisMode = "normal"
        self._dark_mode = True
        self.theme = LIGHT_THEME
        self._rect_tool_btn: Optional[tk.Button] = None
        self._line_tool_btn: Optional[tk.Button] = None
        self._triangle_tool_btn: Optional[tk.Button] = None

        self.palette = ColorPalette(
            self.root,
            on_color_change=self._on_color_change,
            on_picker_toggle=self._on_picker_toggle,
            on_line_width_change=self._on_line_width_change,
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

        self.brightness_vis_btn = tk.Button(
            self.toolbar,
            text="Brightness Vis",
            command=self._toggle_brightness_vis,
            font=("Segoe UI", 9),
        )
        self.brightness_vis_btn.pack(side="left", padx=4)

        self.saturation_vis_btn = tk.Button(
            self.toolbar,
            text="Saturation Vis",
            command=self._toggle_saturation_vis,
            font=("Segoe UI", 9),
        )
        self.saturation_vis_btn.pack(side="left", padx=4)

        self.on_layer_btn = tk.Button(
            self.toolbar,
            text="On Layer (Ctrl)",
            command=self._on_on_layer_arm,
            font=("Segoe UI", 9),
            state="disabled",
        )
        self.on_layer_btn.pack(side="left", padx=4)

        self.file_btn = tk.Menubutton(self.toolbar, text="File", relief=tk.RAISED, font=("Segoe UI", 9))
        self.file_menu = tk.Menu(self.file_btn, tearoff=0)
        self.file_btn.config(menu=self.file_menu)
        self.file_menu.add_command(label="Open...", command=self._on_open)
        self.file_menu.add_command(
            label="Save",
            command=self._on_save,
            accelerator="Ctrl+S",
        )
        self.file_menu.add_command(label="Save As...", command=self._on_save_as)
        self.file_btn.pack(side="left", padx=4)

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

        self.tool_frame = tk.Frame(self.canvas_frame, bd=1, relief=tk.GROOVE)
        self._rect_tool_btn = tk.Button(
            self.tool_frame,
            text="Rectangle",
            command=lambda: self._set_draw_tool("rectangle"),
            font=("Segoe UI", 9),
            relief=tk.SUNKEN,
        )
        self._rect_tool_btn.pack(side="left", padx=2, pady=2)
        self._line_tool_btn = tk.Button(
            self.tool_frame,
            text="Line",
            command=lambda: self._set_draw_tool("line"),
            font=("Segoe UI", 9),
            relief=tk.RAISED,
        )
        self._line_tool_btn.pack(side="left", padx=2, pady=2)
        self._triangle_tool_btn = tk.Button(
            self.tool_frame,
            text="Triangle",
            command=lambda: self._set_draw_tool("triangle"),
            font=("Segoe UI", 9),
            relief=tk.RAISED,
        )
        self._triangle_tool_btn.pack(side="left", padx=2, pady=2)
        self.tool_frame.place(in_=self.canvas, x=6, y=6, anchor="nw")

        self.root.bind_all("<Alt_L>", self._on_alt_press)
        self.root.bind_all("<Alt_R>", self._on_alt_press)
        self.root.bind_all("<KeyRelease-Alt_L>", self._on_alt_release)
        self.root.bind_all("<KeyRelease-Alt_R>", self._on_alt_release)
        self.root.bind_all("<Control_L>", self._on_ctrl_press)
        self.root.bind_all("<Control_R>", self._on_ctrl_press)
        self.root.bind_all("<KeyRelease-Control_L>", self._on_ctrl_release)
        self.root.bind_all("<KeyRelease-Control_R>", self._on_ctrl_release)
        self.root.bind_all("<Control-s>", self._on_ctrl_s)
        self.root.bind_all("<Control-S>", self._on_ctrl_s)
        self.root.bind_all("<Tab>", self._on_tab_press)

        self.layers = LayerPanel(
            self.root,
            on_select=self._on_layer_select,
            on_reorder=self._on_rects_change,
            on_delete=self._on_delete,
        )
        self.layers.grid(row=0, column=2, sticky="ns", padx=(4, 8), pady=8)

        self._syncing_color = False
        self._current_file_path: Optional[str] = None
        self._apply_theme()
        self._seed_demo_shapes()
        self._setup_file_drop()

    def _setup_file_drop(self) -> None:
        if not _HAS_FILE_DROP:
            return

        drop_targets = (self.root, self.canvas_frame, self.canvas, self.palette, self.layers)
        for widget in drop_targets:
            try:
                windnd.hook_dropfiles(widget, func=_enqueue_dropped_files, force_unicode=True)
            except OSError:
                pass

        self._poll_file_drop_queue()

    def _poll_file_drop_queue(self) -> None:
        try:
            while True:
                files = _FILE_DROP_QUEUE.get_nowait()
                self._handle_dropped_files(files)
        except queue.Empty:
            pass
        self.root.after(50, self._poll_file_drop_queue)

    @staticmethod
    def _decode_dropped_path(item: object) -> str:
        if isinstance(item, bytes):
            try:
                return item.decode("utf-8")
            except UnicodeDecodeError:
                return item.decode("gbk")
        return str(item).strip().strip("{}")

    def _is_drawing_path(self, path: str) -> bool:
        suffix = Path(path).suffix.lower()
        return suffix in (FILE_EXTENSION.lower(), ".json")

    def _open_path(self, path: str) -> None:
        try:
            doc = load_document(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror("Open Failed", f"Could not open drawing:\n{exc}", parent=self.root)
            return

        self._apply_loaded_document(doc)
        self._current_file_path = path
        self._update_window_title()

    def _handle_dropped_files(self, files: list) -> None:
        for item in files:
            path = self._decode_dropped_path(item)
            if self._is_drawing_path(path):
                self._open_path(path)
                return

        if files:
            messagebox.showwarning(
                "Unsupported File",
                f"Drop a {FILE_EXTENSION} file to open it.",
                parent=self.root,
            )

    def _seed_demo_shapes(self) -> None:
        demos: list[DrawObject] = [
            Rectangle(1, "rect1", 180, 420, 200, 70, 0, "#3b6fc7", 1),
            Rectangle(2, "rect2", 520, 340, 90, 220, -18, "#e8a87c", 2),
            Rectangle(3, "rect3", 300, 200, 55, 55, 0, "#5cb85c", 3),
            Rectangle(4, "rect4", 420, 130, 160, 45, 0, "#5bc0de", 4),
            Line(5, "line1", 120, 280, 340, 180, "#e88c4a", DEFAULT_LINE_WIDTH, 5),
            Triangle(6, "tri1", 600, 180, 680, 320, 520, 300, "#9b59b6", 6),
        ]
        self.canvas.shapes = demos
        self.canvas._next_id = 7
        self.canvas._next_rect_name = 5
        self.canvas._next_line_name = 2
        self.canvas._next_triangle_name = 2
        self.canvas.select(2)
        self._on_rects_change()

    def _build_document(self) -> dict:
        return build_document(
            shapes=self.canvas.shapes,
            paint_canvas=self.canvas.paint_canvas,
            next_id=self.canvas._next_id,
            next_rect_name=self.canvas._next_rect_name,
            next_line_name=self.canvas._next_line_name,
            next_triangle_name=self.canvas._next_triangle_name,
            next_line_width=self.canvas._next_line_width,
            selected_id=self.canvas.selected_id,
            draw_tool=self.canvas.draw_tool,
        )

    def _apply_loaded_document(self, doc: LoadedDocument) -> None:
        self.canvas.import_document(doc)
        self._set_draw_tool(doc.draw_tool)
        self.width_entry.delete(0, tk.END)
        self.width_entry.insert(0, str(int(self.canvas.paint_canvas.width)))
        self.height_entry.delete(0, tk.END)
        self.height_entry.insert(0, str(int(self.canvas.paint_canvas.height)))
        self._on_selection_change(self.canvas.selected_id)
        self._on_rects_change()

    def _update_window_title(self) -> None:
        if self._current_file_path:
            name = Path(self._current_file_path).name
            self.root.title(f"Drawing Tool — {name}")
        else:
            self.root.title("Drawing Tool")

    def _write_document(self, path: str) -> bool:
        try:
            save_document(path, self._build_document())
        except OSError as exc:
            messagebox.showerror("Save Failed", f"Could not save drawing:\n{exc}", parent=self.root)
            return False

        self._current_file_path = path
        self._update_window_title()
        return True

    def _on_save(self) -> None:
        if not self._current_file_path:
            self._on_save_as()
            return
        self._write_document(self._current_file_path)

    def _on_save_as(self) -> None:
        initial_dir = None
        initial_file = None
        if self._current_file_path:
            current = Path(self._current_file_path)
            initial_dir = str(current.parent)
            initial_file = current.name

        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save Drawing As",
            defaultextension=FILE_EXTENSION,
            filetypes=file_dialog_types(),
            initialdir=initial_dir,
            initialfile=initial_file,
        )
        if path:
            self._write_document(path)

    def _on_ctrl_s(self, event: tk.Event) -> Optional[str]:
        if isinstance(event.widget, tk.Entry):
            return None
        if self._current_file_path:
            self._on_save()
        else:
            self._on_save_as()
        return "break"

    def _on_open(self) -> None:
        initial_dir = None
        if self._current_file_path:
            initial_dir = str(Path(self._current_file_path).parent)

        path = filedialog.askopenfilename(
            parent=self.root,
            title="Open Drawing",
            filetypes=file_dialog_types(),
            initialdir=initial_dir,
        )
        if not path:
            return
        self._open_path(path)

    def _set_draw_tool(self, tool: DrawTool) -> None:
        self.canvas.set_draw_tool(tool)
        if self._rect_tool_btn and self._line_tool_btn and self._triangle_tool_btn:
            self._rect_tool_btn.config(relief=tk.SUNKEN if tool == "rectangle" else tk.RAISED)
            self._line_tool_btn.config(relief=tk.SUNKEN if tool == "line" else tk.RAISED)
            self._triangle_tool_btn.config(relief=tk.SUNKEN if tool == "triangle" else tk.RAISED)

    def _on_selection_change(self, shape_id: Optional[int]) -> None:
        shape = self.canvas.get_selected()
        self.layers.set_shapes(self.canvas.shapes, shape_id)
        self.layers.delete_btn.config(state="normal" if shape_id is not None else "disabled")
        if shape_id is None:
            self._on_layer_button_armed = False
        self._update_on_layer_mode()
        is_line = isinstance(shape, Line)
        self.palette.set_line_width_controls_visible(is_line)
        if is_line:
            self.palette.set_line_width_value(shape.stroke_width)
        if shape and not self._syncing_color:
            self._syncing_color = True
            self.palette.set_color(shape.color)
            self._syncing_color = False

    def _on_line_width_change(self, width: float) -> None:
        self.canvas.set_line_width(width)
        self.layers.set_shapes(self.canvas.shapes, self.canvas.selected_id)

    def _on_color_change(self, hex_color: str) -> None:
        if self._syncing_color:
            return
        self.canvas.set_color(hex_color)
        self.layers.set_shapes(self.canvas.shapes, self.canvas.selected_id)

    def _on_layer_select(self, shape_id: int) -> None:
        self.canvas.select(shape_id)
        self._on_selection_change(shape_id)

    def _on_rects_change(self) -> None:
        self.layers.set_shapes(self.canvas.shapes, self.canvas.selected_id)

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
        self.layers.set_shapes(self.canvas.shapes, self.canvas.selected_id)

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

    def _set_color_vis_mode(self, mode: ColorVisMode) -> None:
        self._color_vis_mode = mode
        self.canvas.set_color_vis_mode(mode)
        self.brightness_vis_btn.config(relief=tk.SUNKEN if mode == "brightness" else tk.RAISED)
        self.saturation_vis_btn.config(relief=tk.SUNKEN if mode == "saturation" else tk.RAISED)

    def _toggle_brightness_vis(self) -> None:
        if self._color_vis_mode == "brightness":
            self._set_color_vis_mode("normal")
        else:
            self._set_color_vis_mode("brightness")

    def _toggle_saturation_vis(self) -> None:
        if self._color_vis_mode == "saturation":
            self._set_color_vis_mode("normal")
        else:
            self._set_color_vis_mode("saturation")

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
        self.tool_frame.config(bg=self.theme.app_bg)
        for label in (self.width_label, self.height_label):
            label.config(bg=self.theme.app_bg, fg=self.theme.text)
        for entry in (self.width_entry, self.height_entry):
            _style_entry(entry, self.theme)
        for btn in (
            self.show_canvas_btn,
            self.brightness_vis_btn,
            self.saturation_vis_btn,
            self.on_layer_btn,
            self.dark_mode_btn,
        ):
            _style_button(btn, self.theme)
        _style_menubutton(self.file_btn, self.theme)
        _style_menu(self.file_menu, self.theme)
        if self._rect_tool_btn and self._line_tool_btn and self._triangle_tool_btn:
            for btn in (self._rect_tool_btn, self._line_tool_btn, self._triangle_tool_btn):
                _style_button(btn, self.theme)
        self.tool_frame.config(bg=self.theme.panel_bg)
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
