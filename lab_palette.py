"""OKLab plane picker and OKLCH bar / ring pickers (LUT-backed)."""

from __future__ import annotations

import math
import tkinter as tk
from typing import Callable, Optional

from PIL import Image, ImageTk

from lab_color import (
    A_MAX,
    A_MIN,
    B_MAX,
    B_MIN,
    C_MAX,
    C_MIN,
    H_MAX,
    H_MIN,
    L_MAX,
    L_MIN,
    PLANE_SIZE,
    LabColorLUT,
    _ab_to_plane_xy,
    _clamp,
    _plane_xy_to_ab,
    oklab_to_rgb,
    oklch_to_rgb,
    peek_lab_lut,
    rgb_to_oklab,
    rgb_to_oklch,
    start_lab_lut_build,
    try_load_lab_lut,
)


def _resample_colors(
    colors: list[tuple[int, int, int]], length: int
) -> list[tuple[int, int, int]]:
    if len(colors) == length:
        return colors
    if not colors:
        return [(0, 0, 0)] * length
    last = len(colors) - 1
    return [colors[int(round(i / max(length - 1, 1) * last))] for i in range(length)]


def _bar_image_pixels(
    colors: list[tuple[int, int, int]],
    length: int,
    thickness: int,
    vertical: bool,
) -> list[tuple[int, int, int]]:
    row = _resample_colors(colors, length)
    if vertical:
        pixels: list[tuple[int, int, int]] = []
        for color in row:
            pixels.extend([color] * thickness)
        return pixels
    pixels: list[tuple[int, int, int]] = []
    for _ in range(thickness):
        pixels.extend(row)
    return pixels


SLIDER_THICKNESS = 14
SLIDER_THUMB_PAD = 8
B_COLUMN_W = SLIDER_THICKNESS + SLIDER_THUMB_PAD
PLANE_GAP = 4
BAR_ROW_W = PLANE_SIZE + PLANE_GAP + B_COLUMN_W
RING_SIZE = 120
RING_SQUARE = 60


def _style_lab_widgets(root: tk.Misc, panel_bg: str, text_fg: str) -> None:
    if isinstance(root, tk.Label):
        root.config(bg=panel_bg, fg=text_fg)
    elif isinstance(root, (tk.Frame, tk.Canvas)):
        root.config(bg=panel_bg)
    for child in root.winfo_children():
        _style_lab_widgets(child, panel_bg, text_fg)


class _LabSlider(tk.Frame):
    """Horizontal or vertical gradient slider with a triangular thumb."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        length: int,
        thickness: int,
        vertical: bool,
        on_change: Callable[[float], None],
        invert: bool = False,
    ) -> None:
        super().__init__(master, highlightthickness=0)
        self.length = length
        self.thickness = thickness
        self.vertical = vertical
        self.invert = invert
        self.on_change = on_change
        self._value = 0.0
        self._from = 0.0
        self._to = 100.0
        self._updating = False
        self._pixels: list[tuple[int, int, int]] = []
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._image_id: Optional[int] = None
        self._thumb_id: Optional[int] = None
        self._border_id: Optional[int] = None
        self.theme_bg = "#f0f0f0"
        self.theme_outline = "#888888"
        self.theme_thumb_fill = "#333333"
        self.theme_thumb_outline = "#111111"

        pad = SLIDER_THUMB_PAD
        if vertical:
            cw, ch = self.thickness + pad, self.length + pad
        else:
            cw, ch = self.length + pad, self.thickness + pad
        self.canvas = tk.Canvas(self, width=cw, height=ch, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_press)

    def apply_theme(self, panel_bg: str, outline: str, thumb_fill: str, thumb_outline: str) -> None:
        self.theme_bg = panel_bg
        self.theme_outline = outline
        self.theme_thumb_fill = thumb_fill
        self.theme_thumb_outline = thumb_outline
        self.config(bg=panel_bg)
        self.canvas.config(bg=panel_bg)
        if self._border_id is not None:
            self.canvas.itemconfig(self._border_id, outline=outline)
        if self._thumb_id is not None:
            self.canvas.itemconfig(self._thumb_id, fill=thumb_fill, outline=thumb_outline)

    def set_range(self, from_: float, to_: float) -> None:
        self._from = from_
        self._to = to_

    def set_pixels(self, pixels: list[tuple[int, int, int]]) -> None:
        self._pixels = _bar_image_pixels(pixels, self.length, self.thickness, self.vertical)
        if self.vertical:
            img = Image.new("RGB", (self.thickness, self.length))
        else:
            img = Image.new("RGB", (self.length, self.thickness))
        img.putdata(self._pixels)
        self._photo = ImageTk.PhotoImage(img)
        bar_w = self.thickness if self.vertical else self.length
        bar_h = self.length if self.vertical else self.thickness
        if self._image_id is None:
            self._border_id = self.canvas.create_rectangle(
                0, 0, bar_w, bar_h, outline=self.theme_outline, width=1
            )
            self._image_id = self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
            self._thumb_id = self.canvas.create_polygon(0, 0, 0, 0, 0, 0)
            self.canvas.tag_raise(self._thumb_id)
        else:
            self.canvas.coords(self._border_id, 0, 0, bar_w, bar_h)
            self.canvas.itemconfig(self._image_id, image=self._photo)
        self._draw_thumb()

    def set_value(self, value: float) -> None:
        self._updating = True
        self._value = _clamp(value, self._from, self._to)
        self._draw_thumb()
        self._updating = False

    def get_value(self) -> float:
        return self._value

    def _draw_thumb(self) -> None:
        if self._thumb_id is None:
            return
        t = (self._value - self._from) / max(self._to - self._from, 1e-6)
        if self.invert:
            t = 1.0 - t
        if self.vertical:
            y = t * (self.length - 1)
            x = self.thickness + 2
            self.canvas.coords(self._thumb_id, x, y - 5, x, y + 5, x + 6, y)
        else:
            x = t * (self.length - 1)
            y = self.thickness + 2
            self.canvas.coords(self._thumb_id, x - 5, y, x + 5, y, x, y + 6)

    def _on_press(self, event: tk.Event) -> None:
        if self._updating:
            return
        if self.vertical:
            t = _clamp(event.y / max(self.length - 1, 1), 0.0, 1.0)
            if self.invert:
                t = 1.0 - t
        else:
            t = _clamp(event.x / max(self.length - 1, 1), 0.0, 1.0)
        self._value = self._from + t * (self._to - self._from)
        self._draw_thumb()
        self.on_change(self._value)


class _LutClient:
    """Shared LUT load / poll helper for OKLab and OKLCH widgets."""

    def __init__(self, widget: tk.Misc, on_ready: Callable[[LabColorLUT], None]) -> None:
        self._widget = widget
        self._on_ready = on_ready
        self.lut: Optional[LabColorLUT] = None
        if try_load_lab_lut():
            lut = peek_lab_lut()
            if lut is not None:
                self._on_ready(lut)
                self.lut = lut
                return
        widget.after(50, self._begin)

    def _begin(self) -> None:
        if self.lut is not None:
            return
        start_lab_lut_build()
        self._poll()

    def _poll(self) -> None:
        lut = peek_lab_lut()
        if lut is not None:
            self.lut = lut
            self._on_ready(lut)
            return
        self._widget.after(100, self._poll)


class LabColorPicker(tk.Frame):
    """OKLab picker: a-b plane, a/b/l sliders, gamut boundary overlay."""

    def __init__(self, master: tk.Misc, on_change: Callable[[], None]) -> None:
        super().__init__(master, highlightthickness=0)
        self.on_change = on_change
        self._updating = False
        self.l_val = 0.7
        self.a_val = 0.0
        self.b_val = 0.0
        self.r, self.g, self.b = 179, 179, 179
        self.panel_bg = "#f0f0f0"
        self.text_fg = "#000000"
        self._lut: Optional[LabColorLUT] = None
        self._plane_photo: Optional[ImageTk.PhotoImage] = None

        self.plane_canvas = tk.Canvas(
            self, width=PLANE_SIZE, height=PLANE_SIZE, highlightthickness=0, bd=0, bg=self.panel_bg
        )
        self.plane_canvas.grid(row=0, column=1, sticky="nw", pady=(20, 2))
        self.plane_canvas.bind("<Button-1>", self._on_plane_press)
        self.plane_canvas.bind("<B1-Motion>", self._on_plane_press)

        self.b_col = tk.Frame(self, bg=self.panel_bg)
        self.b_col.grid(row=0, column=2, sticky="n", padx=(PLANE_GAP, 0), pady=(0, 2))
        self.b_label = tk.Label(self.b_col, text="b", font=("Segoe UI", 9), bg=self.panel_bg, fg=self.text_fg)
        self.b_label.pack(anchor="n")
        self.b_slider = _LabSlider(
            self.b_col, length=PLANE_SIZE, thickness=SLIDER_THICKNESS, vertical=True,
            on_change=self._on_b_slider, invert=True,
        )
        self.b_slider.set_range(B_MIN, B_MAX)
        self.b_slider.pack()

        self.a_label = tk.Label(self, text="a", font=("Segoe UI", 9), bg=self.panel_bg, fg=self.text_fg, width=2)
        self.a_label.grid(row=1, column=0, sticky="e", padx=(0, 2))
        self.a_slider = _LabSlider(
            self, length=PLANE_SIZE, thickness=SLIDER_THICKNESS, vertical=False, on_change=self._on_a_slider
        )
        self.a_slider.set_range(A_MIN, A_MAX)
        self.a_slider.grid(row=1, column=1, columnspan=2, sticky="w", pady=(2, 0))

        self.l_label = tk.Label(self, text="L", font=("Segoe UI", 9), bg=self.panel_bg, fg=self.text_fg, width=2)
        self.l_label.grid(row=2, column=0, sticky="e", padx=(0, 2), pady=(2, 6))
        self.l_slider = _LabSlider(
            self, length=BAR_ROW_W, thickness=SLIDER_THICKNESS, vertical=False, on_change=self._on_l_slider
        )
        self.l_slider.set_range(L_MIN, L_MAX)
        self.l_slider.grid(row=2, column=1, columnspan=2, sticky="w", pady=(2, 6))

        self._show_loading()
        _LutClient(self, self._on_lut_ready)

    def _on_lut_ready(self, lut: LabColorLUT) -> None:
        self._lut = lut
        self._refresh_all()

    def _show_loading(self) -> None:
        gray = [(180, 180, 180)] * (PLANE_SIZE * PLANE_SIZE)
        img = Image.new("RGB", (PLANE_SIZE, PLANE_SIZE))
        img.putdata(gray)
        self._plane_photo = ImageTk.PhotoImage(img)
        self.plane_canvas.delete("all")
        self.plane_canvas.create_image(0, 0, anchor="nw", image=self._plane_photo)
        self.plane_canvas.create_text(
            PLANE_SIZE // 2, PLANE_SIZE // 2, text="Loading…", fill="#333333", font=("Segoe UI", 10)
        )

    def apply_theme(
        self, panel_bg: str, text_fg: str, outline: str, thumb_fill: str, thumb_outline: str
    ) -> None:
        self.panel_bg = panel_bg
        self.text_fg = text_fg
        _style_lab_widgets(self, panel_bg, text_fg)
        theme_args = (panel_bg, outline, thumb_fill, thumb_outline)
        self.a_slider.apply_theme(*theme_args)
        self.b_slider.apply_theme(*theme_args)
        self.l_slider.apply_theme(*theme_args)
        self._refresh_plane()

    def set_from_rgb(self, r: int, g: int, b: int) -> None:
        self._updating = True
        self.r, self.g, self.b = r, g, b
        self.l_val, self.a_val, self.b_val = rgb_to_oklab(r, g, b)
        self._refresh_all()
        self._updating = False

    def get_rgb(self) -> tuple[int, int, int]:
        return self.r, self.g, self.b

    def _emit(self) -> None:
        if self._updating:
            return
        self.r, self.g, self.b = oklab_to_rgb(self.l_val, self.a_val, self.b_val)
        self.on_change()

    def _refresh_all(self) -> None:
        self._refresh_plane()
        self._refresh_sliders()
        self._update_marker()

    def _refresh_plane(self) -> None:
        if self._lut is None:
            return
        pixels = self._lut.plane_pixels(self.l_val)
        img = Image.new("RGB", (PLANE_SIZE, PLANE_SIZE))
        img.putdata(pixels)
        self._plane_photo = ImageTk.PhotoImage(img)
        self.plane_canvas.delete("all")
        self.plane_canvas.create_image(0, 0, anchor="nw", image=self._plane_photo)
        boundary = self._lut.boundary(self.l_val)
        if boundary:
            flat = [coord for pt in boundary for coord in pt]
            self.plane_canvas.create_polygon(*flat, outline="white", fill="", width=1)
        self._update_marker()

    def _refresh_sliders(self) -> None:
        if self._lut is None:
            return
        self.a_slider.set_pixels(self._lut.a_row_pixels(self.l_val, self.b_val))
        self.b_slider.set_pixels(self._lut.b_col_pixels(self.l_val, self.a_val))
        l_pixels = [(int(round(i / max(BAR_ROW_W - 1, 1) * 255)),) * 3 for i in range(BAR_ROW_W)]
        self.l_slider.set_pixels(l_pixels)
        self.a_slider.set_value(self.a_val)
        self.b_slider.set_value(self.b_val)
        self.l_slider.set_value(self.l_val)

    def _update_marker(self) -> None:
        self.plane_canvas.delete("marker")
        px, py = _ab_to_plane_xy(self.a_val, self.b_val, PLANE_SIZE)
        self.plane_canvas.create_oval(
            px - 5, py - 5, px + 5, py + 5, outline="white", width=2, tags="marker"
        )

    def _set_ab(self, a_val: float, b_val: float) -> None:
        self.a_val = _clamp(a_val, A_MIN, A_MAX)
        self.b_val = _clamp(b_val, B_MIN, B_MAX)
        self.a_slider.set_value(self.a_val)
        self.b_slider.set_value(self.b_val)
        self._lut_refresh_cross_sliders()
        self._update_marker()
        self._emit()

    def _lut_refresh_cross_sliders(self) -> None:
        if self._lut is None:
            return
        self.a_slider.set_pixels(self._lut.a_row_pixels(self.l_val, self.b_val))
        self.b_slider.set_pixels(self._lut.b_col_pixels(self.l_val, self.a_val))

    def _on_plane_press(self, event: tk.Event) -> None:
        a_val, b_val = _plane_xy_to_ab(float(event.x), float(event.y), PLANE_SIZE)
        self._set_ab(a_val, b_val)

    def _on_a_slider(self, value: float) -> None:
        self.a_val = value
        if self._lut is not None:
            self.b_slider.set_pixels(self._lut.b_col_pixels(self.l_val, self.a_val))
        self._update_marker()
        self._emit()

    def _on_b_slider(self, value: float) -> None:
        self.b_val = value
        if self._lut is not None:
            self.a_slider.set_pixels(self._lut.a_row_pixels(self.l_val, self.b_val))
        self._update_marker()
        self._emit()

    def _on_l_slider(self, value: float) -> None:
        self.l_val = value
        self._refresh_plane()
        self._lut_refresh_cross_sliders()
        self._emit()


class OklchBarPicker(tk.Frame):
    """OKLCH bar mode: H / C / L gradient sliders (HSV-style bars)."""

    def __init__(self, master: tk.Misc, on_change: Callable[[], None]) -> None:
        super().__init__(master, highlightthickness=0)
        self.on_change = on_change
        self._updating = False
        self.l_val = 0.7
        self.c_val = 0.12
        self.h_val = 40.0
        self.r, self.g, self.b = 200, 150, 100
        self.panel_bg = "#f0f0f0"
        self.text_fg = "#000000"
        self._lut: Optional[LabColorLUT] = None

        self.sliders: dict[str, _LabSlider] = {}
        for key, label, from_, to_ in (
            ("h", "H", H_MIN, H_MAX),
            ("c", "C", C_MIN, C_MAX),
            ("l", "L", L_MIN, L_MAX),
        ):
            row = tk.Frame(self, bg=self.panel_bg)
            row.pack(fill="x", padx=6, pady=2)
            lbl = tk.Label(row, text=label, width=2, font=("Segoe UI", 9), bg=self.panel_bg, fg=self.text_fg)
            lbl.pack(side="left")
            setattr(self, f"_{key}_label", lbl)
            slider = _LabSlider(
                row, length=160, thickness=SLIDER_THICKNESS, vertical=False,
                on_change=lambda v, k=key: self._on_slider(k, v),
            )
            slider.set_range(from_, to_)
            slider.pack(side="left", padx=4)
            self.sliders[key] = slider

        _LutClient(self, self._on_lut_ready)

    def _on_lut_ready(self, lut: LabColorLUT) -> None:
        self._lut = lut
        self._refresh_gradients()
        self._sync_values()

    def apply_theme(
        self, panel_bg: str, text_fg: str, outline: str, thumb_fill: str, thumb_outline: str
    ) -> None:
        self.panel_bg = panel_bg
        self.text_fg = text_fg
        _style_lab_widgets(self, panel_bg, text_fg)
        for slider in self.sliders.values():
            slider.apply_theme(panel_bg, outline, thumb_fill, thumb_outline)
        self._refresh_gradients()

    def set_from_rgb(self, r: int, g: int, b: int) -> None:
        self._updating = True
        self.r, self.g, self.b = r, g, b
        self.l_val, self.c_val, self.h_val = rgb_to_oklch(r, g, b)
        self._sync_values()
        self._refresh_gradients()
        self._updating = False

    def get_rgb(self) -> tuple[int, int, int]:
        return self.r, self.g, self.b

    def _sync_values(self) -> None:
        self.sliders["l"].set_value(self.l_val)
        self.sliders["c"].set_value(self.c_val)
        self.sliders["h"].set_value(self.h_val)

    def _refresh_gradients(self) -> None:
        if self._lut is None:
            return
        l_colors = self._lut.l_row_at_chroma(self.h_val, self.c_val)
        c_colors = self._lut.c_row_at_lightness(self.h_val, self.l_val)
        h_colors = self._lut.hue_ring_colors(self.l_val, max(self.c_val, 0.08), 160)
        self.sliders["l"].set_pixels(l_colors)
        self.sliders["c"].set_pixels(c_colors)
        self.sliders["h"].set_pixels(h_colors)

    def _on_slider(self, key: str, value: float) -> None:
        if key == "l":
            self.l_val = value
        elif key == "c":
            self.c_val = value
        else:
            self.h_val = value % 360.0
        self._refresh_gradients()
        if self._updating:
            return
        self.r, self.g, self.b = oklch_to_rgb(self.l_val, self.c_val, self.h_val)
        self.on_change()


class OklchRingPicker(tk.Frame):
    """OKLCH ring mode: hue ring + L/C square (like HSV ring + SV square)."""

    def __init__(self, master: tk.Misc, on_change: Callable[[], None]) -> None:
        super().__init__(master, highlightthickness=0)
        self.on_change = on_change
        self._updating = False
        self.l_val = 0.7
        self.c_val = 0.12
        self.h_val = 40.0
        self.r, self.g, self.b = 200, 150, 100
        self.panel_bg = "#f0f0f0"
        self.text_fg = "#000000"
        self._lut: Optional[LabColorLUT] = None
        self._wheel_photo: Optional[ImageTk.PhotoImage] = None
        self._square_photo: Optional[ImageTk.PhotoImage] = None
        self._cached_hue: Optional[float] = None

        self.picker_frame = tk.Frame(self)
        self.picker_frame.pack(pady=(4, 4))
        self.wheel_canvas = tk.Canvas(
            self.picker_frame, width=RING_SIZE, height=RING_SIZE, highlightthickness=0
        )
        self.wheel_canvas.pack()
        self.wheel_canvas.bind("<Button-1>", self._on_wheel_click)
        self.wheel_canvas.bind("<B1-Motion>", self._on_wheel_click)

        inset = (RING_SIZE - RING_SQUARE) // 2
        self.square_canvas = tk.Canvas(
            self.picker_frame, width=RING_SQUARE, height=RING_SQUARE, highlightthickness=0
        )
        self.square_canvas.place(x=inset + 1, y=inset + 1, width=RING_SQUARE, height=RING_SQUARE)
        self.square_canvas.bind("<Button-1>", self._on_square_click)
        self.square_canvas.bind("<B1-Motion>", self._on_square_click)

        _LutClient(self, self._on_lut_ready)

    def _on_lut_ready(self, lut: LabColorLUT) -> None:
        self._lut = lut
        self._cached_hue = None
        self._refresh_wheel()
        self._refresh_square()
        self._update_markers()

    def apply_theme(
        self, panel_bg: str, text_fg: str, outline: str, thumb_fill: str, thumb_outline: str
    ) -> None:
        self.panel_bg = panel_bg
        self.text_fg = text_fg
        _style_lab_widgets(self, panel_bg, text_fg)
        self._cached_hue = None
        self._refresh_wheel()
        self._refresh_square()
        self._update_markers()

    def set_from_rgb(self, r: int, g: int, b: int) -> None:
        self._updating = True
        self.r, self.g, self.b = r, g, b
        self.l_val, self.c_val, self.h_val = rgb_to_oklch(r, g, b)
        self._cached_hue = None
        self._refresh_wheel()
        self._refresh_square()
        self._update_markers()
        self._updating = False

    def get_rgb(self) -> tuple[int, int, int]:
        return self.r, self.g, self.b

    def _emit(self) -> None:
        if self._updating:
            return
        self.r, self.g, self.b = oklch_to_rgb(self.l_val, self.c_val, self.h_val)
        self.on_change()

    def _refresh_wheel(self) -> None:
        size = RING_SIZE
        cx, cy = size / 2, size / 2
        r_outer = size / 2 - 2
        r_inner = RING_SQUARE / 2 + 4
        hole = tuple(int(self.panel_bg.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
        pixels: list[tuple[int, int, int]] = []
        chroma = max(self.c_val, 0.1)
        for y in range(size):
            dy = y - cy
            for x in range(size):
                dx = x - cx
                dist = math.hypot(dx, dy)
                if r_inner <= dist <= r_outer:
                    angle = (math.degrees(math.atan2(dy, dx)) + 90) % 360
                    pixels.append(oklch_to_rgb(self.l_val, chroma, angle))
                else:
                    pixels.append(hole)
        img = Image.new("RGB", (size, size))
        img.putdata(pixels)
        self._wheel_photo = ImageTk.PhotoImage(img)
        self.wheel_canvas.delete("all")
        self.wheel_canvas.create_image(0, 0, anchor="nw", image=self._wheel_photo)

    def _refresh_square(self) -> None:
        if self._lut is None:
            return
        if self._cached_hue == self.h_val and self._square_photo is not None:
            return
        self._cached_hue = self.h_val
        full = self._lut.lc_plane_pixels(self.h_val)
        # Downsample PLANE_SIZE -> RING_SQUARE
        pixels: list[tuple[int, int, int]] = []
        for y in range(RING_SQUARE):
            src_y = int(round(y / max(RING_SQUARE - 1, 1) * (PLANE_SIZE - 1)))
            for x in range(RING_SQUARE):
                src_x = int(round(x / max(RING_SQUARE - 1, 1) * (PLANE_SIZE - 1)))
                pixels.append(full[src_y * PLANE_SIZE + src_x])
        img = Image.new("RGB", (RING_SQUARE, RING_SQUARE))
        img.putdata(pixels)
        self._square_photo = ImageTk.PhotoImage(img)
        self.square_canvas.delete("all")
        self.square_canvas.create_image(0, 0, anchor="nw", image=self._square_photo)
        # Gamut boundary scaled
        boundary = self._lut.lc_boundary(self.h_val)
        if boundary:
            scale = (RING_SQUARE - 1) / max(PLANE_SIZE - 1, 1)
            flat = [c * scale for pt in boundary for c in pt]
            self.square_canvas.create_polygon(*flat, outline="white", fill="", width=1)

    def _update_markers(self) -> None:
        self.wheel_canvas.delete("marker")
        self.square_canvas.delete("marker")
        cx = cy = RING_SIZE / 2
        r_mid = (RING_SIZE / 2 - 2 + RING_SQUARE / 2 + 4) / 2
        angle = math.radians(self.h_val - 90)
        wx = cx + r_mid * math.cos(angle)
        wy = cy + r_mid * math.sin(angle)
        self.wheel_canvas.create_oval(
            wx - 4, wy - 4, wx + 4, wy + 4, outline="white", width=2, tags="marker"
        )
        sx = self.c_val / C_MAX * (RING_SQUARE - 1)
        sy = (1.0 - self.l_val) * (RING_SQUARE - 1)
        self.square_canvas.create_oval(
            sx - 4, sy - 4, sx + 4, sy + 4, outline="white", width=2, tags="marker"
        )

    def _on_wheel_click(self, event: tk.Event) -> None:
        cx = cy = RING_SIZE / 2
        dx, dy = event.x - cx, event.y - cy
        dist = math.hypot(dx, dy)
        r_inner = RING_SQUARE / 2 + 4
        r_outer = RING_SIZE / 2 - 2
        if dist < r_inner or dist > r_outer:
            return
        self.h_val = (math.degrees(math.atan2(dy, dx)) + 90) % 360
        self._cached_hue = None
        self._refresh_wheel()
        self._refresh_square()
        self._update_markers()
        self._emit()

    def _on_square_click(self, event: tk.Event) -> None:
        self.c_val = _clamp(event.x / max(RING_SQUARE - 1, 1) * C_MAX, C_MIN, C_MAX)
        self.l_val = _clamp(1.0 - event.y / max(RING_SQUARE - 1, 1), L_MIN, L_MAX)
        self._refresh_wheel()
        self._update_markers()
        self._emit()
