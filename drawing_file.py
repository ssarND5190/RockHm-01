"""Save and load drawing documents as JSON (.dhdraw) files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from draw_objects import (
    DEFAULT_LINE_WIDTH,
    DrawObject,
    DrawTool,
    Line,
    Rectangle,
    Triangle,
)

FILE_VERSION = 1
FILE_EXTENSION = ".dhdraw"
FILE_TYPE_LABEL = "Drawing files"
FILE_TYPE_PATTERN = "*.dhdraw"


@dataclass
class LoadedDocument:
    shapes: list[DrawObject]
    paint_canvas: dict[str, float]
    next_id: int
    next_rect_name: int
    next_line_name: int
    next_triangle_name: int
    next_line_width: float
    selected_id: Optional[int]
    draw_tool: DrawTool


def file_dialog_types() -> list[tuple[str, str]]:
    return [
        (FILE_TYPE_LABEL, FILE_TYPE_PATTERN),
        ("JSON files", "*.json"),
        ("All files", "*.*"),
    ]


def _shape_to_dict(shape: DrawObject) -> dict[str, Any]:
    if isinstance(shape, Rectangle):
        return {
            "type": "rectangle",
            "id": shape.id,
            "name": shape.name,
            "cx": shape.cx,
            "cy": shape.cy,
            "width": shape.width,
            "height": shape.height,
            "rotation": shape.rotation,
            "color": shape.color,
            "z_index": shape.z_index,
        }
    if isinstance(shape, Line):
        return {
            "type": "line",
            "id": shape.id,
            "name": shape.name,
            "x1": shape.x1,
            "y1": shape.y1,
            "x2": shape.x2,
            "y2": shape.y2,
            "color": shape.color,
            "stroke_width": shape.stroke_width,
            "z_index": shape.z_index,
        }
    if isinstance(shape, Triangle):
        return {
            "type": "triangle",
            "id": shape.id,
            "name": shape.name,
            "x1": shape.x1,
            "y1": shape.y1,
            "x2": shape.x2,
            "y2": shape.y2,
            "x3": shape.x3,
            "y3": shape.y3,
            "color": shape.color,
            "z_index": shape.z_index,
        }
    raise TypeError(f"Unsupported shape type: {type(shape)!r}")


def _shape_from_dict(data: dict[str, Any]) -> DrawObject:
    kind = data.get("type")
    if kind == "rectangle":
        return Rectangle(
            id=int(data["id"]),
            name=str(data["name"]),
            cx=float(data["cx"]),
            cy=float(data["cy"]),
            width=float(data["width"]),
            height=float(data["height"]),
            rotation=float(data.get("rotation", 0.0)),
            color=str(data.get("color", "#4a90d9")),
            z_index=int(data.get("z_index", 0)),
        )
    if kind == "line":
        return Line(
            id=int(data["id"]),
            name=str(data["name"]),
            x1=float(data["x1"]),
            y1=float(data["y1"]),
            x2=float(data["x2"]),
            y2=float(data["y2"]),
            color=str(data.get("color", "#e88c4a")),
            stroke_width=float(data.get("stroke_width", DEFAULT_LINE_WIDTH)),
            z_index=int(data.get("z_index", 0)),
        )
    if kind == "triangle":
        return Triangle(
            id=int(data["id"]),
            name=str(data["name"]),
            x1=float(data["x1"]),
            y1=float(data["y1"]),
            x2=float(data["x2"]),
            y2=float(data["y2"]),
            x3=float(data["x3"]),
            y3=float(data["y3"]),
            color=str(data.get("color", "#9b59b6")),
            z_index=int(data.get("z_index", 0)),
        )
    raise ValueError(f"Unknown shape type: {kind!r}")


def _infer_name_counters(shapes: list[DrawObject]) -> tuple[int, int, int]:
    next_rect = next_line = next_triangle = 1
    for shape in shapes:
        if isinstance(shape, Rectangle) and shape.name.startswith("rect"):
            try:
                next_rect = max(next_rect, int(shape.name[4:]) + 1)
            except ValueError:
                pass
        elif isinstance(shape, Line) and shape.name.startswith("line"):
            try:
                next_line = max(next_line, int(shape.name[4:]) + 1)
            except ValueError:
                pass
        elif isinstance(shape, Triangle) and shape.name.startswith("tri"):
            try:
                next_triangle = max(next_triangle, int(shape.name[3:]) + 1)
            except ValueError:
                pass
    return next_rect, next_line, next_triangle


def build_document(
    *,
    shapes: list[DrawObject],
    paint_canvas: Any,
    next_id: int,
    next_rect_name: int,
    next_line_name: int,
    next_triangle_name: int,
    next_line_width: float,
    selected_id: Optional[int],
    draw_tool: DrawTool,
) -> dict[str, Any]:
    return {
        "version": FILE_VERSION,
        "paint_canvas": {
            "cx": paint_canvas.cx,
            "cy": paint_canvas.cy,
            "width": paint_canvas.width,
            "height": paint_canvas.height,
        },
        "next_id": next_id,
        "next_rect_name": next_rect_name,
        "next_line_name": next_line_name,
        "next_triangle_name": next_triangle_name,
        "next_line_width": next_line_width,
        "selected_id": selected_id,
        "draw_tool": draw_tool,
        "shapes": [_shape_to_dict(shape) for shape in shapes],
    }


def parse_document(data: dict[str, Any]) -> LoadedDocument:
    version = data.get("version")
    if version != FILE_VERSION:
        raise ValueError(f"Unsupported file version: {version!r}")

    shapes = [_shape_from_dict(item) for item in data.get("shapes", [])]
    shape_ids = {shape.id for shape in shapes}

    next_rect, next_line, next_triangle = _infer_name_counters(shapes)
    next_id = int(data.get("next_id", max(shape_ids, default=0) + 1))
    next_id = max(next_id, max(shape_ids, default=0) + 1)

    selected_id = data.get("selected_id")
    if selected_id is not None:
        selected_id = int(selected_id)
        if selected_id not in shape_ids:
            selected_id = None

    draw_tool = data.get("draw_tool", "rectangle")
    if draw_tool not in ("rectangle", "line", "triangle"):
        draw_tool = "rectangle"

    paint = data.get("paint_canvas", {})
    return LoadedDocument(
        shapes=shapes,
        paint_canvas={
            "cx": float(paint.get("cx", 400.0)),
            "cy": float(paint.get("cy", 320.0)),
            "width": float(paint.get("width", 960.0)),
            "height": float(paint.get("height", 540.0)),
        },
        next_id=next_id,
        next_rect_name=int(data.get("next_rect_name", next_rect)),
        next_line_name=int(data.get("next_line_name", next_line)),
        next_triangle_name=int(data.get("next_triangle_name", next_triangle)),
        next_line_width=float(data.get("next_line_width", DEFAULT_LINE_WIDTH)),
        selected_id=selected_id,
        draw_tool=draw_tool,
    )


def save_document(path: str | Path, document: dict[str, Any]) -> None:
    target = Path(path)
    if target.suffix == "":
        target = target.with_suffix(FILE_EXTENSION)
    target.write_text(json.dumps(document, indent=2), encoding="utf-8")


def load_document(path: str | Path) -> LoadedDocument:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Drawing file must contain a JSON object.")
    return parse_document(data)
