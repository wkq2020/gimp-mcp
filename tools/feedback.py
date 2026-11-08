"""反馈回路工具：预览图导出 + 直方图统计。

PDB 依据（GIMP 3.2.6 实测）：
- gimp-image-duplicate / gimp-image-scale / gimp-image-flatten / file-jpeg-export / gimp-image-delete
- gimp-drawable-histogram：(drawable channel start end) → (mean std-dev median pixels count percentile)，
  mean/median/std-dev 原生即为 0–255 量纲（实测：128 灰底图 mean=128.0），percentile 为 0–1 比例
- 黑场/白场占比 = 窄区间 histogram 的 count / 全区间 pixels
"""

from __future__ import annotations

import time
from pathlib import Path

from config import CONFIG, Config
from gimp_client import GimpClient, ScriptFuError
from scheme import esc, parse_kv, require_image, selected_drawable_expr

_HIST_CHANNELS = {"value": 0, "red": 1, "green": 2, "blue": 3, "alpha": 4, "luminosity": 5}


def _preview_dir(cfg: Config) -> Path:
    d = cfg.check_path_allowed(cfg.resolve_allowed_dirs()[0] / ".previews")
    d.mkdir(parents=True, exist_ok=True)
    return d


def export_preview(client: GimpClient, cfg: Config = CONFIG, path: str | None = None,
                   max_side: int = 1024) -> dict:
    """导出当前活动图像的降采样预览，返回文件路径（供多模态大模型看图验收）。

    - path 省略时写入 <白名单首目录>/.previews/preview_<图像ID>_<时间戳>.jpg
    - 最长边缩放到 max_side 以内（原图更小则不放大）
    - 按扩展名选导出器：.jpg/.jpeg 走 JPEG，.png 走 PNG
    - 无论成败都删除临时副本图像，不会在 GIMP 里留下多余图像
    """
    if max_side <= 0:
        raise ValueError(f"max_side 必须为正: {max_side}")
    img = require_image(client)
    if path is not None:
        target = cfg.check_path_allowed(path)
    else:
        target = cfg.check_path_allowed(_preview_dir(cfg) / f"preview_{img}_{time.time_ns()}.jpg")
    cfg.check_export_extension(target)
    suffix = target.suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png"):
        raise ValueError("预览图仅支持 jpg/png")
    target_scheme = esc(str(target).replace("\\", "/"))

    kv = parse_kv(client.eval_string(
        f'(string-append "w=" (number->string (car (gimp-image-get-width {img})))'
        f' ";h=" (number->string (car (gimp-image-get-height {img}))))'
    ))
    w, h = int(kv["w"]), int(kv["h"])
    scale = min(1.0, max_side / max(w, h))
    new_w = max(1, int(w * scale + 0.5))
    new_h = max(1, int(h * scale + 0.5))

    before_mtime = target.stat().st_mtime_ns if target.exists() else None
    dup = int(client.eval_string(
        f"(number->string (car (gimp-image-duplicate {img})))"
    ))
    try:
        if scale < 1.0:
            client.eval(f"(gimp-image-scale {dup} {new_w} {new_h})")
        client.eval(f"(gimp-image-flatten {dup})")
        if suffix == ".png":
            client.eval(f"(file-png-export 1 {dup} {target_scheme} 0 FALSE 9 TRUE FALSE TRUE TRUE)")
        else:
            client.eval(f"(file-jpeg-export 1 {dup} {target_scheme} 0 0.85)")
    finally:
        # 失败也必须删副本：副本会排到 gimp-get-images 首位，
        # 留着它，后续 require_image 会全部落到这张临时图像上
        try:
            client.eval(f"(gimp-image-delete {dup})")
        except Exception:
            pass

    if not target.is_file():
        raise ScriptFuError(f"GIMP 报告成功但预览文件未出现: {target}")
    if before_mtime is not None and target.stat().st_mtime_ns == before_mtime:
        raise ScriptFuError(f"GIMP 报告成功但预览文件未更新: {target}")
    return {"path": str(target), "width": new_w, "height": new_h,
            "size_bytes": target.stat().st_size, "source_image_id": img}


def get_histogram_stats(client: GimpClient, channel: str = "value") -> dict:
    """当前活动图层的直方图统计（数值反馈回路）。PDB: gimp-drawable-histogram。

    返回 mean/median/std_dev（0–255 口径）、黑场占比（0–2% 区间像素占比）、
    白场占比（98–100% 区间像素占比）。channel: value/red/green/blue/alpha/luminosity。
    """
    ch = _HIST_CHANNELS.get(channel.lower())
    if ch is None:
        raise ValueError(f"不支持的通道: {channel}（可选 {', '.join(_HIST_CHANNELS)}）")
    img = require_image(client)
    code = f"""
(let ((drawable {selected_drawable_expr(img)}))
  (let ((full (gimp-drawable-histogram drawable {ch} 0.0 1.0))
        (black (gimp-drawable-histogram drawable {ch} 0.0 0.02))
        (white (gimp-drawable-histogram drawable {ch} 0.98 1.0)))
    (string-append
      "mean=" (number->string (list-ref full 0))
      ";std_dev=" (number->string (list-ref full 1))
      ";median=" (number->string (list-ref full 2))
      ";pixels=" (number->string (list-ref full 3))
      ";black_pct=" (number->string (* 100 (/ (list-ref black 4) (max 1 (list-ref full 3)))))
      ";white_pct=" (number->string (* 100 (/ (list-ref white 4) (max 1 (list-ref full 3))))))))
""".strip()
    kv = parse_kv(client.eval_string(code))
    return {
        "channel": channel,
        "mean": round(float(kv["mean"]), 2),
        "median": round(float(kv["median"]), 2),
        "std_dev": round(float(kv["std_dev"]), 2),
        "pixels": int(float(kv["pixels"])),
        "black_point_pct": round(float(kv["black_pct"]), 2),
        "white_point_pct": round(float(kv["white_pct"]), 2),
    }
