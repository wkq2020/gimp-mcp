"""冒烟脚本：直接调用工具函数（绕过 MCP），需 Script-Fu Server 在线。

用法: python scripts/smoke.py [步骤名...]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CONFIG
from gimp_client import GimpClient
from tools import adjust, connection, escape, feedback, files, geometry, layers, selection


def main() -> None:
    client = GimpClient(port=CONFIG.port, timeout=CONFIG.timeout_seconds)
    all_steps = ["ping", "new", "info", "export", "open", "savexcf", "security",
                 "geometry", "selection", "layers", "adjust", "feedback", "escape"]
    steps = sys.argv[1:] or all_steps

    if "ping" in steps:
        print("ping:", connection.ping(client))
    if "new" in steps:
        print("new_image:", files.new_image(client, 320, 180, "rgb"))
    if "info" in steps:
        print("get_image_info:", connection.get_image_info(client))
    if "export" in steps:
        print("export png:", files.export_image(client, CONFIG, "workspace/smoke.png"))
        print("export webp q80:", files.export_image(client, CONFIG, "workspace/smoke.webp", quality=80))
        print("export jpg:", files.export_image(client, CONFIG, "workspace/smoke.jpg", format="jpeg"))
    if "open" in steps:
        print("open_image:", files.open_image(client, CONFIG, "workspace/smoke.png"))
        print("info after open:", connection.get_image_info(client))
    if "savexcf" in steps:
        print("save_xcf:", files.save_xcf(client, CONFIG, "workspace/smoke.xcf"))
    if "security" in steps:
        try:
            files.open_image(client, CONFIG, r"C:\Windows\notepad.exe")
            print("安全用例失败：白名单外路径未被拒绝")
        except PermissionError as e:
            print("白名单拒绝 OK:", e)
        try:
            files.export_image(client, CONFIG, "workspace/evil.exe")
            print("安全用例失败：非法扩展名未被拒绝")
        except ValueError as e:
            print("扩展名拒绝 OK:", e)
        try:
            files.export_image(client, CONFIG, "workspace/a.png", format="webp")
            print("安全用例失败：format 与扩展名不一致未被发现")
        except ValueError as e:
            print("format 校验 OK:", e)

    if "geometry" in steps:
        files.new_image(client, 400, 300, "rgb")
        print("crop_to_rect:", geometry.crop_to_rect(client, 10, 20, 300, 200))
        print("crop_to_aspect 16:9:", geometry.crop_to_aspect(client, 16, 9))
        try:
            geometry.crop_to_rect(client, 0, 0, 9999, 9999)
            print("越界裁剪用例失败：未报错")
        except ValueError as e:
            print("越界裁剪拒绝 OK:", e)
        print("scale_image:", geometry.scale_image(client, width=160))
        print("resize_canvas:", geometry.resize_canvas(client, 200, 120, 5, 5))
        print("rotate_image:", geometry.rotate_image(client, 90))
        print("flip_image:", geometry.flip_image(client, "vertical"))
    if "selection" in steps:
        files.new_image(client, 200, 100, "rgb")
        print("select_all:", selection.select_all(client))
        print("select_rect:", selection.select_rect(client, 10, 10, 50, 40))
        print("fill_selection:", selection.fill_selection(client, "#ff0000", 80))
        print("select_ellipse:", selection.select_ellipse(client, 0, 0, 60, 60))
        print("select_invert:", selection.select_invert(client))
        print("select_none:", selection.select_none(client))
        try:
            selection.fill_selection(client, "红色")
            print("非法颜色用例失败：未报错")
        except ValueError as e:
            print("非法颜色拒绝 OK:", e)
    if "layers" in steps:
        files.new_image(client, 200, 100, "rgb")
        print("add_layer:", layers.add_layer(client, "图层甲", "multiply", 60))
        dup = layers.duplicate_layer(client, "图层甲")
        print("duplicate_layer:", dup)
        print("set_active_layer:", layers.set_active_layer(client, "图层甲"))
        print("remove_layer:", layers.remove_layer(client, dup["new_layer_name"]))
        try:
            layers.remove_layer(client, "不存在的图层")
            print("缺失图层用例失败：未报错")
        except Exception as e:
            print("缺失图层报错 OK:", e)
        print("info:", connection.get_image_info(client))

    if "adjust" in steps:
        files.new_image(client, 200, 100, "rgb")
        selection.fill_selection(client, "#808080")  # 灰底，亮度才有提升空间
        before = feedback.get_histogram_stats(client)
        print("直方图(灰底):", before)
        print("brightness:", adjust.adjust_brightness_contrast(client, 30, 10))
        after = feedback.get_histogram_stats(client)
        print("直方图(调亮后):", after, "均值提升:", after["mean"] > before["mean"])
        print("levels:", adjust.adjust_levels(client, gamma=1.2))
        print("hue_sat:", adjust.adjust_hue_saturation(client, hue=10, saturation=20))
        print("desaturate:", adjust.desaturate(client, "luminosity"))
        print("gaussian:", adjust.gaussian_blur(client, 5))
        print("unsharp:", adjust.unsharp_mask(client, 2.0, 0.5, 0.0))
        print("add_text 右下角:", adjust.add_text(client, "©2026", color="#ffffff", anchor="bottom-right"))
        print("add_text 指定坐标:", adjust.add_text(client, "位置测试", position=(5, 5), color="#ff0000"))
        # selection_only 流程
        selection.select_rect(client, 0, 0, 50, 50)
        print("blur selection_only:", adjust.gaussian_blur(client, 8, selection_only=True))
        selection.select_none(client)
        try:
            adjust.gaussian_blur(client, 8, selection_only=True)
            print("无选区 selection_only 用例失败：未报错")
        except Exception as e:
            print("无选区 selection_only 报错 OK:", e)
        info = connection.get_image_info(client)
        print("图层清单:", [l["name"] for l in info["layers"]])
        try:
            adjust.adjust_brightness_contrast(client, 200, 0)
            print("越界亮度用例失败：未报错")
        except ValueError as e:
            print("越界亮度拒绝 OK:", e)
    if "feedback" in steps:
        files.new_image(client, 3000, 2000, "rgb")
        print("export_preview:", feedback.export_preview(client))
        print("histogram:", feedback.get_histogram_stats(client, "value"))
    if "escape" in steps:
        try:
            escape.run_scriptfu(client, CONFIG, "(+ 1 2)")
            print("escape 用例失败：默认关闭却执行了")
        except PermissionError as e:
            print("escape 默认关闭 OK:", str(e)[:60], "...")

    client.close()


if __name__ == "__main__":
    main()
