"""Scheme 代码生成与结果解析的公共助手。

约定：每个工具生成的脚本以"单一字符串"为最终表达式（见 docs/protocol.md），
字符串内容形如 "key1=val1;key2=val2" 或单个值，由本模块负责解析。
"""

from __future__ import annotations

import math

from gimp_client import GimpClient


def esc(value: str) -> str:
    """Python 字符串转义为带双引号的 Scheme 字符串字面量（防注入，必走此函数）。"""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def num(value: int | float) -> str:
    """数字格式化为 Scheme 字面量；浮点保留足够精度。"""
    if isinstance(value, bool):
        raise TypeError("布尔值请用 TRUE/FALSE 常量")
    if isinstance(value, int):
        return str(value)
    f = float(value)
    if not math.isfinite(f):
        raise ValueError(f"数值必须是有限数（收到 {value!r}），无法生成合法 Scheme 字面量")
    return repr(f)


def parse_kv(body: str) -> dict[str, str]:
    """解析 "k1=v1;k2=v2" 形式的工具返回串。"""
    result: dict[str, str] = {}
    body = body.strip()
    if body:
        for pair in body.split(";"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                result[k.strip()] = v.strip()
    return result


def require_image(client: GimpClient) -> int:
    """返回当前活动图像 ID；无打开图像时抛 ScriptFuError 风格的明确错误。"""
    body = client.eval_string(
        "(let ((imgs (car (gimp-get-images))))"
        "  (if (> (vector-length imgs) 0)"
        "      (number->string (vector-ref imgs 0))"
        "      \"\"))"
    )
    if not body:
        from gimp_client import ScriptFuError

        raise ScriptFuError("GIMP 中没有打开的图像，请先 open_image 或 new_image")
    return int(body)


def selected_drawable_expr(img: int) -> str:
    """生成取图像当前选中 drawable（图层）ID 的 Scheme 表达式。

    无选中图层时（例如图层被删光）抛出可读错误，而不是 TinyScheme 的
    "vector-ref: out of bounds: 0"——后者大模型无法据此自纠。
    """
    return (
        f"(let ((v (car (gimp-image-get-selected-drawables {img}))))"
        "  (if (= (vector-length v) 0)"
        "      (error \"当前图像没有选中的图层（图层可能已被删光），请先 add_layer 或重新 open_image\")"
        "      (vector-ref v 0)))"
    )
