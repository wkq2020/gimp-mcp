"""图层管理工具。

PDB 依据（GIMP 3.2.6 实测）：
- gimp-layer-new：3.2 签名 (image name width height type opacity mode)
- gimp-image-insert-layer：(image layer parent position)
- gimp-image-get-layer-by-name：按名称查找图层（已验证存在）
- gimp-image-remove-layer：(image layer)
- gimp-image-set-selected-layers：(image (vector layer))，GIMP 3 替代已删除的 gimp-image-set-active-layer
- gimp-layer-copy：(layer add-alpha) 返回副本
- gimp-image-get-width/height 取画布尺寸
"""

from __future__ import annotations

from gimp_client import GimpClient, ScriptFuError
from scheme import esc, num, require_image, selected_drawable_expr

_LAYER_MODES = {
    "normal": "LAYER-MODE-NORMAL",
    "multiply": "LAYER-MODE-MULTIPLY",
    "screen": "LAYER-MODE-SCREEN",
    "overlay": "LAYER-MODE-OVERLAY",
    "addition": "LAYER-MODE-ADDITION",
    "subtract": "LAYER-MODE-SUBTRACT",
    "difference": "LAYER-MODE-DIFFERENCE",
}


def _find_layer(client: GimpClient, img: int, name: str) -> int:
    body = client.eval(
        f"(gimp-image-get-layer-by-name {img} {esc(name)})"
    ).strip()
    # 未找到时返回 (-1) 或 (-1 ...)
    first = body.strip("()").split()[0] if body.strip("()") else "-1"
    layer_id = int(first)
    if layer_id < 0:
        raise ScriptFuError(f"图层不存在: {name!r}")
    return layer_id


def add_layer(
    client: GimpClient, name: str, mode: str = "normal", opacity: float = 100.0
) -> dict:
    """新建透明图层并置于顶层、设为活动图层。PDB: gimp-layer-new + gimp-image-insert-layer。

    - mode: normal / multiply / screen / overlay / addition / subtract / difference
    - opacity: 0–100
    """
    mode_const = _LAYER_MODES.get(mode.lower())
    if mode_const is None:
        raise ValueError(f"不支持的图层模式: {mode}（可选 {', '.join(_LAYER_MODES)}）")
    if not (0 <= opacity <= 100):
        raise ValueError(f"opacity 须在 0–100: {opacity}")
    img = require_image(client)
    # 图层类型跟随图像色彩模式（灰度/索引图不能想当然用 RGBA）
    code = f"""
(let ((img {img}))
  (let ((bt (car (gimp-image-get-base-type img))))
    (let ((layer (car (gimp-layer-new img {esc(name)}
                                      (car (gimp-image-get-width img))
                                      (car (gimp-image-get-height img))
                                      (cond ((= bt 0) RGBA-IMAGE)
                                            ((= bt 1) GRAYA-IMAGE)
                                            (else INDEXEDA-IMAGE))
                                      {num(opacity)} {mode_const}))))
      (gimp-image-insert-layer img layer -1 0)
      (gimp-image-set-selected-layers img (vector layer))
      (number->string layer))))
""".strip()
    layer_id = int(client.eval_string(code))
    return {"layer_id": layer_id, "name": name, "mode": mode, "opacity": opacity}


def remove_layer(client: GimpClient, name: str) -> dict:
    """按名称删除图层。PDB: gimp-image-get-layer-by-name + gimp-image-remove-layer。"""
    img = require_image(client)
    layer_id = _find_layer(client, img, name)
    client.eval(f"(gimp-image-remove-layer {img} {layer_id})")
    return {"removed": name, "layer_id": layer_id}


def set_active_layer(client: GimpClient, name: str) -> dict:
    """按名称设为活动（选中）图层。PDB: gimp-image-set-selected-layers。"""
    img = require_image(client)
    layer_id = _find_layer(client, img, name)
    client.eval(f"(gimp-image-set-selected-layers {img} (vector {layer_id}))")
    return {"active_layer": name, "layer_id": layer_id}


def duplicate_layer(client: GimpClient, name: str | None = None) -> dict:
    """复制图层（默认当前活动图层；给名称则复制指定图层）。PDB: gimp-layer-copy + gimp-image-insert-layer。"""
    img = require_image(client)
    if name is not None:
        src = _find_layer(client, img, name)
    else:
        src = client.eval_string(
            f"(number->string {selected_drawable_expr(img)})"
        )
    code = f"""
(let ((img {img}) (src {src}))
  (let ((copy (car (gimp-layer-copy src TRUE)))
        (parent (car (gimp-item-get-parent src)))
        (position (car (gimp-image-get-item-position img src))))
    (gimp-image-insert-layer img copy parent position)
    (gimp-image-set-selected-layers img (vector copy))
    (car (gimp-item-get-name copy))))
""".strip()
    new_name = client.eval_string(code)
    return {"duplicated_from": name or "active", "new_layer_name": new_name}
