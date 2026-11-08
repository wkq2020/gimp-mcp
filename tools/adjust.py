"""调色与滤镜工具。

PDB 依据（GIMP 3.2.6 实测，探针 scripts/probe_adjust.py / probe_text.py）：
- 滤镜统一入口 gimp-drawable-merge-new-filter：(drawable "op" 0 LAYER-MODE-REPLACE 1.0 "key" val ...)
  - 亮度对比度 "gimp:brightness-contrast"：brightness/contrast 范围实测 -1.0–1.0（越界报错含范围文本）
  - 去色 "gimp:desaturate"："mode" DESATURATE-LIGHTNESS/LUMINOSITY/AVERAGE
  - 高斯 "gegl:gaussian-blur"："std-dev-x/y"（= UI 半径 × 0.32，取自随装脚本 drop-shadow.scm）
  - USM "gegl:unsharp-mask"："std-dev" "scale" "threshold"（实测调用成功）
- gimp-drawable-levels：(drawable channel low-in high-in clamp-in gamma low-out high-out clamp-out)，0.0–1.0
- gimp-drawable-hue-saturation：(drawable hue-range hue-offset saturation lightness overlap)（6 参实测成功）
- 文字 gimp-text-font：3.2 签名 (image drawable x y text border antialias size font-resource-id)，
  字体须为资源 ID（gimp-font-get-by-name 取得）；颜色取自 context 前景色（随装脚本 slide.scm 同款用法）
- 定位：gimp-drawable-get-width/height + gimp-layer-set-offsets

selection_only 语义：
- false（默认）：若存在选区，先 gimp-selection-save 暂存、select-none、执行、
  再 gimp-image-select-item 从暂存 channel 恢复（GIMP 3 无 gimp-selection-load），
  保证"作用于全图"且不丢选区；op 失败时由 Python finally 保证恢复。
- true：直接在目标 drawable 上执行 op。这些 PDB 操作原生受选区约束（false 分支正是
  因此才要先清空选区），所以不需要复制层 + 蒙版 + 合并，也不会改变图层结构与图层 ID。
  无选区时返回明确错误。
"""

from __future__ import annotations

import re

from gimp_client import GimpClient, ScriptFuError
from scheme import esc, num, parse_kv, require_image, selected_drawable_expr

_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")

_LEVEL_CHANNELS = {"value": 0, "red": 1, "green": 2, "blue": 3, "alpha": 4}
_DESATURATE_MODES = {
    "lightness": 0,
    "luminosity": 1,
    "average": 2,
    "均值": 2,
}
_ANCHORS = ("top-left", "top-right", "bottom-left", "bottom-right", "center")


def _apply(client: GimpClient, img: int, op_code: str, drawable: str, selection_only: bool) -> None:
    """执行调色/滤镜操作（op_code 中可用 drawable 变量），按 selection_only 包装。

    selection_only=False 时分多次 eval 并用 try/finally 恢复选区、清理暂存 channel。
    """
    # 先把 drawable 表达式定值成 ID，再动选区：gimp-selection-save 会把新建的 channel
    # 变成选中 drawable，若等执行 op 时才求值，op 会打到那个临时 channel 上并随它一起被删除。
    drawable = client.eval_string(f"(number->string {drawable})")
    if selection_only:
        empty = client.eval_string(
            f"(number->string (car (gimp-selection-is-empty {img})))"
        )
        if empty == "1":
            raise ScriptFuError("selection_only=true 但当前没有活动选区，请先建立选区")
        # 这些 op 原生受选区约束（下方 else 分支正是因此才要暂存并清空选区），
        # 直接执行即"仅作用于选区"，无需复制层 + 蒙版 + merge-down。
        client.eval(f"(let ((img {img}) (drawable {drawable})) {op_code})")
    else:
        # 有选区时先暂存并清空，op 完成后恢复，保证"作用于全图"且选区不丢
        saved = client.eval_string(
            f"(let ((img {img}))"
            "  (if (= FALSE (car (gimp-selection-is-empty img)))"
            "      (let ((saved (car (gimp-selection-save img))))"
            "        (gimp-selection-none img)"
            "        (number->string saved))"
            "      \"\"))"
        )
        try:
            client.eval(f"(let ((img {img}) (drawable {drawable})) {op_code})")
        finally:
            if saved:
                # GIMP 3 无 gimp-selection-load，用 gimp-image-select-item 从 channel 恢复选区
                client.eval(f"(gimp-image-select-item {img} 2 {saved})")
                client.eval(f"(gimp-image-remove-channel {img} {saved})")


def adjust_brightness_contrast(client: GimpClient, brightness: float, contrast: float,
                               selection_only: bool = False) -> dict:
    """亮度/对比度，范围 -100–100（映射为 GEGL 的 -1.0–1.0）。PDB: gimp-drawable-merge-new-filter "gimp:brightness-contrast"。"""
    for name, v in (("brightness", brightness), ("contrast", contrast)):
        if not (-100 <= v <= 100):
            raise ValueError(f"{name} 须在 -100–100: {v}")
    img = require_image(client)
    op = (f'(gimp-drawable-merge-new-filter drawable "gimp:brightness-contrast" 0 '
          f'LAYER-MODE-REPLACE 1.0 "brightness" {num(brightness / 100)} "contrast" {num(contrast / 100)})')
    _apply(client, img, op, selected_drawable_expr(img), selection_only)
    return {"brightness": brightness, "contrast": contrast, "selection_only": selection_only}


def adjust_levels(client: GimpClient, channel: str = "value",
                  input_black: float = 0, input_white: float = 255,
                  gamma: float = 1.0, selection_only: bool = False) -> dict:
    """色阶（仅调整输入黑场/白场/gamma，输出固定 0–255）。PDB: gimp-drawable-levels。

    - channel: value / red / green / blue / alpha
    - input_black / input_white: 0–255；gamma: 0.1–10
    """
    ch = _LEVEL_CHANNELS.get(channel.lower())
    if ch is None:
        raise ValueError(f"不支持的通道: {channel}")
    if not (0 <= input_black < input_white <= 255):
        raise ValueError(f"要求 0 <= 黑场 < 白场 <= 255: {input_black}/{input_white}")
    if not (0.1 <= gamma <= 10):
        raise ValueError(f"gamma 须在 0.1–10: {gamma}")
    img = require_image(client)
    op = (f"(gimp-drawable-levels drawable {ch} {num(input_black / 255)} {num(input_white / 255)} "
          f"TRUE {num(gamma)} 0.0 1.0 TRUE)")
    _apply(client, img, op, selected_drawable_expr(img), selection_only)
    return {"channel": channel, "input_black": input_black,
            "input_white": input_white, "gamma": gamma, "selection_only": selection_only}


def adjust_hue_saturation(client: GimpClient, hue: float = 0, saturation: float = 0,
                          lightness: float = 0, selection_only: bool = False) -> dict:
    """色相/饱和度/明度。PDB: gimp-drawable-hue-saturation。

    - hue: -180–180；saturation / lightness: -100–100
    """
    if not (-180 <= hue <= 180):
        raise ValueError(f"hue 须在 -180–180: {hue}")
    for name, v in (("saturation", saturation), ("lightness", lightness)):
        if not (-100 <= v <= 100):
            raise ValueError(f"{name} 须在 -100–100: {v}")
    img = require_image(client)
    op = (f"(gimp-drawable-hue-saturation drawable 0 {num(hue)} "
          f"{num(saturation)} {num(lightness)} 0)")
    _apply(client, img, op, selected_drawable_expr(img), selection_only)
    return {"hue": hue, "saturation": saturation, "lightness": lightness,
            "selection_only": selection_only}


def desaturate(client: GimpClient, mode: str = "luminosity",
               selection_only: bool = False) -> dict:
    """去色。mode: luminosity / lightness / average。PDB: gimp-drawable-merge-new-filter "gimp:desaturate"。

    mode 参数实测须传数值（DESATURATE-* 符号常量在该 Script-Fu 环境未绑定）：
    0=lightness 1=luminosity 2=average。
    """
    mode_val = _DESATURATE_MODES.get(mode.lower())
    if mode_val is None:
        raise ValueError(f"不支持的去色模式: {mode}（可选 {', '.join(_DESATURATE_MODES)}）")
    img = require_image(client)
    op = (f'(gimp-drawable-merge-new-filter drawable "gimp:desaturate" 0 '
          f'LAYER-MODE-REPLACE 1.0 "mode" {mode_val})')
    _apply(client, img, op, selected_drawable_expr(img), selection_only)
    return {"mode": mode, "selection_only": selection_only}


def gaussian_blur(client: GimpClient, radius: float, selection_only: bool = False) -> dict:
    """高斯模糊。PDB: gimp-drawable-merge-new-filter "gegl:gaussian-blur"。

    换算：std-dev-x/y = radius × 0.32（沿用 GIMP 2.x plug-in-gauss 的 radius 约定，
    取自随装脚本 drop-shadow.scm）。注意与 unsharp_mask 的 radius 口径不同：
    那边 std-dev = radius，同名参数的实际强度差约 3 倍。
    与 GIMP 3 高斯模糊对话框 Size X/Y 是否一致，尚未实测比对。
    """
    if radius <= 0:
        raise ValueError(f"radius 必须为正: {radius}")
    std = round(radius * 0.32, 4)
    img = require_image(client)
    op = (f'(gimp-drawable-merge-new-filter drawable "gegl:gaussian-blur" 0 '
          f'LAYER-MODE-REPLACE 1.0 "std-dev-x" {num(std)} "std-dev-y" {num(std)} "filter" "auto")')
    _apply(client, img, op, selected_drawable_expr(img), selection_only)
    return {"radius": radius, "std_dev": std, "selection_only": selection_only}


def unsharp_mask(client: GimpClient, radius: float, amount: float, threshold: float = 0.0,
                 selection_only: bool = False) -> dict:
    """USM 锐化。PDB: gimp-drawable-merge-new-filter "gegl:unsharp-mask"（std-dev/scale/threshold）。

    换算：std-dev = radius（不乘系数），与 gaussian_blur 的 radius × 0.32 口径不同。
    """
    if radius <= 0 or amount <= 0:
        raise ValueError(f"radius/amount 必须为正: {radius}/{amount}")
    img = require_image(client)
    op = (f'(gimp-drawable-merge-new-filter drawable "gegl:unsharp-mask" 0 '
          f'LAYER-MODE-REPLACE 1.0 "std-dev" {num(radius)} "scale" {num(amount)} '
          f'"threshold" {num(threshold)})')
    _apply(client, img, op, selected_drawable_expr(img), selection_only)
    return {"radius": radius, "amount": amount, "threshold": threshold,
            "selection_only": selection_only}


def add_text(client: GimpClient, text: str, font: str = "Sans-serif", size: float = 32,
             color: str = "#ffffff", position: tuple[float, float] | None = None,
             anchor: str | None = None, margin: float = 10) -> dict:
    """添加文字图层。PDB: gimp-font-get-by-name + gimp-text-font + gimp-layer-set-offsets（+ context 前景色）。

    - position=(x, y) 显式指定左上角坐标；否则用 anchor 定位
    - anchor: top-left / top-right / bottom-left / bottom-right / center（默认 top-left），配合 margin
    - color 取自 context 前景色（随装脚本 slide.scm 同款用法）
    """
    if not text:
        raise ValueError("text 不能为空")
    if not _HEX_RE.match(color):
        raise ValueError(f"颜色须为 #RRGGBB: {color!r}")
    hex_color = "#" + color.lstrip("#").lower()
    if anchor is None:
        anchor = "top-left" if position is None else None
    if anchor is not None and anchor not in _ANCHORS:
        raise ValueError(f"不支持的 anchor: {anchor}（可选 {', '.join(_ANCHORS)}）")
    img = require_image(client)
    font_body = client.eval(f"(gimp-font-get-by-name {esc(font)})").strip()
    font_id = int(font_body.strip("()").split()[0])
    if font_id <= 0:
        raise ScriptFuError(
            f"字体不存在: {font!r}。请调用 list_fonts 工具查看 GIMP 已安装字体名"
            f"（可用 contains 参数过滤），把返回的名称原样传给 font"
        )
    if position is not None:
        x, y = position
        pos_code = f"(gimp-layer-set-offsets layer {num(x)} {num(y)})"
    else:
        # 按 anchor 计算偏移：需要文字层与画布的宽高
        pos_code = f"""
(let ((tw (car (gimp-drawable-get-width layer)))
      (th (car (gimp-drawable-get-height layer)))
      (iw (car (gimp-image-get-width img)))
      (ih (car (gimp-image-get-height img))))
  (gimp-layer-set-offsets layer
    {_anchor_x_expr(anchor, margin)}
    {_anchor_y_expr(anchor, margin)}))
""".strip()
    code = f"""
(let ((img {img}))
  (let ((layer (car (gimp-text-font img -1 0 0 {esc(text)} 0 TRUE {num(size)} {font_id}))))
    {pos_code}
    (string-append "layer=" (number->string layer)
                   ";w=" (number->string (car (gimp-drawable-get-width layer)))
                   ";h=" (number->string (car (gimp-drawable-get-height layer))))))
""".strip()
    # push/pop 分步执行，pop 放在 finally 中：即使 text-font 失败 context 栈也不泄漏
    client.eval(f"(begin (gimp-context-push) (gimp-context-set-foreground {esc(hex_color)}))")
    try:
        kv = parse_kv(client.eval_string(code))
    finally:
        client.eval("(gimp-context-pop)")
    return {"layer_id": int(kv["layer"]), "text": text, "font": font, "size": size,
            "color": hex_color, "anchor": anchor or "position",
            "text_width": int(kv["w"]), "text_height": int(kv["h"])}


def _anchor_x_expr(anchor: str, margin: float) -> str:
    m = num(margin)
    if anchor in ("top-left", "bottom-left"):
        return m
    if anchor in ("top-right", "bottom-right"):
        return f"(- iw tw {m})"
    return "(quotient (- iw tw) 2)"


def _anchor_y_expr(anchor: str, margin: float) -> str:
    m = num(margin)
    if anchor in ("top-left", "top-right"):
        return m
    if anchor in ("bottom-left", "bottom-right"):
        return f"(- ih th {m})"
    return "(quotient (- ih th) 2)"
