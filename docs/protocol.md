# GIMP 3 Script-Fu 协议与兼容性

本文记录在 Windows 11、GIMP 3.2.6 环境下验证的协议格式与 PDB 行为，作为客户端实现和兼容性排查依据。

## 验证环境

GIMP 通过 winget 安装，控制台程序位于 `%LOCALAPPDATA%\Programs\GIMP 3\bin\gimp-console-3.2.exe`。Script-Fu Server 可用以下命令以无头方式启动：

```bash
gimp-console-3.2.exe --batch-interpreter=plug-in-script-fu-eval --batch "(plug-in-script-fu-server 1 \"127.0.0.1\" 10008 \"\")"
```

首次启动约需 10–15 秒。

## 1. 线路协议帧格式

- 请求帧：**3 字节头** = `0x47`('G') + 2 字节大端序长度，后跟 UTF-8 脚本字节。长度上限为 65535。
- 响应帧：**4 字节头** = `0x47`('G') + 1 字节错误码（0=成功，非 0=失败）+ 2 字节大端序长度，后跟 UTF-8 文本。
- 单条 TCP 连接可连续发送多个请求，服务端按序应答。

实测样本：

| 请求 | 响应头(hex) | 响应体 |
|---|---|---|
| `(+ 1 2)` | `47 00 00 01` | `3` |
| `(gimp-version)` | `47 00 00 09` | `("3.2.6")` |
| `(gimp-this-procedure-does-not-exist 1)` | `47 01 00 42` | `Error: eval: unbound variable: gimp-this-procedure-does-not-exist ` |

## 2. 求值环境语义

- **返回值序列化**：最终表达式的值以 Scheme 读取语法打印——字符串带双引号、列表带圆括号、向量 `#(...)`、数字原样。
- `print` 未绑定；`display` / `newline` 可用，但会把 `#t` 混入响应。因此工具脚本约定以单一字符串作为最终表达式，由 Python 端剥除外层引号并反转义。
- GIMP 端错误以 `Error: ` 开头，例如参数错误 `Error: Invalid value for argument 0 `。客户端保留并返回原始错误文本。
- `let*`、多行脚本、`string-append`、`number->string` 和条件表达式均可使用；中文字符串按 UTF-8 往返。
- `TRUE` 求值为 `1`。

## 3. 对象表示（GIMP 3 Script-Fu 兼容层）

- 图像和图层以**整数 ID** 表示：`(gimp-image-new 64 64 RGB)` 返回 `(3)`，即含一个 ID 的列表。
- `(gimp-get-images)` 返回类似 `(#(3 2 1))` 的结构：列表内含一个向量，而不是 GIMP 2 的 `(n (ids))` 形式。
- `(gimp-image-get-layers img)` 对无图层图像返回 `(#())`。新建图像默认没有图层，必须调用 `gimp-layer-new` 和 `gimp-image-insert-layer`。

## 4. PDB 兼容性说明

- **gimp-drawable-histogram**：返回 `(mean std-dev median pixels count percentile)`，其中 mean、median、std-dev 使用 0–255 量纲，percentile 使用 0–1 比例。
- **gimp-text-font（3.2 签名）**：`(image drawable x y text border antialias size font-resource-id)`，共 9 个参数；字体必须是由 `gimp-font-get-by-name` 获取的资源 ID。
- **gimp-layer-new（3.2 签名）**：`(image name width height type opacity mode)`，name 是第 2 个参数。
- **gimp:desaturate**：`DESATURATE-*` 符号常量在该 Script-Fu 环境中未绑定，mode 须传数值（0=lightness，1=luminosity，2=average）。
- **gimp:brightness-contrast**：brightness、contrast 取值范围为 -1.0–1.0。
- **GEGL 滤镜**：`gimp-drawable-merge-new-filter` 可用；`gimp-pdb-procedure-exists` 可能误报该过程缺失，应以实际调用结果为准。
- **蒙版类型**：`gimp-layer-create-mask` 的 SELECTION 类型数值为 4。
- **参数错误编号**：PDB 错误文本中的 "argument N" 为 1 基，且 run-mode 计为第 1 位。
- **GIMP 本地化**：自动生成的图层名随界面语言变化，工具不应依赖这些名称。

## 5. PDB 过程查询

- `gimp-procedural-db-query`、`gimp-pdb-query`、`gimp-pdb-get-procedure-info` 在该求值环境中均未绑定。
- `gimp-pdb-procedure-exists` 可用，返回 `(1)` 或 `(0)`，可用于过程存在性检查。
- 需要核对过程签名时，可使用 gimp-console 的 `--batch-interpreter=python-fu-eval`，通过 GIMP 3.2 自带的 Python 与 GI 内省 PDB；最终兼容性以实际调用结果为准。
