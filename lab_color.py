"""CIELAB color space conversions and precomputed LUTs for the LAB picker."""

from __future__ import annotations

import gzip
import math
import pickle
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# D65 reference white (CIE, Y = 100).
_XN = 95.047
_YN = 100.0
_ZN = 108.883

# sRGB <-> XYZ matrices (D65, linear RGB in 0..1).
_SRGB_TO_XYZ = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)
_XYZ_TO_SRGB = (
    (3.2404542, -1.5371385, -0.4985314),
    (-0.9692660, 1.8760108, 0.0415560),
    (0.0556434, -0.2040259, 1.0572252),
)

A_MIN = -128.0
A_MAX = 127.0
B_MIN = -128.0
B_MAX = 127.0
L_MIN = 0.0
L_MAX = 100.0
PLANE_SIZE = 128
L_LEVELS = 101
GAMUT_STEPS = 120
GAMUT_SEARCH_STEPS = 18
_LUT_CACHE_PATH = Path(__file__).with_name(".lab_lut_cache.gz")
_LUT_CACHE_VERSION = 1


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _srgb_to_linear(channel: float) -> float:
    c = channel / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(channel: float) -> float:
    if channel <= 0.0031308:
        return 12.92 * channel
    return 1.055 * (channel ** (1.0 / 2.4)) - 0.055


def _lab_f(t: float) -> float:
    delta = 6.0 / 29.0
    if t > delta**3:
        return t ** (1.0 / 3.0)
    return t / (3.0 * delta * delta) + 4.0 / 29.0


def _lab_f_inv(t: float) -> float:
    delta = 6.0 / 29.0
    if t > delta:
        return t**3
    return 3.0 * delta * delta * (t - 4.0 / 29.0)


def _xyz_to_lab(x: float, y: float, z: float) -> tuple[float, float, float]:
    xr, yr, zr = x / _XN, y / _YN, z / _ZN
    fx, fy, fz = _lab_f(xr), _lab_f(yr), _lab_f(zr)
    l_val = 116.0 * fy - 16.0
    a_val = 500.0 * (fx - fy)
    b_val = 200.0 * (fy - fz)
    return l_val, a_val, b_val


def _lab_to_xyz(l_val: float, a_val: float, b_val: float) -> tuple[float, float, float]:
    fy = (l_val + 16.0) / 116.0
    fx = fy + a_val / 500.0
    fz = fy - b_val / 200.0
    xr = _lab_f_inv(fx)
    yr = _lab_f_inv(fy)
    zr = _lab_f_inv(fz)
    return xr * _XN, yr * _YN, zr * _ZN


def _xyz_to_rgb_linear(x: float, y: float, z: float) -> tuple[float, float, float]:
    r = _XYZ_TO_SRGB[0][0] * x + _XYZ_TO_SRGB[0][1] * y + _XYZ_TO_SRGB[0][2] * z
    g = _XYZ_TO_SRGB[1][0] * x + _XYZ_TO_SRGB[1][1] * y + _XYZ_TO_SRGB[1][2] * z
    b = _XYZ_TO_SRGB[2][0] * x + _XYZ_TO_SRGB[2][1] * y + _XYZ_TO_SRGB[2][2] * z
    return r, g, b


def _rgb_linear_to_xyz(r: float, g: float, b: float) -> tuple[float, float, float]:
    x = _SRGB_TO_XYZ[0][0] * r + _SRGB_TO_XYZ[0][1] * g + _SRGB_TO_XYZ[0][2] * b
    y = _SRGB_TO_XYZ[1][0] * r + _SRGB_TO_XYZ[1][1] * g + _SRGB_TO_XYZ[1][2] * b
    z = _SRGB_TO_XYZ[2][0] * r + _SRGB_TO_XYZ[2][1] * g + _SRGB_TO_XYZ[2][2] * b
    return x * 100.0, y * 100.0, z * 100.0


def lab_to_rgb_raw(l_val: float, a_val: float, b_val: float) -> tuple[float, float, float]:
    x, y, z = _lab_to_xyz(l_val, a_val, b_val)
    r, g, b = _xyz_to_rgb_linear(x / 100.0, y / 100.0, z / 100.0)
    return _linear_to_srgb(r) * 255.0, _linear_to_srgb(g) * 255.0, _linear_to_srgb(b) * 255.0


def lab_to_rgb(l_val: float, a_val: float, b_val: float) -> tuple[int, int, int]:
    r, g, b = lab_to_rgb_raw(l_val, a_val, b_val)
    return (
        int(round(_clamp(r, 0.0, 255.0))),
        int(round(_clamp(g, 0.0, 255.0))),
        int(round(_clamp(b, 0.0, 255.0))),
    )


def rgb_to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    lr = _srgb_to_linear(r)
    lg = _srgb_to_linear(g)
    lb = _srgb_to_linear(b)
    x, y, z = _rgb_linear_to_xyz(lr, lg, lb)
    return _xyz_to_lab(x, y, z)


def _is_in_gamut(l_val: float, a_val: float, b_val: float) -> bool:
    r, g, b = lab_to_rgb_raw(l_val, a_val, b_val)
    return 0.0 <= r <= 255.0 and 0.0 <= g <= 255.0 and 0.0 <= b <= 255.0


def _ab_to_plane_xy(a_val: float, b_val: float, size: int) -> tuple[float, float]:
    px = (a_val - A_MIN) / (A_MAX - A_MIN) * (size - 1)
    py = (B_MAX - b_val) / (B_MAX - B_MIN) * (size - 1)
    return px, py


def _plane_xy_to_ab(px: float, py: float, size: int) -> tuple[float, float]:
    a_val = A_MIN + px / max(size - 1, 1) * (A_MAX - A_MIN)
    b_val = B_MAX - py / max(size - 1, 1) * (B_MAX - B_MIN)
    return a_val, b_val


def _build_gamut_boundary(l_val: float, size: int) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    max_chroma = max(A_MAX - A_MIN, B_MAX - B_MIN)
    for step in range(GAMUT_STEPS):
        angle = math.tau * step / GAMUT_STEPS
        lo, hi = 0.0, max_chroma
        for _ in range(GAMUT_SEARCH_STEPS):
            mid = (lo + hi) * 0.5
            a_val = mid * math.cos(angle)
            b_val = mid * math.sin(angle)
            if _is_in_gamut(l_val, a_val, b_val):
                lo = mid
            else:
                hi = mid
        px, py = _ab_to_plane_xy(lo * math.cos(angle), lo * math.sin(angle), size)
        points.append((px, py))
    return points


@dataclass
class LabColorLUT:
    plane_size: int
    planes: list[list[tuple[int, int, int]]]
    boundaries: list[list[tuple[float, float]]]

    @classmethod
    def build(
        cls,
        plane_size: int = PLANE_SIZE,
        l_levels: int = L_LEVELS,
    ) -> LabColorLUT:
        planes: list[list[tuple[int, int, int]]] = []
        boundaries: list[list[tuple[float, float]]] = []

        for l_index in range(l_levels):
            l_val = float(l_index)
            plane: list[tuple[int, int, int]] = []
            for py in range(plane_size):
                for px in range(plane_size):
                    a_val, b_val = _plane_xy_to_ab(float(px), float(py), plane_size)
                    plane.append(lab_to_rgb(l_val, a_val, b_val))
            planes.append(plane)
            boundaries.append(_build_gamut_boundary(l_val, plane_size))

        return cls(
            plane_size=plane_size,
            planes=planes,
            boundaries=boundaries,
        )

    def plane_pixels(self, l_val: float) -> list[tuple[int, int, int]]:
        return self.planes[int(round(_clamp(l_val, L_MIN, L_MAX)))]

    def boundary(self, l_val: float) -> list[tuple[float, float]]:
        return self.boundaries[int(round(_clamp(l_val, L_MIN, L_MAX)))]

    def a_row_pixels(self, l_val: float, b_val: float) -> list[tuple[int, int, int]]:
        l_index = int(round(_clamp(l_val, L_MIN, L_MAX)))
        _, py = _ab_to_plane_xy(0.0, b_val, self.plane_size)
        py = int(round(_clamp(py, 0, self.plane_size - 1)))
        base = l_index * self.plane_size * self.plane_size
        return [self.planes[l_index][py * self.plane_size + px] for px in range(self.plane_size)]

    def b_col_pixels(self, l_val: float, a_val: float) -> list[tuple[int, int, int]]:
        l_index = int(round(_clamp(l_val, L_MIN, L_MAX)))
        px, _ = _ab_to_plane_xy(a_val, 0.0, self.plane_size)
        px = int(round(_clamp(px, 0, self.plane_size - 1)))
        return [self.planes[l_index][py * self.plane_size + px] for py in range(self.plane_size)]


def _cache_payload(lut: LabColorLUT) -> dict:
    return {
        "version": _LUT_CACHE_VERSION,
        "plane_size": PLANE_SIZE,
        "l_levels": L_LEVELS,
        "gamut_steps": GAMUT_STEPS,
        "lut": lut,
    }


def _load_lut_cache() -> Optional[LabColorLUT]:
    if not _LUT_CACHE_PATH.is_file():
        return None
    try:
        with gzip.open(_LUT_CACHE_PATH, "rb") as handle:
            payload = pickle.load(handle)
    except (OSError, EOFError, pickle.UnpicklingError, KeyError):
        return None
    if payload.get("version") != _LUT_CACHE_VERSION:
        return None
    if payload.get("plane_size") != PLANE_SIZE or payload.get("l_levels") != L_LEVELS:
        return None
    lut = payload.get("lut")
    return lut if isinstance(lut, LabColorLUT) else None


def _save_lut_cache(lut: LabColorLUT) -> None:
    try:
        with gzip.open(_LUT_CACHE_PATH, "wb") as handle:
            pickle.dump(_cache_payload(lut), handle, protocol=pickle.HIGHEST_PROTOCOL)
    except OSError:
        pass


_LUT: Optional[LabColorLUT] = None
_LUT_LOCK = threading.Lock()
_LUT_BUILDING = False


def _try_load_lut() -> bool:
    global _LUT
    if _LUT is not None:
        return True
    cached = _load_lut_cache()
    if cached is None:
        return False
    _LUT = cached
    return True


def get_lab_lut() -> LabColorLUT:
    """Return the LUT, building it synchronously if needed."""
    if _try_load_lut():
        return _LUT  # type: ignore[return-value]
    with _LUT_LOCK:
        if _LUT is None:
            _LUT = LabColorLUT.build()
            _save_lut_cache(_LUT)
    return _LUT


def start_lab_lut_build() -> None:
    """Load cached LUT or build it on a background thread."""
    global _LUT, _LUT_BUILDING
    if _try_load_lut() or _LUT_BUILDING:
        return

    with _LUT_LOCK:
        if _LUT is not None or _LUT_BUILDING:
            return
        _LUT_BUILDING = True

    def _worker() -> None:
        global _LUT, _LUT_BUILDING
        lut = LabColorLUT.build()
        _save_lut_cache(lut)
        with _LUT_LOCK:
            _LUT = lut
            _LUT_BUILDING = False

    threading.Thread(target=_worker, daemon=True).start()


def lab_lut_ready() -> bool:
    return _LUT is not None


def try_load_lab_lut() -> bool:
    return _try_load_lut()


def peek_lab_lut() -> Optional[LabColorLUT]:
    return _LUT
