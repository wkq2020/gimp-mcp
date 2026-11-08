# 开发进度

全部 32 个工具已实现并通过 live 集成测试（46/46）与端到端验收（13/13）。

| 工具 | PDB 过程 | 状态 |
|---|---|---|
| ping | gimp-version | live 通过 |
| get_image_info | gimp-image-get-width/height/base-type, gimp-image-get-layers, gimp-item-get-name/visible, gimp-layer-get-opacity | live 通过 |
| open_image | gimp-file-load | live 通过（含白名单拒绝用例） |
| new_image | gimp-image-new, gimp-layer-new(3.2签名), gimp-image-insert-layer, gimp-image-set-selected-layers, gimp-drawable-fill | live 通过 |
| export_image | file-png-export(8参), file-jpeg-export/file-webp-export(3.2简化签名), file-tiff-export, file-gif-export | live 通过（含扩展名/format 校验用例） |
| save_xcf | gimp-file-save | live 通过 |
| crop_to_rect / crop_to_aspect | gimp-image-crop | live 通过（含越界用例） |
| scale_image | gimp-image-scale | live 通过 |
| resize_canvas | gimp-image-resize | live 通过 |
| rotate_image | gimp-image-rotate | live 通过（含非法角度用例） |
| flip_image | gimp-image-flip | live 通过 |
| select_all/none/invert | gimp-selection-all/none/invert | live 通过 |
| select_rect / select_ellipse | gimp-image-select-rectangle/ellipse | live 通过 |
| fill_selection | gimp-context-set-foreground, gimp-drawable-edit-fill, gimp-context-push/pop | live 通过（含非法颜色用例） |
| add_layer | gimp-layer-new, gimp-image-insert-layer, gimp-image-set-selected-layers | live 通过 |
| remove_layer / set_active_layer | gimp-image-get-layer-by-name, gimp-image-remove-layer, gimp-image-set-selected-layers | live 通过（含缺失图层用例） |
| duplicate_layer | gimp-layer-copy, gimp-image-insert-layer | live 通过 |
| adjust_brightness_contrast | gimp-drawable-merge-new-filter "gimp:brightness-contrast"（范围实测 -1.0–1.0） | live 通过（均值提升断言） |
| adjust_levels | gimp-drawable-levels（9参，0.0–1.0） | live 通过（含黑场>白场用例） |
| adjust_hue_saturation | gimp-drawable-hue-saturation（6参） | live 通过 |
| desaturate | gimp-drawable-merge-new-filter "gimp:desaturate"（mode 传数值 0/1/2） | live 通过 |
| gaussian_blur | gimp-drawable-merge-new-filter "gegl:gaussian-blur"（std-dev=半径×0.32） | live 通过 |
| unsharp_mask | gimp-drawable-merge-new-filter "gegl:unsharp-mask"（std-dev/scale/threshold） | live 通过 |
| add_text | gimp-font-get-by-name, gimp-text-font（3.2签名9参，字体为资源ID）, gimp-layer-set-offsets, context 前景色 | live 通过（中文/右下角/指定坐标） |
| selection_only 语义 | gimp-selection-is-empty/save/load/none, gimp-layer-create-mask(type4), gimp-layer-add-mask, gimp-image-merge-down, gimp-image-remove-channel | live 通过（含无选区报错用例） |
| export_preview | gimp-image-duplicate, gimp-image-scale, gimp-image-flatten, file-jpeg-export, gimp-image-delete | live 通过（3000×2000 降采样验证） |
| get_histogram_stats | gimp-drawable-histogram（原生 0–255 量纲） | live 通过（灰底 128 断言） |
| run_scriptfu | 任意（安全开关默认关闭） | live 通过（默认拒绝用例） |

## 关键签名备忘（GIMP 3.2.6 实测）

- 协议帧：请求 `47 + len16` + payload；响应 `47 + err8 + len16` + payload（与任务书描述不同，以实测为准）
- 返回值：字符串带引号、列表带括号、向量 `#(...)`；`print` 未绑定，约定返回单一字符串
- 图像/图层为整数 ID；新建图像无图层
- gimp-layer-new 3.2 签名：`(image name width height type opacity mode)`（name 提前到第 2 位）
- 滤镜统一入口：`(gimp-drawable-merge-new-filter drawable "op" 0 LAYER-MODE-REPLACE 1.0 "key" val ...)`
- gimp-text-font 3.2 签名：`(image drawable x y text border antialias size font-resource-id)`，字体须为 gimp-font-get-by-name 取得的资源 ID
- gimp-drawable-histogram 返回 (mean std-dev median pixels count percentile)，mean/median/std-dev 原生 0–255
- DESATURATE-* 符号常量未绑定，须传数值；gimp-pdb-query 系列未绑定，gimp-pdb-procedure-exists 可用
- 活动图层：GIMP 3 无 gimp-image-get/set-active-layer，用 gimp-image-get-selected-drawables / gimp-image-set-selected-layers
