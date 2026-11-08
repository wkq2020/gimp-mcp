"""端到端验收：以真实 MCP 客户端（stdio）驱动 gimp-mcp 服务，模拟自然语言任务链。

任务链（对应任务书第 10 节）：
  "打开 workspace/photo.jpg，裁剪成 16:9，调亮一点，右下角加白色文字水印 ©2026，
   导出为 workspace/photo_final.webp"
验收点：最终文件存在、尺寸为 16:9、直方图均值相比原图提升、含文字图层、格式为 webp。
另验收：ping 返回版本、export_preview 可读、安全用例、调用日志。

运行前提：GIMP Script-Fu Server 已在 127.0.0.1:10008 监听。
用法: python scripts/e2e_acceptance.py
"""

import asyncio
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
WORKSPACE = ROOT / "workspace"

PASSED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    PASSED.append((name, cond))
    print(f"[{status}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        raise AssertionError(f"验收失败: {name}")


async def call(session: ClientSession, tool: str, **args) -> dict:
    result = await session.call_tool(tool, args)
    assert not result.isError, f"{tool} MCP 层错误: {result.content}"
    payload = json.loads(result.content[0].text)
    return payload


async def call_ok(session: ClientSession, tool: str, **args) -> dict:
    payload = await call(session, tool, **args)
    assert payload["ok"], f"{tool} 返回错误: {payload.get('error')}"
    return payload["result"]


def prepare_photo() -> Path:
    """生成验收用样例图 workspace/photo.jpg（渐变+色块，直方图有层次）。"""
    from PIL import Image, ImageDraw

    photo = WORKSPACE / "photo.jpg"
    img = Image.new("RGB", (1920, 1080))
    draw = ImageDraw.Draw(img)
    for x in range(0, 1920, 4):
        gray = int(200 * x / 1920)
        draw.rectangle([x, 0, x + 3, 1080], fill=(gray, gray, gray))
    draw.rectangle([100, 100, 500, 400], fill=(160, 50, 50))
    draw.ellipse([900, 300, 1300, 700], fill=(50, 50, 160))
    img.save(photo, quality=90)
    return photo


async def _run() -> None:
    photo = prepare_photo()
    final = WORKSPACE / "photo_final.webp"
    final.unlink(missing_ok=True)

    params = StdioServerParameters(command=str(PYTHON), args=[str(ROOT / "server.py")],
                                   cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            print(f"已连接 MCP 服务，注册工具 {len(tool_names)} 个: {sorted(tool_names)}\n")

            # 验收 1：ping 返回 GIMP 版本
            ping = await call_ok(session, "ping")
            check("ping 返回 GIMP 版本", ping["gimp_version"].startswith("3."),
                  f"version={ping['gimp_version']}")

            # 验收 5a：安全用例——白名单外路径被拒绝
            denied = await call(session, "open_image", path=r"C:\Windows\notepad.exe")
            check("白名单外路径被拒绝", not denied["ok"] and "白名单" in denied["error"])

            # 验收 5b：run_scriptfu 默认关闭
            esc = await call(session, "run_scriptfu", code="(+ 1 2)")
            check("run_scriptfu 默认关闭并返回明确错误",
                  not esc["ok"] and "安全开关" in esc["error"])

            # ---- 任务链开始 ----
            opened = await call_ok(session, "open_image", path="workspace/photo.jpg")
            check("打开 photo.jpg", opened["image_id"] > 0)

            before = await call_ok(session, "get_histogram_stats", channel="value")

            cropped = await call_ok(session, "crop_to_aspect", ratio_w=16, ratio_h=9)
            check("裁剪为 16:9", abs(cropped["width"] / cropped["height"] - 16 / 9) < 0.01,
                  f"{cropped['width']}x{cropped['height']}")

            await call_ok(session, "adjust_brightness_contrast", brightness=30, contrast=0)
            after = await call_ok(session, "get_histogram_stats", channel="value")
            check("调亮后直方图均值提升", after["mean"] > before["mean"],
                  f"{before['mean']} -> {after['mean']}")

            text = await call_ok(session, "add_text", text="©2026", color="#ffffff",
                                 anchor="bottom-right")
            check("右下角白色文字水印", text["layer_id"] > 0)

            info = await call_ok(session, "get_image_info")
            check("图像含文字图层", any(l["name"] == "©2026" for l in info["layers"]))

            exported = await call_ok(session, "export_image",
                                     path="workspace/photo_final.webp")
            check("导出 photo_final.webp", final.is_file() and exported["format"] == "webp",
                  f"{exported['size_bytes']} bytes")

            # 验收 3 补充：最终文件尺寸确为 16:9（用 Pillow 独立验证，不信 GIMP 自报）
            from PIL import Image

            with Image.open(final) as im:
                check("最终文件格式为 webp", im.format == "WEBP")
                check("最终文件尺寸为 16:9", abs(im.width / im.height - 16 / 9) < 0.01,
                      f"{im.width}x{im.height}")

            # 验收 4：视觉反馈链路
            preview = await call_ok(session, "export_preview")
            p = Path(preview["path"])
            check("export_preview 预览图可被读取", p.is_file() and p.stat().st_size > 0,
                  str(p))

    # 验收：调用日志已记录
    log_files = sorted((ROOT / "logs").glob("tool_calls_*.log"))
    ok = False
    if log_files:
        content = log_files[-1].read_text(encoding="utf-8")
        ok = '"tool": "ping"' in content and '"tool": "export_image"' in content
    check("logs/ 下记录了工具调用日志", ok)

    print("全部验收点通过 ✅")


def _print_summary() -> None:
    failed = [n for n, c in PASSED if not c]
    print(f"\n端到端验收: {len(PASSED) - len(failed)}/{len(PASSED)} 通过")
    if failed:
        print("未通过:", ", ".join(failed))


async def main() -> None:
    # check() 保持 fail-fast（任务链各步有依赖），但无论成败都输出已完成的验收汇总
    try:
        await _run()
    finally:
        _print_summary()


if __name__ == "__main__":
    asyncio.run(main())
