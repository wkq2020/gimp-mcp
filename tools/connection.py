"""连接与元信息工具。

PDB 依据（GIMP 3.2.6 实测，gimp-pdb-procedure-exists 验证存在 + 实际调用成功）：
- gimp-version：返回 ("3.2.6") 形式的列表字符串
- gimp-get-images：返回 (#(id ...))，向量首元素为最近活动图像
- gimp-image-get-width / gimp-image-get-height / gimp-image-get-base-type
- gimp-image-get-layers：返回 (#(layer-id ...))
- gimp-item-get-name / gimp-item-get-visible / gimp-layer-get-opacity
"""

from __future__ import annotations

from gimp_client import GimpClient
from scheme import parse_kv, require_image

_BASE_TYPES = {0: "rgb", 1: "grayscale", 2: "indexed"}


def ping(client: GimpClient) -> dict:
    """检测 GIMP 连接并返回 GIMP 版本。PDB: gimp-version。"""
    body = client.eval("(gimp-version)")
    version = body.strip().strip("()").strip('"')
    return {"connected": True, "gimp_version": version}


def list_fonts(client: GimpClient, contains: str = "", limit: int = 50) -> dict:
    """列出 GIMP 已安装字体名，供 add_text 的 font 参数使用。

    GIMP 3 没有 gimp-fonts-get-name-list（实测 unbound）；
    用 gimp-fonts-get-list 取资源 ID 向量，再逐个 gimp-resource-get-name。
    contains 为大小写不敏感的子串过滤；limit 限制返回条数，
    避免把几百个字体名一次性塞给大模型。
    """
    if limit <= 0:
        raise ValueError(f"limit 必须为正: {limit}")
    body = client.eval_string(
        "(let ((v (car (gimp-fonts-get-list))))"
        "  (let loop ((i 0) (acc \"\"))"
        "    (if (= i (vector-length v)) acc"
        "        (loop (+ i 1)"
        "              (string-append acc (if (= i 0) \"\" \"\\n\")"
        "                             (car (gimp-resource-get-name (vector-ref v i))))))))"
    )
    names = [n for n in body.split("\n") if n.strip()]
    matched = [n for n in names if contains.lower() in n.lower()] if contains else names
    return {
        "total_installed": len(names),
        "matched": len(matched),
        "returned": min(limit, len(matched)),
        "fonts": matched[:limit],
    }


def get_image_info(client: GimpClient) -> dict:
    """当前活动图像的尺寸、色彩模式、图层列表（名称/可见性/不透明度）。

    图层名逐层单独查询：名称可能含 `,` `;` `|` 等任意字符（如 add_text 的文本），
    不能用分隔符拼串解析；每层返回 "visible|opacity|name"，split 限 2 次保证 name 原样保留。
    """
    img = require_image(client)
    code = f"""
(let ((img {img}))
  (let ((w (car (gimp-image-get-width img)))
        (h (car (gimp-image-get-height img)))
        (bt (car (gimp-image-get-base-type img)))
        (layers (car (gimp-image-get-layers img))))
    (let loop ((lst (vector->list layers)) (acc ""))
      (if (null? lst)
          (string-append "width=" (number->string w)
                         ";height=" (number->string h)
                         ";base_type=" (number->string bt)
                         ";layer_ids=" acc)
          (loop (cdr lst)
                (string-append acc
                  (if (string=? acc "") "" " ")
                  (number->string (car lst))))))))
""".strip()
    kv = parse_kv(client.eval_string(code))
    layer_ids = [int(x) for x in kv.get("layer_ids", "").split()]
    layers = [_get_layer_info(client, layer_id) for layer_id in layer_ids]
    return {
        "image_id": img,
        "width": int(kv["width"]),
        "height": int(kv["height"]),
        "base_type": _BASE_TYPES.get(int(kv["base_type"]), kv["base_type"]),
        "layers": layers,
    }


def _get_layer_info(client: GimpClient, layer_id: int) -> dict:
    """查询单个图层；名称置于最后，split 限 2 次使名称可含任意分隔符。"""
    body = client.eval_string(
        f"(let ((L {layer_id}))"
        "  (string-append (number->string (car (gimp-item-get-visible L))) \"|\""
        "                 (number->string (car (gimp-layer-get-opacity L))) \"|\""
        "                 (car (gimp-item-get-name L))))"
    )
    visible, opacity, name = body.split("|", 2)
    return {"name": name, "visible": visible == "1", "opacity": float(opacity)}
