"""选区工具。

PDB 依据（GIMP 3.2.6，gimp-pdb-procedure-exists 验证存在）：
- gimp-selection-all / gimp-selection-none / gimp-selection-invert：(image)
- gimp-image-select-rectangle / gimp-image-select-ellipse：(image operation x y width height)，
  operation 取 CHANNEL-OP-REPLACE(2)
- 填充：gimp-context-set-foreground（接受 "#rrggbb" 字符串）+ gimp-drawable-edit-fill(drawable FILL-FOREGROUND)，
  编辑操作自动受当前选区约束；用 gimp-context-push/pop 保护上下文
"""

from __future__ import annotations

import re

from gimp_client import GimpClient
from scheme import esc, num, require_image, selected_drawable_expr

_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


def _norm_hex(color: str) -> str:
    if not _HEX_RE.match(color):
        raise ValueError(f"颜色须为 #RRGGBB 十六进制: {color!r}")
    return "#" + color.lstrip("#").lower()


def select_all(client: GimpClient) -> dict:
    """全选。PDB: gimp-selection-all。"""
    img = require_image(client)
    client.eval(f"(gimp-selection-all {img})")
    return {"selection": "all"}


def select_none(client: GimpClient) -> dict:
    """取消选区。PDB: gimp-selection-none。"""
    img = require_image(client)
    client.eval(f"(gimp-selection-none {img})")
    return {"selection": "none"}


def select_invert(client: GimpClient) -> dict:
    """反选。PDB: gimp-selection-invert。"""
    img = require_image(client)
    client.eval(f"(gimp-selection-invert {img})")
    return {"selection": "inverted"}


def select_rect(client: GimpClient, x: int, y: int, width: int, height: int) -> dict:
    """矩形选区（替换当前选区）。PDB: gimp-image-select-rectangle。"""
    if width <= 0 or height <= 0:
        raise ValueError(f"选区宽高必须为正: {width}x{height}")
    img = require_image(client)
    client.eval(
        f"(gimp-image-select-rectangle {img} 2 {num(x)} {num(y)} {num(width)} {num(height)})"
    )
    return {"selection": "rect", "x": x, "y": y, "width": width, "height": height}


def select_ellipse(client: GimpClient, x: int, y: int, width: int, height: int) -> dict:
    """椭圆选区（替换当前选区）。PDB: gimp-image-select-ellipse。"""
    if width <= 0 or height <= 0:
        raise ValueError(f"选区宽高必须为正: {width}x{height}")
    img = require_image(client)
    client.eval(
        f"(gimp-image-select-ellipse {img} 2 {num(x)} {num(y)} {num(width)} {num(height)})"
    )
    return {"selection": "ellipse", "x": x, "y": y, "width": width, "height": height}


def fill_selection(client: GimpClient, color: str, opacity: float = 100.0) -> dict:
    """用前景色填充当前选区（无选区时填充整个图层）。PDB: gimp-context-set-foreground + gimp-drawable-edit-fill。

    - color: #RRGGBB
    - opacity: 0–100
    """
    hex_color = _norm_hex(color)
    if not (0 <= opacity <= 100):
        raise ValueError(f"opacity 须在 0–100: {opacity}")
    img = require_image(client)
    code = f"""
(let ((drawable {selected_drawable_expr(img)}))
  (gimp-context-set-foreground {esc(hex_color)})
  (gimp-context-set-opacity {num(opacity)})
  (gimp-drawable-edit-fill drawable FILL-FOREGROUND)
  "filled")
""".strip()
    client.eval("(gimp-context-push)")
    try:
        client.eval_string(code)
    finally:
        client.eval("(gimp-context-pop)")
    return {"filled": hex_color, "opacity": opacity}
