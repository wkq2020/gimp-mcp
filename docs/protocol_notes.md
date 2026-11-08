# Script-Fu Server 协议实测笔记

实测环境：Windows 11，GIMP 3.2.6（winget 安装，`%LOCALAPPDATA%\Programs\GIMP 3\bin\gimp-console-3.2.exe`），
Script-Fu Server 以无头方式启动：

```
gimp-console-3.2.exe --batch-interpreter=plug-in-script-fu-eval --batch "(plug-in-script-fu-server 1 \"127.0.0.1\" 10008 \"\")"
```

首次启动约需 10–15 秒。以下结论全部来自本机实测（探针脚本见 `scripts/probe_*.py`），未凭文档假设。

## 1. 线路协议帧格式（与任务书第 5 节的偏差）

**任务书原文称"4 字节大端序长度前缀 + UTF-8 编码的 Scheme 脚本"，实测不符，以实测为准：**

- 请求帧：**3 字节头** = `0x47`('G') + 2 字节大端序长度，后跟 UTF-8 脚本字节。长度上限 65535。
- 响应帧：**4 字节头** = `0x47`('G') + 1 字节错误码（0=成功，非 0=失败）+ 2 字节大端序长度，后跟 UTF-8 文本。
- 单条 TCP 连接可连续发送多个请求（已实测复用成功）；服务端按序应答。
- 决策：客户端按实测格式实现；任务书允许的偏差记录于此（任务书 11.5 条）。

实测样本：

| 请求 | 响应头(hex) | 响应体 |
|---|---|---|
| `(+ 1 2)` | `47 00 00 01` | `3` |
| `(gimp-version)` | `47 00 00 09` | `("3.2.6")` |
| `(gimp-this-procedure-does-not-exist 1)` | `47 01 00 42` | `Error: eval: unbound variable: gimp-this-procedure-does-not-exist ` |

## 2. 求值环境语义（实测）

- **返回值序列化**：最终表达式的值以 Scheme 读取语法打印——字符串带双引号（`"1920x1080"`）、列表带圆括号（`(1 "a" 2.5)`）、向量 `#(...)`、数字原样。
- **`print` 未绑定**（unbound），**`display` / `newline` 可用**但会把 `#t` 混进响应。⇒ 约定：所有工具脚本以"返回单一字符串"为最终表达式，Python 端剥掉外层引号并反转义。
- 错误表现形式：err=1，响应体以 `Error: ` 开头，例如参数错误 `Error: Invalid value for argument 0 `、类型错误 `Error: in script, expected type: numeric for argument 1 to gimp-image-get-width`。客户端原样带回。
- `let*`、多行脚本、`string-append`、`number->string`、条件表达式均正常；中文字符串往返正常（UTF-8 全程）。
- `TRUE` 求值为 `1`。

## 3. 对象表示（GIMP 3.2.6 Script-Fu 兼容层）

- 图像/图层仍以**整数 ID** 表示：`(gimp-image-new 64 64 RGB)` → `(3)`（返回值是含一个 ID 的列表）。
- `(gimp-get-images)` → `(#(3 2 1))`：列表内含一个**向量**（不是 GIMP 2 的 `(n (ids))` 形式）。
- `(gimp-image-get-layers img)` → `(#())`：同样是向量；**新建图像默认没有任何图层**，必须自行 `gimp-layer-new` + `gimp-image-insert-layer`。

## 4. 工具实现阶段实测补充

- **gimp-drawable-histogram**：返回 `(mean std-dev median pixels count percentile)`，mean/median/std-dev **原生 0–255 量纲**（128 灰底图 mean=128.0），percentile 为 0–1 比例。
- **gimp-text-font（3.2 签名）**：`(image drawable x y text border antialias size font-resource-id)`——共 9 参，无 2.x 的 size-type 单位参；字体必须是**字体资源 ID**（`gimp-font-get-by-name` 取得），传字体名字符串报 `resource ID of improper subclass`。
- **gimp-layer-new（3.2 签名）**：`(image name width height type opacity mode)`——name 从 2.x 的第 4 位提前到第 2 位。
- **gimp:desaturate 的 mode 参数**：`DESATURATE-*` 符号常量在该 Script-Fu 环境未绑定，须传数值（0=lightness 1=luminosity 2=average）。
- **gimp:brightness-contrast**：brightness/contrast 取值范围 -1.0–1.0，越界报错文本含范围说明（任务书工具的 -100–100 映射为 /100）。
- **GEGL 滤镜调用**：`gimp-drawable-merge-new-filter` 可用但 `gimp-pdb-procedure-exists` 对它误报缺失——过程名核验以"实际调用成功"为最终依据。
- **蒙版类型常量**：`gimp-layer-create-mask` 的 SELECTION 类型数值为 4（实测选区蒙版流程可用）。
- **错误编号口径**：PDB 错误文本中 "argument N" 为**1 基**且 run-mode 计为第 1 位。
- **GIMP 本地化**：图层自动命名随界面语言变化（中文环境下副本后缀为" 副本"、导入图层名为"背景"），工具不依赖自动命名。

## 5. PDB 过程查询

- `gimp-procedural-db-query`、`gimp-pdb-query`、`gimp-pdb-get-procedure-info` 在该求值环境中**均未绑定**。
- **`gimp-pdb-procedure-exists` 可用**（返回 `(1)`/`(0)`），作为过程名核验手段。
- 过程签名核验辅助手段：gimp-console 的 `--batch-interpreter=python-fu-eval`（GIMP 3.2 自带 Python 3.14，可用 GI 内省 PDB），必要时使用；最终以"实测调用成功"为准并记入各工具 docstring。
