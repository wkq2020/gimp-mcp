"""文件操作工具。

PDB 依据（GIMP 3.2.6 实测调用成功，探针见 scripts/probe_fileops.py / probe_solve_export.py）：
- gimp-file-load：(run-mode path path) 3 参即可，返回 (image-id)
- gimp-image-new：(width height base-type) 返回 (image-id)；新建图像无图层
- gimp-layer-new：GIMP 3 签名为 (image name width height type opacity mode)（name 在第 2 位）
- gimp-image-insert-layer：(image layer parent position)
- gimp-file-save：(run-mode image path) 3 参
- file-png-export：(run-mode image path options interlaced compression bkgd offs phys time)
- file-jpeg-export：(run-mode image path options quality)，quality 0.0–1.0
- file-webp-export：(run-mode image path options preset lossless quality)，quality 0–100
- file-tiff-export / file-gif-export：(run-mode image path) 即可
"""

from __future__ import annotations

from pathlib import Path

from config import Config
from gimp_client import GimpClient, ScriptFuError
from scheme import esc, num, require_image

_MODE_MAP = {
    "rgb": ("RGB", "RGB-IMAGE"),
    "grayscale": ("GRAY", "GRAY-IMAGE"),
    "gray": ("GRAY", "GRAY-IMAGE"),
    "indexed": ("RGB", "RGB-IMAGE"),
}

_EXPORT_FUNCS = {
    "png": "file-png-export",
    "jpg": "file-jpeg-export",
    "jpeg": "file-jpeg-export",
    "webp": "file-webp-export",
    "tiff": "file-tiff-export",
    "gif": "file-gif-export",
}

_FORMAT_EXT_EQUIV = {"jpg": {"jpg", "jpeg"}, "jpeg": {"jpg", "jpeg"}}


def _posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def open_image(client: GimpClient, cfg: Config, path: str) -> dict:
    """打开图像；路径必须在白名单目录内。PDB: gimp-file-load。

    新加载的图像会排到 gimp-get-images 首位，因此随后各工具的"当前图像"就是它。
    注意：本服务的"当前图像"一律指 gimp-get-images 首元素（最近创建/加载的图像），
    不是 GIMP 界面里焦点所在的那张；目前也不支持在多张已打开图像之间切换。
    """
    p = cfg.check_path_allowed(path)
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在: {p}")
    body = client.eval(f"(gimp-file-load 1 {esc(_posix(p))} {esc(_posix(p))})")
    image_id = int(body.strip().strip("()"))
    return {"image_id": image_id, "path": str(p)}


def new_image(client: GimpClient, width: int, height: int, mode: str = "rgb") -> dict:
    """新建空白图像（自动创建一个白色背景图层）。PDB: gimp-image-new + gimp-layer-new + gimp-image-insert-layer。"""
    if width <= 0 or height <= 0:
        raise ValueError(f"宽高必须为正整数: {width}x{height}")
    base, layer_type = _MODE_MAP.get(mode.lower(), (None, None))
    if base is None:
        raise ValueError(f"不支持的模式: {mode}（可选 rgb / grayscale / indexed）")
    # 直接新建 INDEXED 没有调色板；从已填充的 RGB 转换才能保证白底可导出。
    convert = '(gimp-image-convert-indexed img 0 0 256 FALSE FALSE "")' if mode.lower() == "indexed" else ""
    code = f"""
(let ((img (car (gimp-image-new {num(width)} {num(height)} {base}))))
  (let ((layer (car (gimp-layer-new img "Background" {num(width)} {num(height)} {layer_type} 100 LAYER-MODE-NORMAL))))
    (gimp-image-insert-layer img layer -1 0)
    (gimp-image-set-selected-layers img (vector layer))
    (gimp-drawable-fill layer FILL-WHITE)
    {convert}
    (number->string img)))
""".strip()
    image_id = int(client.eval_string(code))
    return {"image_id": image_id, "width": width, "height": height, "mode": mode}


def export_image(
    client: GimpClient,
    cfg: Config,
    path: str,
    format: str | None = None,
    quality: int | None = None,
) -> dict:
    """导出当前活动图像。PDB: file-png-export / file-jpeg-export / file-webp-export / file-tiff-export / file-gif-export。

    - format 省略时按扩展名推断；给出时校验与扩展名一致（jpg/jpeg 视为同族）。
    - quality 仅对 jpeg/webp 生效，取值 1–100；JPEG 映射为 0–1，WebP 保持 0–100。
    - 扩展名为 xcf 时等价于 save_xcf。
    - JPEG 等不支持透明的格式由 GIMP 自动展平，调用方无需先 flatten；
      实测透明区域导出为白色。
    """
    p = cfg.check_path_allowed(path)
    ext = cfg.check_export_extension(p)
    if format:
        fmt = format.lower().lstrip(".")
        equiv = _FORMAT_EXT_EQUIV.get(fmt, {fmt})
        if ext not in equiv:
            raise ValueError(f"format={format} 与扩展名 .{ext} 不一致")
    if quality is not None and not (1 <= quality <= 100):
        raise ValueError(f"quality 须在 1–100 之间: {quality}")
    if quality is not None and ext not in ("jpg", "jpeg", "webp"):
        raise ValueError(f"quality 仅对 jpeg/webp 生效，当前格式为 {ext}（请省略 quality 参数）")
    if ext == "xcf":
        return save_xcf(client, cfg, path)
    func = _EXPORT_FUNCS.get(ext)
    if func is None:
        raise ValueError(
            f"扩展名 .{ext} 没有对应的导出实现"
            f"（支持: {', '.join(sorted(_EXPORT_FUNCS))} 与 xcf）；"
            f"请检查 config.json 的 allowed_export_extensions 是否多配了未实现的格式"
        )
    img = require_image(client)
    before_mtime = p.stat().st_mtime_ns if p.exists() else None
    target = esc(_posix(p))
    if func == "file-png-export":
        call = f"({func} 1 {img} {target} 0 FALSE 9 TRUE FALSE TRUE TRUE)"
    elif func == "file-jpeg-export" and quality is not None:
        call = f"({func} 1 {img} {target} 0 {num(quality / 100)})"
    elif func == "file-webp-export" and quality is not None:
        call = f'({func} 1 {img} {target} 0 "default" FALSE {num(quality)})'
    else:
        call = f"({func} 1 {img} {target})"
    client.eval(call)
    if not p.is_file():
        raise ScriptFuError(f"GIMP 报告成功但导出文件未出现: {p}")
    if before_mtime is not None and p.stat().st_mtime_ns == before_mtime:
        raise ScriptFuError(f"GIMP 报告成功但导出文件未更新: {p}")
    return {"path": str(p), "format": ext, "size_bytes": p.stat().st_size}


def save_xcf(client: GimpClient, cfg: Config, path: str) -> dict:
    """保存为 XCF 工程文件。PDB: gimp-file-save。"""
    p = cfg.check_path_allowed(path)
    if p.suffix.lower() != ".xcf":
        raise ValueError(f"save_xcf 要求 .xcf 扩展名: {p.name}")
    cfg.check_export_extension(p)
    img = require_image(client)
    before_mtime = p.stat().st_mtime_ns if p.exists() else None
    client.eval(f"(gimp-file-save 1 {img} {esc(_posix(p))})")
    if not p.is_file():
        raise ScriptFuError(f"GIMP 报告成功但文件未出现: {p}")
    if before_mtime is not None and p.stat().st_mtime_ns == before_mtime:
        raise ScriptFuError(f"GIMP 报告成功但文件未更新: {p}")
    return {"path": str(p), "format": "xcf", "size_bytes": p.stat().st_size}
