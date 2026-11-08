"""GIMP MCP 服务入口（FastMCP，stdio 传输）。

用法：
    python server.py            # 以 MCP stdio 服务运行（由 MCP 客户端拉起）

前提：GIMP 3 已启动且 Script-Fu Server 正在监听 127.0.0.1:10008
（滤镜 → Development → Script-Fu → Start Server，或见 README 的命令行启动方式）。
"""

from __future__ import annotations

import json
import logging
import time
import inspect
from datetime import datetime
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from config import CONFIG, PROJECT_ROOT, Config
from gimp_client import GimpClient
from tools import adjust, connection, escape, feedback, files, geometry, layers, selection

mcp = FastMCP("gimp-mcp")

CLIENT = GimpClient(
    port=CONFIG.port,
    timeout=CONFIG.timeout_seconds,
    reconnect_retries=CONFIG.reconnect_retries,
    reconnect_interval=CONFIG.reconnect_interval_seconds,
)


_LOG_DATE: str | None = None


def _get_logger() -> logging.Logger:
    """按当前日期取日志器；跨零点后自动切到新日期的文件，而不是继续写前一天的。"""
    global _LOG_DATE
    today = f"{datetime.now():%Y%m%d}"
    logger = logging.getLogger("gimp-mcp")
    if _LOG_DATE != today:
        log_dir = PROJECT_ROOT / CONFIG.log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(
            log_dir / f"tool_calls_{today}.log", encoding="utf-8"
        )
        for old in list(logger.handlers):
            logger.removeHandler(old)
            old.close()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        _LOG_DATE = today
    return logger


def _wrap(tool_name: str, func, *args, **kwargs):
    """统一返回 {ok, result?, error?}；记录每次调用日志（脱敏，不含图像内容）。"""
    start = time.monotonic()
    # 位置参数绑定回参数名，便于排查"大模型到底发了什么"；client/config 对象不入日志
    try:
        bound = inspect.signature(func).bind(*args, **kwargs)
        call_args = {
            k: v for k, v in bound.arguments.items()
            if not isinstance(v, (GimpClient, Config))
        }
    except TypeError:
        call_args = {}
    try:
        logger = _get_logger()
    except Exception as exc:
        return {"ok": False, "error": f"无法初始化调用日志，操作未执行: {exc}"}
    try:
        response = {"ok": True, "result": func(*args, **kwargs)}
    except Exception as exc:
        response = {"ok": False, "error": str(exc)}
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), "tool": tool_name,
             "duration_ms": round((time.monotonic() - start) * 1000),
             "args": call_args, **response}
    try:
        logger.info(json.dumps(entry, ensure_ascii=False, default=str))
    except Exception as exc:
        # 记录失败不能把已完成的操作改报失败，否则客户端可能重复应用它。
        response["warning"] = f"调用日志写入失败，操作结果不变，请勿因此重试: {exc}"
    return response


# ---------- 连接与元信息 ----------

@mcp.tool()
def ping() -> dict:
    """检测 GIMP 连接是否正常，返回 GIMP 版本号。"""
    return _wrap("ping", connection.ping, CLIENT)


@mcp.tool()
def get_image_info() -> dict:
    """返回当前活动图像的尺寸、色彩模式、图层列表（名称/可见性/不透明度）。"""
    return _wrap("get_image_info", connection.get_image_info, CLIENT)


@mcp.tool()
def list_fonts(contains: str = "", limit: int = 50) -> dict:
    """列出 GIMP 已安装字体名，供 add_text 的 font 参数使用。

    contains 为大小写不敏感的子串过滤（如 "yahei"）；limit 限制返回条数（默认 50）。
    返回 total_installed / matched / returned / fonts。
    """
    return _wrap("list_fonts", connection.list_fonts, CLIENT, contains, limit)


# ---------- 文件操作 ----------

@mcp.tool()
def open_image(path: str) -> dict:
    """打开图像。path 必须在白名单目录内（默认 workspace/）。

    新打开的图像会成为后续工具的"当前图像"（本服务以 gimp-get-images 首元素为准，
    即最近创建/加载的图像，而非 GIMP 界面焦点图像；不支持在多张已打开图像间切换）。
    """
    return _wrap("open_image", files.open_image, CLIENT, CONFIG, path)


@mcp.tool()
def new_image(width: int, height: int, mode: str = "rgb") -> dict:
    """新建空白图像。mode: rgb / grayscale / indexed。"""
    return _wrap("new_image", files.new_image, CLIENT, width, height, mode)


@mcp.tool()
def export_image(path: str, format: Optional[str] = None,
                 quality: Optional[int] = None) -> dict:
    """导出当前活动图像为 png/jpg/jpeg/webp/tiff/gif/xcf。

    - format 省略时按扩展名推断；给出时须与扩展名一致
    - quality 仅对 jpeg/webp 生效，1–100
    - path 必须在白名单目录内
    """
    return _wrap("export_image", files.export_image, CLIENT, CONFIG, path, format, quality)


@mcp.tool()
def save_xcf(path: str) -> dict:
    """保存当前活动图像为 XCF 工程文件。path 必须在白名单目录内。"""
    return _wrap("save_xcf", files.save_xcf, CLIENT, CONFIG, path)


# ---------- 几何与构图 ----------

@mcp.tool()
def crop_to_rect(x: int, y: int, width: int, height: int) -> dict:
    """按像素矩形裁剪当前活动图像（x,y 为左上角）。"""
    return _wrap("crop_to_rect", geometry.crop_to_rect, CLIENT, x, y, width, height)


@mcp.tool()
def crop_to_aspect(ratio_w: float, ratio_h: float, anchor: str = "center") -> dict:
    """按宽高比裁剪（如 16:9）。anchor: center/top/bottom/left/right。"""
    return _wrap("crop_to_aspect", geometry.crop_to_aspect, CLIENT, ratio_w, ratio_h, anchor)


@mcp.tool()
def scale_image(width: Optional[int] = None, height: Optional[int] = None,
                keep_aspect: bool = True) -> dict:
    """缩放图像；只给一边时按比例推算另一边。"""
    return _wrap("scale_image", geometry.scale_image, CLIENT, width, height, keep_aspect)


@mcp.tool()
def resize_canvas(width: int, height: int, offset_x: int = 0, offset_y: int = 0) -> dict:
    """调整画布大小（不缩放图层内容），offset 为原内容在新画布中的偏移。"""
    return _wrap("resize_canvas", geometry.resize_canvas, CLIENT, width, height, offset_x, offset_y)


@mcp.tool()
def rotate_image(degrees: int) -> dict:
    """旋转图像，仅支持顺时针 90/180/270 度。"""
    return _wrap("rotate_image", geometry.rotate_image, CLIENT, degrees)


@mcp.tool()
def flip_image(direction: str = "horizontal") -> dict:
    """翻转图像。direction: horizontal / vertical。"""
    return _wrap("flip_image", geometry.flip_image, CLIENT, direction)


# ---------- 选区 ----------

@mcp.tool()
def select_all() -> dict:
    """全选当前活动图像。"""
    return _wrap("select_all", selection.select_all, CLIENT)


@mcp.tool()
def select_none() -> dict:
    """取消选区。"""
    return _wrap("select_none", selection.select_none, CLIENT)


@mcp.tool()
def select_invert() -> dict:
    """反选。"""
    return _wrap("select_invert", selection.select_invert, CLIENT)


@mcp.tool()
def select_rect(x: int, y: int, width: int, height: int) -> dict:
    """矩形选区（替换当前选区）。"""
    return _wrap("select_rect", selection.select_rect, CLIENT, x, y, width, height)


@mcp.tool()
def select_ellipse(x: int, y: int, width: int, height: int) -> dict:
    """椭圆选区（替换当前选区）。"""
    return _wrap("select_ellipse", selection.select_ellipse, CLIENT, x, y, width, height)


@mcp.tool()
def fill_selection(color: str, opacity: float = 100.0) -> dict:
    """用颜色填充当前选区（无选区时填充整个图层）。color 为 #RRGGBB，opacity 0–100。"""
    return _wrap("fill_selection", selection.fill_selection, CLIENT, color, opacity)


# ---------- 图层 ----------

@mcp.tool()
def add_layer(name: str, mode: str = "normal", opacity: float = 100.0) -> dict:
    """新建透明图层并置于顶层。mode: normal/multiply/screen/overlay/addition/subtract/difference。"""
    return _wrap("add_layer", layers.add_layer, CLIENT, name, mode, opacity)


@mcp.tool()
def remove_layer(name: str) -> dict:
    """按名称删除图层。"""
    return _wrap("remove_layer", layers.remove_layer, CLIENT, name)


@mcp.tool()
def set_active_layer(name: str) -> dict:
    """按名称设为活动图层（后续操作的作用对象）。"""
    return _wrap("set_active_layer", layers.set_active_layer, CLIENT, name)


@mcp.tool()
def duplicate_layer(name: Optional[str] = None) -> dict:
    """复制图层（默认当前活动图层），将副本放在源层同一父级、紧邻源层上方并选中。"""
    return _wrap("duplicate_layer", layers.duplicate_layer, CLIENT, name)


# ---------- 调色与滤镜 ----------

@mcp.tool()
def adjust_brightness_contrast(brightness: float, contrast: float,
                               selection_only: bool = False) -> dict:
    """亮度/对比度，范围 -100–100。selection_only=true 时仅作用于当前选区。"""
    return _wrap("adjust_brightness_contrast", adjust.adjust_brightness_contrast,
                 CLIENT, brightness, contrast, selection_only)


@mcp.tool()
def adjust_levels(channel: str = "value", input_black: float = 0,
                  input_white: float = 255, gamma: float = 1.0,
                  selection_only: bool = False) -> dict:
    """色阶。channel: value/red/green/blue/alpha；黑场/白场 0–255；gamma 0.1–10。"""
    return _wrap("adjust_levels", adjust.adjust_levels, CLIENT, channel,
                 input_black, input_white, gamma, selection_only)


@mcp.tool()
def adjust_hue_saturation(hue: float = 0, saturation: float = 0,
                          lightness: float = 0, selection_only: bool = False) -> dict:
    """色相(-180–180)/饱和度(-100–100)/明度(-100–100)。"""
    return _wrap("adjust_hue_saturation", adjust.adjust_hue_saturation, CLIENT,
                 hue, saturation, lightness, selection_only)


@mcp.tool()
def desaturate(mode: str = "luminosity", selection_only: bool = False) -> dict:
    """去色。mode: luminosity / lightness / average。"""
    return _wrap("desaturate", adjust.desaturate, CLIENT, mode, selection_only)


@mcp.tool()
def gaussian_blur(radius: float, selection_only: bool = False) -> dict:
    """高斯模糊。std-dev = radius × 0.32，沿用旧版半径约定；与 GIMP 3 UI 的 Size 尚未比对。"""
    return _wrap("gaussian_blur", adjust.gaussian_blur, CLIENT, radius, selection_only)


@mcp.tool()
def unsharp_mask(radius: float, amount: float, threshold: float = 0.0,
                 selection_only: bool = False) -> dict:
    """USM 锐化。"""
    return _wrap("unsharp_mask", adjust.unsharp_mask, CLIENT, radius, amount,
                 threshold, selection_only)


@mcp.tool()
def add_text(text: str, font: str = "Sans-serif", size: float = 32,
             color: str = "#ffffff", position_x: Optional[float] = None,
             position_y: Optional[float] = None, anchor: Optional[str] = None,
             margin: float = 10) -> dict:
    """添加文字图层。

    - position_x/position_y 同时给出时按坐标放置（左上角）
    - 否则按 anchor 定位: top-left/top-right/bottom-left/bottom-right/center（默认 top-left），margin 为边距
    - color 为 #RRGGBB；font 须为 GIMP 已安装字体名（默认 Sans-serif）
    """
    position = None
    if position_x is not None and position_y is not None:
        position = (position_x, position_y)
    return _wrap("add_text", adjust.add_text, CLIENT, text, font, size, color,
                 position, anchor, margin)


# ---------- 反馈回路 ----------

@mcp.tool()
def export_preview(path: Optional[str] = None, max_side: Optional[int] = None) -> dict:
    """导出当前活动图像的降采样预览，返回文件路径（供多模态大模型看图验收）。

    max_side 省略时取 config.json 的 preview_max_side（默认 1024）。
    path 省略时生成 .jpg；显式给 path 时按扩展名选 JPEG 或 PNG。
    """
    return _wrap("export_preview", feedback.export_preview, CLIENT, CONFIG, path,
                 max_side if max_side is not None else CONFIG.preview_max_side)


@mcp.tool()
def get_histogram_stats(channel: str = "value") -> dict:
    """当前活动图层的直方图统计：均值/中位数/标准差/黑场占比/白场占比（0–255 口径）。

    channel: value/red/green/blue/alpha/luminosity。用于不依赖视觉的数值反馈闭环，
    例如"调亮一点"后比较 mean 是否上升。
    """
    return _wrap("get_histogram_stats", feedback.get_histogram_stats, CLIENT, channel)


# ---------- 万能出口（默认关闭） ----------

@mcp.tool()
def run_scriptfu(code: str) -> dict:
    """直接执行任意 Script-Fu 代码。安全开关控制，默认关闭（config.json 的
    enable_scriptfu_escape_hatch）。开启等价于允许 AI 执行任意 Scheme 代码。"""
    return _wrap("run_scriptfu", escape.run_scriptfu, CLIENT, CONFIG, code)


if __name__ == "__main__":
    mcp.run()
