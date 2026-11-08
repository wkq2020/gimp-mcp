"""live 集成测试：自动启动隔离的 GIMP 3 + Script-Fu Server。

运行：pytest -m live
每个工具至少一个 happy path 用例 + 一个错误用例。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import CONFIG
from gimp_client import ScriptFuError
from scheme import require_image
from tools import adjust, connection, escape, feedback, files, geometry, layers, selection

pytestmark = pytest.mark.live

OUT = Path("workspace/test_outputs")


def _layer_mean(client, image_id: int, name: str) -> float:
    """按图层名取 VALUE 通道均值，用于断言"到底哪一层被改了"。"""
    lid = layers._find_layer(client, image_id, name)
    return float(client.eval_string(
        f"(number->string (list-ref (gimp-drawable-histogram {lid} 0 0.0 1.0) 0))"))


def _image_count(client) -> int:
    return int(client.eval_string(
        "(number->string (vector-length (car (gimp-get-images))))"))


@pytest.fixture(autouse=True)
def _outputs_dir(tmp_path, monkeypatch, image_scope):
    monkeypatch.setitem(globals(), "OUT", tmp_path)
    monkeypatch.setattr(CONFIG, "allowed_dirs", [str(tmp_path)])
    monkeypatch.setattr(CONFIG, "allowed_export_extensions", ["png", "jpg", "jpeg", "webp", "tiff", "gif", "xcf"])


# ---------- 连接与元信息 ----------

class TestConnection:
    def test_ping_returns_version(self, live_client):
        info = connection.ping(live_client)
        assert info["connected"] is True
        assert info["gimp_version"].count(".") == 2

    def test_get_image_info(self, fresh_image):
        client, img = fresh_image
        info = connection.get_image_info(client)
        assert info["width"] == 320 and info["height"] == 180
        assert info["base_type"] == "rgb"
        assert len(info["layers"]) == 1
        assert info["layers"][0]["visible"] is True

    def test_get_image_info_no_image(self, live_client):
        with pytest.raises(ScriptFuError, match="没有打开的图像"):
            connection.get_image_info(live_client)


# ---------- 文件操作 ----------

class TestFiles:
    def test_open_image(self, live_client, fixtures_dir):
        # 白名单仅放行 workspace/，先把样例图复制进去（符合安全设计）
        import shutil

        target = OUT / "photo.jpg"
        shutil.copy(fixtures_dir / "photo.jpg", target)
        result = files.open_image(live_client, CONFIG, str(target))
        assert result["image_id"] > 0
        info = connection.get_image_info(live_client)
        assert info["width"] == 1920 and info["height"] == 1080

    def test_open_image_outside_whitelist(self, live_client):
        with pytest.raises(PermissionError):
            files.open_image(live_client, CONFIG, r"C:\Windows\notepad.exe")

    def test_open_image_not_found(self, live_client):
        with pytest.raises(FileNotFoundError):
            files.open_image(live_client, CONFIG, str(OUT / "不存在的文件.png"))

    def test_new_image(self, live_client):
        result = files.new_image(live_client, 100, 50, "rgb")
        assert result["width"] == 100

    def test_new_image_bad_mode(self, live_client):
        with pytest.raises(ValueError):
            files.new_image(live_client, 100, 50, "cmyk")

    def test_export_and_reload(self, fresh_image, live_client):
        client, _ = fresh_image
        selection.fill_selection(client, "#336699")
        target = OUT / "导出测试.webp"
        result = files.export_image(client, CONFIG, str(target), quality=80)
        assert result["format"] == "webp"
        assert target.is_file() and target.stat().st_size > 0
        reloaded = files.open_image(client, CONFIG, str(target))
        assert reloaded["image_id"] > 0

    def test_export_bad_extension(self, fresh_image):
        client, _ = fresh_image
        with pytest.raises(ValueError):
            files.export_image(client, CONFIG, str(OUT / "x.exe"))

    def test_export_format_mismatch(self, fresh_image):
        client, _ = fresh_image
        with pytest.raises(ValueError, match="不一致"):
            files.export_image(client, CONFIG, str(OUT / "x.png"), format="webp")

    def test_save_xcf(self, fresh_image):
        client, _ = fresh_image
        target = OUT / "工程.xcf"
        result = files.save_xcf(client, CONFIG, str(target))
        assert target.is_file()
        assert result["format"] == "xcf"


# ---------- 几何 ----------

class TestGeometry:
    def test_crop_to_rect(self, fresh_image):
        client, _ = fresh_image
        result = geometry.crop_to_rect(client, 10, 10, 200, 100)
        assert result["width"] == 200
        assert connection.get_image_info(client)["width"] == 200

    def test_crop_out_of_bounds(self, fresh_image):
        client, _ = fresh_image
        with pytest.raises(ValueError, match="超出图像范围"):
            geometry.crop_to_rect(client, 0, 0, 9999, 9999)

    def test_crop_to_aspect_16_9(self, fresh_image):
        client, _ = fresh_image
        result = geometry.crop_to_aspect(client, 16, 9)
        assert abs(result["width"] / result["height"] - 16 / 9) < 0.01

    def test_scale_keep_aspect(self, fresh_image):
        client, _ = fresh_image
        result = geometry.scale_image(client, width=160)
        assert result["height"] == 90

    def test_scale_requires_one_side(self, fresh_image):
        client, _ = fresh_image
        with pytest.raises(ValueError):
            geometry.scale_image(client)

    def test_resize_canvas(self, fresh_image):
        client, _ = fresh_image
        result = geometry.resize_canvas(client, 400, 300, 5, 5)
        assert result["width"] == 400

    def test_rotate(self, fresh_image):
        client, _ = fresh_image
        geometry.rotate_image(client, 90)
        info = connection.get_image_info(client)
        assert info["width"] == 180 and info["height"] == 320

    def test_rotate_bad_degrees(self, fresh_image):
        client, _ = fresh_image
        with pytest.raises(ValueError):
            geometry.rotate_image(client, 45)

    def test_flip(self, fresh_image):
        client, _ = fresh_image
        assert geometry.flip_image(client, "vertical")["flipped"] == "vertical"


# ---------- 选区 ----------

class TestSelection:
    def test_rect_and_fill(self, fresh_image):
        client, _ = fresh_image
        selection.select_rect(client, 0, 0, 50, 50)
        result = selection.fill_selection(client, "#ff0000")
        assert result["filled"] == "#ff0000"

    def test_fill_bad_color(self, fresh_image):
        client, _ = fresh_image
        with pytest.raises(ValueError):
            selection.fill_selection(client, "红色")

    def test_all_none_invert_ellipse(self, fresh_image):
        client, _ = fresh_image
        selection.select_all(client)
        selection.select_invert(client)
        selection.select_none(client)
        result = selection.select_ellipse(client, 0, 0, 60, 60)
        assert result["selection"] == "ellipse"


# ---------- 图层 ----------

class TestLayers:
    def test_add_and_activate(self, fresh_image):
        client, _ = fresh_image
        added = layers.add_layer(client, "测试层", "multiply", 60)
        assert added["name"] == "测试层"
        layers.set_active_layer(client, "测试层")
        info = connection.get_image_info(client)
        assert info["layers"][0]["name"] == "测试层"
        assert info["layers"][0]["opacity"] == 60.0

    def test_remove_missing_layer(self, fresh_image):
        client, _ = fresh_image
        with pytest.raises(ScriptFuError, match="图层不存在"):
            layers.remove_layer(client, "不存在")

    def test_duplicate(self, fresh_image):
        client, _ = fresh_image
        layers.add_layer(client, "原始层")
        result = layers.duplicate_layer(client, "原始层")
        assert result["new_layer_name"]
        info = connection.get_image_info(client)
        assert len(info["layers"]) == 3

    def test_add_layer_bad_mode(self, fresh_image):
        client, _ = fresh_image
        with pytest.raises(ValueError):
            layers.add_layer(client, "x", mode="发光")


# ---------- 调色与滤镜 ----------

class TestAdjust:
    def test_brightness_raises_mean(self, fresh_image):
        client, _ = fresh_image
        selection.fill_selection(client, "#808080")
        before = feedback.get_histogram_stats(client)["mean"]
        adjust.adjust_brightness_contrast(client, 30, 0)
        after = feedback.get_histogram_stats(client)["mean"]
        assert after > before

    def test_brightness_out_of_range(self, fresh_image):
        client, _ = fresh_image
        with pytest.raises(ValueError):
            adjust.adjust_brightness_contrast(client, 200, 0)

    def test_levels_gamma(self, fresh_image):
        client, _ = fresh_image
        selection.fill_selection(client, "#808080")
        result = adjust.adjust_levels(client, gamma=1.5)
        assert result["gamma"] == 1.5

    def test_levels_bad_range(self, fresh_image):
        client, _ = fresh_image
        with pytest.raises(ValueError):
            adjust.adjust_levels(client, input_black=200, input_white=100)

    def test_hue_saturation(self, fresh_image):
        client, _ = fresh_image
        result = adjust.adjust_hue_saturation(client, hue=15, saturation=30)
        assert result["saturation"] == 30

    def test_desaturate(self, fresh_image):
        client, _ = fresh_image
        result = adjust.desaturate(client, "luminosity")
        assert result["mode"] == "luminosity"

    def test_gaussian_blur(self, fresh_image):
        client, _ = fresh_image
        result = adjust.gaussian_blur(client, 5)
        assert result["std_dev"] == pytest.approx(1.6)

    def test_unsharp_mask(self, fresh_image):
        client, _ = fresh_image
        result = adjust.unsharp_mask(client, 2.0, 0.5)
        assert result["amount"] == 0.5

    def test_selection_only_blur(self, fresh_image):
        client, _ = fresh_image
        selection.select_rect(client, 0, 0, 60, 60)
        result = adjust.gaussian_blur(client, 8, selection_only=True)
        assert result["selection_only"] is True
        info = connection.get_image_info(client)
        assert len(info["layers"]) == 1  # 直接作用于原图层，不产生复制层

    def test_selection_only_without_selection(self, fresh_image):
        client, _ = fresh_image
        with pytest.raises(ScriptFuError, match="没有活动选区"):
            adjust.gaussian_blur(client, 8, selection_only=True)


class TestAddText:
    def test_bottom_right_watermark(self, fresh_image):
        client, _ = fresh_image
        result = adjust.add_text(client, "©2026", color="#ffffff", anchor="bottom-right")
        assert result["text_width"] > 0
        info = connection.get_image_info(client)
        assert any(l["name"] == "©2026" for l in info["layers"])

    def test_chinese_text_at_position(self, fresh_image):
        client, _ = fresh_image
        result = adjust.add_text(client, "水印测试", position=(5, 5), color="#ff0000")
        assert result["anchor"] == "position"

    def test_bad_color(self, fresh_image):
        client, _ = fresh_image
        with pytest.raises(ValueError):
            adjust.add_text(client, "x", color="white")

    def test_bad_anchor(self, fresh_image):
        client, _ = fresh_image
        with pytest.raises(ValueError):
            adjust.add_text(client, "x", anchor="正中偏左")


# ---------- 反馈回路 ----------

class TestFeedback:
    def test_export_preview_downscale(self, live_client):
        from tools import files as f

        f.new_image(live_client, 3000, 2000, "rgb")
        result = feedback.export_preview(live_client, CONFIG)
        assert result["width"] == 1024
        assert result["height"] == 683
        assert Path(result["path"]).is_file()

    def test_histogram_gray(self, fresh_image):
        client, _ = fresh_image
        selection.fill_selection(client, "#808080")
        stats = feedback.get_histogram_stats(client)
        assert stats["mean"] == pytest.approx(128.0, abs=1.0)
        assert stats["std_dev"] == pytest.approx(0.0, abs=0.1)

    def test_histogram_bad_channel(self, fresh_image):
        client, _ = fresh_image
        with pytest.raises(ValueError):
            feedback.get_histogram_stats(client, "红外")


# ---------- 万能出口 ----------

class TestEscape:
    def test_disabled_by_default(self, live_client):
        with pytest.raises(PermissionError, match="安全开关"):
            escape.run_scriptfu(live_client, CONFIG, "(+ 1 2)")


# ---------- 工具行为的 live 回归 ----------

class TestToolBehaviorRegressions:
    def test_layer_name_with_delimiters(self, fresh_image):
        """add_text 文本含分隔符后 get_image_info 正常返回且名字完整。"""
        client, _ = fresh_image
        text = "Hello, world;|="
        adjust.add_text(client, text)
        info = connection.get_image_info(client)
        assert any(l["name"] == text for l in info["layers"])
        layers.add_layer(client, "逗号,分号;竖线|")
        info = connection.get_image_info(client)
        assert any(l["name"] == "逗号,分号;竖线|" for l in info["layers"])
        layers.remove_layer(client, "逗号,分号;竖线|")

    def test_new_image_white_with_black_background(self, live_client):
        """context 背景为黑时 new_image 仍应产出白底。"""
        live_client.eval("(gimp-context-set-background '(0 0 0))")
        try:
            files.new_image(live_client, 100, 60, "rgb")
            stats = feedback.get_histogram_stats(live_client)
            assert stats["mean"] == pytest.approx(255.0, abs=1.0)
        finally:
            live_client.eval("(gimp-context-set-background '(255 255 255))")

    def test_scale_height_only_no_aspect(self, fresh_image):
        """keep_aspect=False 且只给 height 时 width 保持不变。"""
        client, _ = fresh_image
        result = geometry.scale_image(client, height=90, keep_aspect=False)
        assert result["width"] == 320 and result["height"] == 90

    def test_crop_aspect_extreme_ratio(self, fresh_image):
        """极端比例在小图上应给出明确错误。"""
        client, _ = fresh_image
        with pytest.raises(ValueError, match="不足 1 像素"):
            geometry.crop_to_aspect(client, 1, 10000)

    def test_quality_rejected_for_png(self, fresh_image):
        """png 传 quality 应明确报错。"""
        client, _ = fresh_image
        with pytest.raises(ValueError, match="仅对 jpeg/webp"):
            files.export_image(client, CONFIG, str(OUT / "q.png"), quality=80)

    def test_add_layer_grayscale_and_indexed(self, live_client):
        """灰度/索引图像上添加图层。"""
        for mode in ("grayscale", "indexed"):
            files.new_image(live_client, 100, 60, mode)
            result = layers.add_layer(live_client, f"{mode}层")
            assert result["layer_id"] > 0
            info = connection.get_image_info(live_client)
            assert info["base_type"] == mode
            assert len(info["layers"]) == 2

    def test_preview_filenames_unique(self, live_client):
        """同一图像连续两次预览不重名。"""
        files.new_image(live_client, 100, 60, "rgb")
        p1 = feedback.export_preview(live_client, CONFIG)
        p2 = feedback.export_preview(live_client, CONFIG)
        assert p1["path"] != p2["path"]

    def test_selection_restored_after_apply(self, fresh_image):
        """selection_only=False 执行后原选区必须仍在。"""
        client, img = fresh_image
        selection.select_rect(client, 0, 0, 50, 50)
        adjust.gaussian_blur(client, 5)
        empty = client.eval_string(
            f"(number->string (car (gimp-selection-is-empty {img['image_id']})))"
        )
        assert empty == "0", "执行滤镜后选区丢失"

    def test_selection_restored_after_op_failure(self, fresh_image):
        """op 在 GIMP 端失败时也要恢复选区、不残留 channel。"""
        client, img = fresh_image
        image_id = img["image_id"]
        selection.select_rect(client, 0, 0, 50, 50)
        with pytest.raises(ScriptFuError):
            adjust._apply(
                client, image_id,
                "(gimp-drawable-levels drawable 99 0.0 1.0 TRUE 1.0 0.0 1.0 TRUE)",
                "(vector-ref (car (gimp-image-get-selected-drawables (vector-ref (car (gimp-get-images)) 0))) 0)",
                False,
            )
        empty = client.eval_string(
            f"(number->string (car (gimp-selection-is-empty {image_id})))"
        )
        assert empty == "0", "op 失败后选区未恢复"


# ---------- 选区与预览的 live 回归 ----------


class TestSelectionAndPreviewRegressions:
    def test_selection_only_targets_active_layer(self, fresh_image):
        """活动图层不是最顶层时，selection_only 也只能改它，不能改顶层。"""
        client, img = fresh_image
        image_id = img["image_id"]
        selection.select_none(client)
        selection.fill_selection(client, "#808080")     # Background 灰 128
        layers.add_layer(client, "Top")
        selection.fill_selection(client, "#000000")     # Top 黑
        layers.set_active_layer(client, "Background")
        selection.select_all(client)
        top_before = _layer_mean(client, image_id, "Top")
        top_id_before = layers._find_layer(client, image_id, "Top")

        adjust.adjust_levels(client, input_white=128, selection_only=True)

        assert _layer_mean(client, image_id, "Background") > 140, "目标图层没被调整"
        assert _layer_mean(client, image_id, "Top") == top_before, "顶层被误改了"
        assert layers._find_layer(client, image_id, "Top") == top_id_before, "不应再 merge-down"
        assert len(connection.get_image_info(client)["layers"]) == 2

    def test_export_preview_png_is_real_png(self, fresh_image):
        """.png 预览必须真的是 PNG，而不是改了扩展名的 JPEG。"""
        client, _ = fresh_image
        target = OUT / "preview.png"
        result = feedback.export_preview(client, CONFIG, str(target))
        assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert result["width"] > 0 and result["height"] > 0

    def test_export_preview_failure_leaves_no_duplicate(self, fresh_image):
        """预览导出失败也不能在 GIMP 里留下副本图像劫持后续调用。"""
        client, img = fresh_image
        before = _image_count(client)
        target = OUT / "not_a_file.jpg"
        target.mkdir()
        try:
            with pytest.raises(Exception):
                feedback.export_preview(client, CONFIG, str(target))
        finally:
            target.rmdir()
        assert _image_count(client) == before, "导出失败后残留了副本图像"
        assert require_image(client) == img["image_id"]

    def test_no_layer_gives_readable_error(self, fresh_image):
        """删光图层后要报可读错误，而不是 vector-ref 越界。"""
        client, _ = fresh_image
        layers.remove_layer(client, "Background")
        with pytest.raises(ScriptFuError, match="没有选中的图层"):
            feedback.get_histogram_stats(client)

    def test_full_image_adjust_actually_applies_with_selection(self, fresh_image):
        """有选区时 selection_only=False 仍须修改目标图层像素。

        gimp-selection-save 会把新建 channel 变成选中 drawable，因此必须在保存选区前确定目标图层。
        """
        client, img = fresh_image
        image_id = img["image_id"]
        selection.select_none(client)
        selection.fill_selection(client, "#808080")
        before = _layer_mean(client, image_id, "Background")
        selection.select_rect(client, 0, 0, 10, 10)
        adjust.adjust_brightness_contrast(client, 20, 0)
        selection.select_none(client)   # 直方图受选区限制，先取消再测全图
        after = _layer_mean(client, image_id, "Background")
        assert after > before, f"有选区时全图调整未生效: {before} -> {after}"


class TestExportAndPathRegressions:
    @pytest.mark.parametrize("extension", ["jpg", "webp"])
    def test_quality_changes_encoded_and_decoded_output(self, live_client, extension):
        import random
        from PIL import Image

        source = OUT / "noise.png"
        Image.frombytes("RGB", (128, 96), random.Random(42).randbytes(128 * 96 * 3)).save(source)
        files.open_image(live_client, CONFIG, str(source))
        low, high = OUT / f"low.{extension}", OUT / f"high.{extension}"
        files.export_image(live_client, CONFIG, str(low), quality=1)
        files.export_image(live_client, CONFIG, str(high), quality=100)
        assert low.stat().st_size < high.stat().st_size
        with Image.open(low) as a, Image.open(high) as b:
            assert a.convert("RGB").tobytes() != b.convert("RGB").tobytes()

    @pytest.mark.parametrize("preview", [False, True])
    def test_png_is_not_interlaced(self, fresh_image, preview):
        client, _ = fresh_image
        target = OUT / "output.png"
        if preview:
            feedback.export_preview(client, CONFIG, str(target))
        else:
            files.export_image(client, CONFIG, str(target))
        data = target.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert data[28] == 0

    @pytest.mark.parametrize("mode", ["rgb", "grayscale", "indexed"])
    def test_new_image_white_pixels_export(self, live_client, mode):
        from PIL import Image

        image = files.new_image(live_client, 16, 12, mode)
        if mode == "indexed":
            palette = live_client.eval_string(f"(number->string (car (gimp-image-get-palette {image['image_id']})))")
            count = live_client.eval_string(f"(number->string (car (gimp-palette-get-color-count {palette})))")
            assert int(count) > 0
        target = OUT / f"white_{mode}.png"
        files.export_image(live_client, CONFIG, str(target))
        with Image.open(target) as result:
            assert result.convert("RGB").getextrema() == ((255, 255),) * 3

    def test_failed_fill_restores_context(self, fresh_image):
        client, image = fresh_image
        layer_id = layers._find_layer(client, image["image_id"], "Background")
        client.eval("(gimp-context-push)")
        try:
            client.eval('(begin (gimp-context-set-foreground "#112233") (gimp-context-set-opacity 75))')
            before = (client.eval("(gimp-context-get-foreground)"), client.eval("(gimp-context-get-opacity)"))
            client.eval(f"(gimp-item-set-lock-content {layer_id} TRUE)")
            with pytest.raises(ScriptFuError):
                selection.fill_selection(client, "#ff0000", 50)
            after = (client.eval("(gimp-context-get-foreground)"), client.eval("(gimp-context-get-opacity)"))
            assert after == before
        finally:
            client.eval("(gimp-context-pop)")

    @pytest.mark.parametrize("name", ["a\rb", "a\r\nb", "a\x01b", "a\x1bb", "a\\b", "中文\t名称"])
    def test_control_character_layer_names_round_trip(self, fresh_image, name):
        client, _ = fresh_image
        added = layers.add_layer(client, name)
        assert connection.get_image_info(client)["layers"][0]["name"] == name
        assert layers.set_active_layer(client, name)["layer_id"] == added["layer_id"]

    def test_duplicate_below_top_preserves_composite(self, fresh_image):
        from PIL import Image

        client, _ = fresh_image
        selection.fill_selection(client, "#0000ff")
        layers.add_layer(client, "Top")
        selection.fill_selection(client, "#ff0000")
        before = OUT / "before.png"
        after = OUT / "after.png"
        files.export_image(client, CONFIG, str(before))
        result = layers.duplicate_layer(client, "Background")
        files.export_image(client, CONFIG, str(after))
        names = [layer["name"] for layer in connection.get_image_info(client)["layers"]]
        assert names == ["Top", result["new_layer_name"], "Background"]
        with Image.open(before) as a, Image.open(after) as b:
            assert a.convert("RGB").tobytes() == b.convert("RGB").tobytes()

    def test_duplicate_retains_group_parent(self, fresh_image):
        client, image = fresh_image
        image_id = image["image_id"]
        group = client.eval_string(f'(number->string (car (gimp-group-layer-new {image_id} "Group")))')
        client.eval(f"(gimp-image-insert-layer {image_id} {group} 0 0)")
        src = layers._find_layer(client, image_id, "Background")
        client.eval(f"(gimp-image-reorder-item {image_id} {src} {group} 0)")
        result = layers.duplicate_layer(client, "Background")
        copy = layers._find_layer(client, image_id, result["new_layer_name"])
        assert client.eval_string(f"(number->string (car (gimp-item-get-parent {copy})))") == group
        assert client.eval_string(f"(number->string (car (gimp-image-get-item-position {image_id} {copy})))") == "0"
        assert client.eval_string(f"(number->string (car (gimp-image-get-item-position {image_id} {src})))") == "1"

    def test_duplicate_root_layer_ignores_active_group(self, fresh_image):
        client, image = fresh_image
        image_id = image["image_id"]
        src = layers._find_layer(client, image_id, "Background")
        group = client.eval_string(f'(number->string (car (gimp-group-layer-new {image_id} "Group")))')
        client.eval(f"(gimp-image-insert-layer {image_id} {group} 0 0)")
        child = client.eval_string(f"(number->string (car (gimp-layer-copy {src} TRUE)))")
        client.eval(f"(gimp-image-insert-layer {image_id} {child} {group} 0)")
        client.eval(f'(gimp-item-set-name {child} "Child")')
        client.eval(f"(gimp-image-set-selected-layers {image_id} (vector {child}))")
        result = layers.duplicate_layer(client, "Background")
        copy = layers._find_layer(client, image_id, result["new_layer_name"])
        assert client.eval(f"(gimp-item-get-parent {copy})") == client.eval(f"(gimp-item-get-parent {src})")
        assert client.eval_string(f"(number->string (car (gimp-image-get-item-position {image_id} {copy})))") == "1"

    def test_default_preview_rejects_junction(self, fresh_image, preview_link):
        from config import Config

        client, _ = fresh_image
        link, outside = preview_link
        cfg = Config(allowed_dirs=[str(link.parent)])
        count = _image_count(client)
        with pytest.raises(PermissionError, match="白名单"):
            feedback.export_preview(client, cfg)
        assert _image_count(client) == count
        assert list(outside.iterdir()) == []

    def test_restricted_formats_apply_to_all_entrypoints(self, fresh_image):
        from config import Config

        client, _ = fresh_image
        cfg = Config(allowed_dirs=[str(OUT)], allowed_export_extensions=["png"])
        count = _image_count(client)
        with pytest.raises(ValueError, match="不允许的导出扩展名"):
            files.save_xcf(client, cfg, str(OUT / "denied.xcf"))
        with pytest.raises(ValueError, match="不允许的导出扩展名"):
            feedback.export_preview(client, cfg)
        assert not (OUT / "denied.xcf").exists()
        assert _image_count(client) == count
        feedback.export_preview(client, cfg, str(OUT / "allowed.png"))
        assert (OUT / "allowed.png").is_file()

    def test_xcf_format_mismatch_is_rejected(self, fresh_image):
        client, _ = fresh_image
        path = OUT / "wrong.xcf"
        with pytest.raises(ValueError, match="不一致"):
            files.export_image(client, CONFIG, str(path), format="png", quality=1000)
        assert not path.exists()

    def test_scoped_cleanup_keeps_preexisting_image(self, fresh_image):
        from conftest import image_scope

        client, image = fresh_image
        scope = image_scope.__wrapped__(client)
        next(scope)
        extra = files.new_image(client, 8, 8)
        with pytest.raises(StopIteration):
            next(scope)
        assert require_image(client) == image["image_id"]
        assert client.eval_string(f"(number->string (car (gimp-image-id-is-valid {extra['image_id']})))") == "0"

    def test_mcp_stdio_round_trip(self, live_client):
        import asyncio
        import json
        import sys
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from PIL import Image

        project = str(Path(__file__).resolve().parent.parent)
        script = (
            f"import sys; sys.path.insert(0, {project!r}); from config import CONFIG; "
            f"CONFIG.port = {live_client.port}; CONFIG.allowed_dirs = {[str(OUT)]!r}; "
            f"CONFIG.log_dir = {str(OUT / 'logs')!r}; CONFIG.enable_scriptfu_escape_hatch = False; "
            "import server; server.mcp.run()"
        )

        async def run():
            params = StdioServerParameters(command=sys.executable, args=["-c", script])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    async def call(name, arguments):
                        result = await session.call_tool(name, arguments)
                        assert not result.isError, result.content
                        return json.loads(result.content[0].text)

                    assert len((await session.list_tools()).tools) == 33
                    assert (await call("ping", {}))["ok"]
                    assert (await call("new_image", {"width": 16, "height": 12, "mode": "indexed"}))["ok"]
                    result = await call("export_image", {"path": str(OUT / "mcp.png")})
                    assert result["ok"], result
                    rejected = await call("export_image", {"path": str(OUT / "wrong.xcf"), "format": "png"})
                    assert not rejected["ok"] and "不一致" in rejected["error"]
                    assert not (await call("run_scriptfu", {"code": "(+ 1 2)"}))["ok"]

        asyncio.run(run())
        with Image.open(OUT / "mcp.png") as image:
            assert image.size == (16, 12)
            assert image.convert("RGB").getpixel((0, 0)) == (255, 255, 255)
        log = next((OUT / "logs").glob("tool_calls_*.log"))
        assert '"tool": "export_image"' in log.read_text(encoding="utf-8")
