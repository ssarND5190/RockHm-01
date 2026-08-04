"""OKLab / OKLCH conversions and precomputed LUTs for the color pickers."""

from __future__ import annotations

import gzip
import math
import pickle
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# OKLab a/b display ranges (cover typical sRGB gamut).
A_MIN = -0.4
A_MAX = 0.4
B_MIN = -0.4
B_MAX = 0.4
L_MIN = 0.0
L_MAX = 1.0
C_MIN = 0.0
C_MAX = 0.4
H_MIN = 0.0
H_MAX = 360.0

PLANE_SIZE = 128
L_LEVELS = 101
HUE_LEVELS = 72
GAMUT_STEPS = 120
GAMUT_SEARCH_STEPS = 18

_LUT_CACHE_PATH = Path(__file__).with_name(".oklab_lut_cache.gz")
_LUT_CACHE_VERSION = 1

# Linear sRGB -> LMS (OKLab M1).
_M1 = (
    (0.4122214708, 0.5363325363, 0.0514459929),
    (0.2119034982, 0.6806995451, 0.1073969566),
    (0.0883024619, 0.2817188376, 0.6299787005),
)
# LMS' -> OKLab (OKLab M2).
_M2 = (
    (0.2104542553, 0.7936177850, -0.0040720468),
    (1.9779984951, -2.4285922050, 0.4505937099),
    (0.0259040371, 0.7827717662, -0.8086757660),
)
# OKLab -> LMS' (M2 inverse).
_M2_INV = (
    (1.0, 0.3963377774, 0.2158037573),
    (1.0, -0.1055613458, -0.0638541728),
    (1.0, -0.0894841775, -1.2914855480),
)
# LMS -> linear sRGB (M1 inverse).
_M1_INV = (
    (4.0767416621, -3.3077115913, 0.2309699292),
    (-1.2684380046, 2.6097574011, -0.3413193965),
    (-0.0041960863, -0.7034186147, 1.7076147010),
)


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


def _matmul3(matrix: tuple[tuple[float, float, float], ...], vec: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        matrix[0][0] * vec[0] + matrix[0][1] * vec[1] + matrix[0][2] * vec[2],
        matrix[1][0] * vec[0] + matrix[1][1] * vec[1] + matrix[1][2] * vec[2],
        matrix[2][0] * vec[0] + matrix[2][1] * vec[1] + matrix[2][2] * vec[2],
    )


def _cbrt(x: float) -> float:
    return math.copysign(abs(x) ** (1.0 / 3.0), x)


def rgb_to_oklab(r: int, g: int, b: int) -> tuple[float, float, float]:
    linear = (_srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b))
    lms = _matmul3(_M1, linear)
    lms_p = (_cbrt(lms[0]), _cbrt(lms[1]), _cbrt(lms[2]))
    return _matmul3(_M2, lms_p)


def oklab_to_rgb_raw(l_val: float, a_val: float, b_val: float) -> tuple[float, float, float]:
    lms_p = _matmul3(_M2_INV, (l_val, a_val, b_val))
    lms = (lms_p[0] ** 3, lms_p[1] ** 3, lms_p[2] ** 3)
    linear = _matmul3(_M1_INV, lms)
    return (
        _linear_to_srgb(linear[0]) * 255.0,
        _linear_to_srgb(linear[1]) * 255.0,
        _linear_to_srgb(linear[2]) * 255.0,
    )


def oklab_to_rgb(l_val: float, a_val: float, b_val: float) -> tuple[int, int, int]:
    r, g, b = oklab_to_rgb_raw(l_val, a_val, b_val)
    return (
        int(round(_clamp(r, 0.0, 255.0))),
        int(round(_clamp(g, 0.0, 255.0))),
        int(round(_clamp(b, 0.0, 255.0))),
    )


def oklab_to_oklch(l_val: float, a_val: float, b_val: float) -> tuple[float, float, float]:
    chroma = math.hypot(a_val, b_val)
    hue = math.degrees(math.atan2(b_val, a_val)) % 360.0
    return l_val, chroma, hue


def oklch_to_oklab(l_val: float, chroma: float, hue: float) -> tuple[float, float, float]:
    rad = math.radians(hue)
    return l_val, chroma * math.cos(rad), chroma * math.sin(rad)


def oklch_to_rgb(l_val: float, chroma: float, hue: float) -> tuple[int, int, int]:
    return oklab_to_rgb(*oklch_to_oklab(l_val, chroma, hue))


def oklch_to_rgb_raw(l_val: float, chroma: float, hue: float) -> tuple[float, float, float]:
    return oklab_to_rgb_raw(*oklch_to_oklab(l_val, chroma, hue))


def rgb_to_oklch(r: int, g: int, b: int) -> tuple[float, float, float]:
    return oklab_to_oklch(*rgb_to_oklab(r, g, b))


def _is_oklab_in_gamut(l_val: float, a_val: float, b_val: float) -> bool:
    r, g, b = oklab_to_rgb_raw(l_val, a_val, b_val)
    return 0.0 <= r <= 255.0 and 0.0 <= g <= 255.0 and 0.0 <= b <= 255.0


def _ab_to_plane_xy(a_val: float, b_val: float, size: int) -> tuple[float, float]:
    px = (a_val - A_MIN) / (A_MAX - A_MIN) * (size - 1)
    py = (B_MAX - b_val) / (B_MAX - B_MIN) * (size - 1)
    return px, py


def _plane_xy_to_ab(px: float, py: float, size: int) -> tuple[float, float]:
    a_val = A_MIN + px / max(size - 1, 1) * (A_MAX - A_MIN)
    b_val = B_MAX - py / max(size - 1, 1) * (B_MAX - B_MIN)
    return a_val, b_val


def _lc_to_plane_xy(chroma: float, l_val: float, size: int) -> tuple[float, float]:
    px = chroma / C_MAX * (size - 1)
    py = (1.0 - l_val) * (size - 1)
    return px, py


def _plane_xy_to_lc(px: float, py: float, size: int) -> tuple[float, float]:
    chroma = px / max(size - 1, 1) * C_MAX
    l_val = 1.0 - py / max(size - 1, 1)
    return chroma, l_val


def _build_ab_boundary(l_val: float, size: int) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    max_chroma = max(A_MAX - A_MIN, B_MAX - B_MIN)
    for step in range(GAMUT_STEPS):
        angle = math.tau * step / GAMUT_STEPS
        lo, hi = 0.0, max_chroma
        for _ in range(GAMUT_SEARCH_STEPS):
            mid = (lo + hi) * 0.5
            a_val = mid * math.cos(angle)
            b_val = mid * math.sin(angle)
            if _is_oklab_in_gamut(l_val, a_val, b_val):
                lo = mid
            else:
                hi = mid
        px, py = _ab_to_plane_xy(lo * math.cos(angle), lo * math.sin(angle), size)
        points.append((px, py))
    return points


def _build_lc_boundary(hue: float, size: int) -> list[tuple[float, float]]:
    """Boundary of in-gamut (C, L) for a fixed hue, as polygon in plane coords."""
    points: list[tuple[float, float]] = []
    # Trace max C for each L from 0..1, then reverse for closed shape feel.
    for i in range(size):
        l_val = i / max(size - 1, 1)
        lo, hi = 0.0, C_MAX
        for _ in range(GAMUT_SEARCH_STEPS):
            mid = (lo + hi) * 0.5
            if _is_oklab_in_gamut(*oklch_to_oklab(l_val, mid, hue)):
                lo = mid
            else:
                hi = mid
        points.append(_lc_to_plane_xy(lo, l_val, size))
    # Close along C=0 edge.
    points.append(_lc_to_plane_xy(0.0, 1.0, size))
    points.append(_lc_to_plane_xy(0.0, 0.0, size))
    return points


@dataclass
class LabColorLUT:
    """Shared LUT: OKLab a-b planes by L, and OKLCH L-C planes by hue."""

    plane_size: int
    planes: list[list[tuple[int, int, int]]]
    boundaries: list[list[tuple[float, float]]]
    hue_levels: int
    lc_planes: list[list[tuple[int, int, int]]]
    lc_boundaries: list[list[tuple[float, float]]]

    @classmethod
    def build(
        cls,
        plane_size: int = PLANE_SIZE,
        l_levels: int = L_LEVELS,
        hue_levels: int = HUE_LEVELS,
    ) -> LabColorLUT:
        planes: list[list[tuple[int, int, int]]] = []
        boundaries: list[list[tuple[float, float]]] = []
        for l_index in range(l_levels):
            l_val = l_index / max(l_levels - 1, 1)
            plane: list[tuple[int, int, int]] = []
            for py in range(plane_size):
                for px in range(plane_size):
                    a_val, b_val = _plane_xy_to_ab(float(px), float(py), plane_size)
                    plane.append(oklab_to_rgb(l_val, a_val, b_val))
            planes.append(plane)
            boundaries.append(_build_ab_boundary(l_val, plane_size))

        lc_planes: list[list[tuple[int, int, int]]] = []
        lc_boundaries: list[list[tuple[float, float]]] = []
        for h_index in range(hue_levels):
            hue = h_index / max(hue_levels, 1) * 360.0
            plane = []
            for py in range(plane_size):
                for px in range(plane_size):
                    chroma, l_val = _plane_xy_to_lc(float(px), float(py), plane_size)
                    plane.append(oklch_to_rgb(l_val, chroma, hue))
            lc_planes.append(plane)
            lc_boundaries.append(_build_lc_boundary(hue, plane_size))

        return cls(
            plane_size=plane_size,
            planes=planes,
            boundaries=boundaries,
            hue_levels=hue_levels,
            lc_planes=lc_planes,
            lc_boundaries=lc_boundaries,
        )

    def _l_index(self, l_val: float) -> int:
        return int(round(_clamp(l_val, L_MIN, L_MAX) * (L_LEVELS - 1)))

    def _h_index(self, hue: float) -> int:
        hue = hue % 360.0
        return int(round(hue / 360.0 * self.hue_levels)) % self.hue_levels

    def plane_pixels(self, l_val: float) -> list[tuple[int, int, int]]:
        return self.planes[self._l_index(l_val)]

    def boundary(self, l_val: float) -> list[tuple[float, float]]:
        return self.boundaries[self._l_index(l_val)]

    def a_row_pixels(self, l_val: float, b_val: float) -> list[tuple[int, int, int]]:
        l_index = self._l_index(l_val)
        _, py = _ab_to_plane_xy(0.0, b_val, self.plane_size)
        py = int(round(_clamp(py, 0, self.plane_size - 1)))
        return [self.planes[l_index][py * self.plane_size + px] for px in range(self.plane_size)]

    def b_col_pixels(self, l_val: float, a_val: float) -> list[tuple[int, int, int]]:
        l_index = self._l_index(l_val)
        px, _ = _ab_to_plane_xy(a_val, 0.0, self.plane_size)
        px = int(round(_clamp(px, 0, self.plane_size - 1)))
        return [self.planes[l_index][py * self.plane_size + px] for py in range(self.plane_size)]

    def lc_plane_pixels(self, hue: float) -> list[tuple[int, int, int]]:
        return self.lc_planes[self._h_index(hue)]

    def lc_boundary(self, hue: float) -> list[tuple[float, float]]:
        return self.lc_boundaries[self._h_index(hue)]

    def l_row_at_chroma(self, hue: float, chroma: float) -> list[tuple[int, int, int]]:
        """Vertical L gradient at fixed hue/chroma (for L slider)."""
        h_index = self._h_index(hue)
        px = int(round(_clamp(chroma / C_MAX, 0.0, 1.0) * (self.plane_size - 1)))
        return [
            self.lc_planes[h_index][py * self.plane_size + px]
            for py in range(self.plane_size - 1, -1, -1)
        ]

    def c_row_at_lightness(self, hue: float, l_val: float) -> list[tuple[int, int, int]]:
        h_index = self._h_index(hue)
        py = int(round(_clamp(1.0 - l_val, 0.0, 1.0) * (self.plane_size - 1)))
        return [self.lc_planes[h_index][py * self.plane_size + px] for px in range(self.plane_size)]

    def hue_ring_colors(self, l_val: float, chroma: float, count: int) -> list[tuple[int, int, int]]:
        return [oklch_to_rgb(l_val, chroma, i / max(count - 1, 1) * 360.0) for i in range(count)]


def _cache_payload(lut: LabColorLUT) -> dict:
    return {
        "version": _LUT_CACHE_VERSION,
        "plane_size": PLANE_SIZE,
        "l_levels": L_LEVELS,
        "hue_levels": HUE_LEVELS,
        "gamut_steps": GAMUT_STEPS,
        "lut": lut,
    }


def _load_lut_cache() -> Optional[LabColorLUT]:
    if not _LUT_CACHE_PATH.is_file():
        return None
    try:
        with gzip.open(_LUT_CACHE_PATH, "rb") as handle:
            payload = pickle.load(handle)
    except (OSError, EOFError, pickle.UnpicklingError, KeyError, AttributeError):
        return None
    if payload.get("version") != _LUT_CACHE_VERSION:
        return None
    if (
        payload.get("plane_size") != PLANE_SIZE
        or payload.get("l_levels") != L_LEVELS
        or payload.get("hue_levels") != HUE_LEVELS
    ):
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
    global _LUT
    if _try_load_lut():
        return _LUT  # type: ignore[return-value]
    with _LUT_LOCK:
        if _LUT is None:
            _LUT = LabColorLUT.build()
            _save_lut_cache(_LUT)
    return _LUT


def start_lab_lut_build() -> None:
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


def try_load_lab_lut() -> bool:
    return _try_load_lut()


def peek_lab_lut() -> Optional[LabColorLUT]:
    return _LUT


# Back-compat aliases used by the OKLab plane picker.
lab_to_rgb = oklab_to_rgb
rgb_to_lab = rgb_to_oklab
