"""LAB color picker widget (a-b plane, a/b/l sliders, RGB gamut boundary)."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from PIL import Image, ImageTk

from lab_color import (
    A_MAX,
    A_MIN,
    B_MAX,
    B_MIN,
    L_MAX,
    L_MIN,
    PLANE_SIZE,
    LabColorLUT,
    _ab_to_plane_xy,
    _clamp,
    _plane_xy_to_ab,
    lab_to_rgb,
    peek_lab_lut,
    rgb_to_lab,
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
LAB_LABEL_W = 18
BAR_ROW_W = PLANE_SIZE + PLANE_GAP + B_COLUMN_W


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


class LabColorPicker(tk.Frame):
    """CIELAB picker: a-b plane, a/b/l sliders, gamut boundary overlay."""

    def __init__(
        self,
        master: tk.Misc,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(master, highlightthickness=0)
        self.on_change = on_change
        self._updating = False
        self.l_val = 50.0
        self.a_val = 0.0
        self.b_val = 0.0
        self.r, self.g, self.b = 119, 119, 119
        self.panel_bg = "#f0f0f0"
        self.text_fg = "#000000"
        self._lut: Optional[LabColorLUT] = None
        self._plane_photo: Optional[ImageTk.PhotoImage] = None

        self.grid_columnconfigure(1, weight=0)
        self.grid_columnconfigure(2, weight=0)

        self.plane_canvas = tk.Canvas(
            self,
            width=PLANE_SIZE,
            height=PLANE_SIZE,
            highlightthickness=0,
            bd=0,
            bg=self.panel_bg,
        )
        self.plane_canvas.grid(row=0, column=1, sticky="nw", pady=(20, 2))
        self.plane_canvas.bind("<Button-1>", self._on_plane_press)
        self.plane_canvas.bind("<B1-Motion>", self._on_plane_press)

        self.b_col = tk.Frame(self, bg=self.panel_bg)
        self.b_col.grid(row=0, column=2, sticky="n", padx=(PLANE_GAP, 0), pady=(0, 2))
        self.b_label = tk.Label(
            self.b_col, text="b", font=("Segoe UI", 9), bg=self.panel_bg, fg=self.text_fg
        )
        self.b_label.pack(anchor="n")
        self.b_slider = _LabSlider(
            self.b_col,
            length=PLANE_SIZE,
            thickness=SLIDER_THICKNESS,
            vertical=True,
            on_change=self._on_b_slider,
            invert=True,
        )
        self.b_slider.set_range(B_MIN, B_MAX)
        self.b_slider.pack()

        self.a_label = tk.Label(
            self,
            text="a",
            font=("Segoe UI", 9),
            bg=self.panel_bg,
            fg=self.text_fg,
            width=2,
        )
        self.a_label.grid(row=1, column=0, sticky="e", padx=(0, 2))
        self.a_slider = _LabSlider(
            self,
            length=PLANE_SIZE,
            thickness=SLIDER_THICKNESS,
            vertical=False,
            on_change=self._on_a_slider,
        )
        self.a_slider.set_range(A_MIN, A_MAX)
        self.a_slider.grid(row=1, column=1, columnspan=2, sticky="w", pady=(2, 0))

        self.l_label = tk.Label(
            self,
            text="l",
            font=("Segoe UI", 9),
            bg=self.panel_bg,
            fg=self.text_fg,
            width=2,
        )
        self.l_label.grid(row=2, column=0, sticky="e", padx=(0, 2), pady=(2, 6))
        self.l_slider = _LabSlider(
            self,
            length=BAR_ROW_W,
            thickness=SLIDER_THICKNESS,
            vertical=False,
            on_change=self._on_l_slider,
        )
        self.l_slider.set_range(L_MIN, L_MAX)
        self.l_slider.grid(row=2, column=1, columnspan=2, sticky="w", pady=(2, 6))

        if try_load_lab_lut():
            self._on_lut_ready(peek_lab_lut())  # type: ignore[arg-type]
        else:
            self._show_loading()
        self.after(50, self._begin_lut_build)

    def _begin_lut_build(self) -> None:
        if self._lut is not None:
            return
        start_lab_lut_build()
        self._poll_lut()

    def _poll_lut(self) -> None:
        lut = peek_lab_lut()
        if lut is not None:
            self._on_lut_ready(lut)
            return
        self.after(100, self._poll_lut)

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
            PLANE_SIZE // 2,
            PLANE_SIZE // 2,
            text="Loading…",
            fill="#333333",
            font=("Segoe UI", 10),
        )

    def apply_theme(
        self,
        panel_bg: str,
        text_fg: str,
        outline: str,
        thumb_fill: str,
        thumb_outline: str,
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
        self.l_val, self.a_val, self.b_val = rgb_to_lab(r, g, b)
        self._refresh_all()
        self._updating = False

    def get_rgb(self) -> tuple[int, int, int]:
        return self.r, self.g, self.b

    def _emit(self) -> None:
        if self._updating:
            return
        self.r, self.g, self.b = lab_to_rgb(self.l_val, self.a_val, self.b_val)
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
        a_pixels = self._lut.a_row_pixels(self.l_val, self.b_val)
        b_pixels = self._lut.b_col_pixels(self.l_val, self.a_val)
        l_pixels = [(int(round(i / max(BAR_ROW_W - 1, 1) * 255)),) * 3 for i in range(BAR_ROW_W)]
        self.a_slider.set_pixels(a_pixels)
        self.b_slider.set_pixels(b_pixels)
        self.l_slider.set_pixels(l_pixels)
        self.a_slider.set_value(self.a_val)
        self.b_slider.set_value(self.b_val)
        self.l_slider.set_value(self.l_val)

    def _update_marker(self) -> None:
        self.plane_canvas.delete("marker")
        px, py = _ab_to_plane_xy(self.a_val, self.b_val, PLANE_SIZE)
        self.plane_canvas.create_oval(
            px - 5,
            py - 5,
            px + 5,
            py + 5,
            outline="white",
            width=2,
            tags="marker",
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
