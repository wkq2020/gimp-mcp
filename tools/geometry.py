"""几何与构图工具。

PDB 依据（GIMP 3.2.6，gimp-pdb-procedure-exists 验证存在；签名与 2.10 一致并经调用验证）：
- gimp-image-crop：(image new-width new-height offx offy)
- gimp-image-scale：(image width height)
- gimp-image-resize：(image width height offx offy)  —— 调整画布
- gimp-image-rotate：(image rotate-type)，0=90° 1=180° 2=270°（顺时针）
- gimp-image-flip：(image flip-type)，0=水平 1=垂直
"""

from __future__ import annotations

from gimp_client import GimpClient
from scheme import num, parse_kv, require_image

_ROTATE_MAP = {90: 0, 180: 1, 270: 2}
_FLIP_MAP = {"horizontal": 0, "h": 0, "水平": 0, "vertical": 1, "v": 1, "垂直": 1}


def _image_size(client: GimpClient, img: int) -> tuple[int, int]:
    kv = parse_kv(
        client.eval_string(
            f'(string-append "w=" (number->string (car (gimp-image-get-width {img})))'
            f' ";h=" (number->string (car (gimp-image-get-height {img}))))'
        )
    )
    return int(kv["w"]), int(kv["h"])


def crop_to_rect(client: GimpClient, x: int, y: int, width: int, height: int) -> dict:
    """按像素矩形裁剪当前活动图像。PDB: gimp-image-crop。"""
    if width <= 0 or height <= 0:
        raise ValueError(f"裁剪宽高必须为正: {width}x{height}")
    img = require_image(client)
    w, h = _image_size(client, img)
    if x < 0 or y < 0 or x + width > w or y + height > h:
        raise ValueError(f"裁剪区域 ({x},{y},{width},{height}) 超出图像范围 ({w}x{h})")
    client.eval(f"(gimp-image-crop {img} {num(width)} {num(height)} {num(x)} {num(y)})")
    return {"width": width, "height": height, "offset_x": x, "offset_y": y}


def crop_to_aspect(
    client: GimpClient, ratio_w: float, ratio_h: float, anchor: str = "center"
) -> dict:
    """按宽高比裁剪（默认居中）。PDB: gimp-image-crop。

    anchor: center / top / bottom / left / right。
    """
    if ratio_w <= 0 or ratio_h <= 0:
        raise ValueError(f"宽高比必须为正: {ratio_w}:{ratio_h}")
    anchor = anchor.lower()
    if anchor not in ("center", "top", "bottom", "left", "right"):
        raise ValueError(f"不支持的 anchor: {anchor}")
    img = require_image(client)
    w, h = _image_size(client, img)
    target = ratio_w / ratio_h
    current = w / h
    if current > target:  # 太宽，裁两侧
        new_w, new_h = round(h * target), h
    else:  # 太高，裁上下
        new_w, new_h = w, round(w / target)
    if new_w < 1 or new_h < 1:
        raise ValueError(
            f"图像 {w}x{h} 对比例 {ratio_w}:{ratio_h} 过小，裁剪结果不足 1 像素，请改用 crop_to_rect"
        )
    if anchor in ("center", "top", "bottom"):
        x = (w - new_w) // 2
    elif anchor == "left":
        x = 0
    else:
        x = w - new_w
    if anchor in ("center", "left", "right"):
        y = (h - new_h) // 2
    elif anchor == "top":
        y = 0
    else:
        y = h - new_h
    client.eval(f"(gimp-image-crop {img} {num(new_w)} {num(new_h)} {num(x)} {num(y)})")
    return {
        "width": new_w,
        "height": new_h,
        "offset_x": x,
        "offset_y": y,
        "aspect": f"{new_w}:{new_h}",
    }


def scale_image(
    client: GimpClient,
    width: int | None = None,
    height: int | None = None,
    keep_aspect: bool = True,
) -> dict:
    """缩放图像。PDB: gimp-image-scale。

    - keep_aspect=True：只给一边时按比例推算另一边
    - keep_aspect=False：只给一边时另一边保持不变（两边都给则拉伸）
    """
    if width is None and height is None:
        raise ValueError("width 和 height 至少给一个")
    img = require_image(client)
    w, h = _image_size(client, img)
    if width is None:
        width = round(w * height / h) if keep_aspect else w
    elif height is None:
        height = round(h * width / w) if keep_aspect else h
    if width <= 0 or height <= 0:
        raise ValueError(f"缩放目标尺寸非法: {width}x{height}")
    client.eval(f"(gimp-image-scale {img} {num(width)} {num(height)})")
    return {"width": width, "height": height, "from": f"{w}x{h}"}


def resize_canvas(
    client: GimpClient,
    width: int,
    height: int,
    offset_x: int = 0,
    offset_y: int = 0,
) -> dict:
    """调整画布大小（不改变图层内容缩放）。PDB: gimp-image-resize。"""
    if width <= 0 or height <= 0:
        raise ValueError(f"画布宽高必须为正: {width}x{height}")
    img = require_image(client)
    client.eval(
        f"(gimp-image-resize {img} {num(width)} {num(height)} {num(offset_x)} {num(offset_y)})"
    )
    return {"width": width, "height": height, "offset_x": offset_x, "offset_y": offset_y}


def rotate_image(client: GimpClient, degrees: int) -> dict:
    """旋转图像（顺时针 90/180/270 度）。PDB: gimp-image-rotate。"""
    deg = degrees % 360
    if deg not in _ROTATE_MAP:
        raise ValueError(f"仅支持 90/180/270 度旋转: {degrees}")
    img = require_image(client)
    client.eval(f"(gimp-image-rotate {img} {_ROTATE_MAP[deg]})")
    return {"rotated_degrees": deg}


def flip_image(client: GimpClient, direction: str = "horizontal") -> dict:
    """翻转图像。direction: horizontal/vertical。PDB: gimp-image-flip。"""
    flip_type = _FLIP_MAP.get(direction.lower())
    if flip_type is None:
        raise ValueError(f"direction 仅支持 horizontal/vertical: {direction}")
    img = require_image(client)
    client.eval(f"(gimp-image-flip {img} {flip_type})")
    return {"flipped": "horizontal" if flip_type == 0 else "vertical"}
