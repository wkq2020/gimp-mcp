# gimp-mcp

让大模型通过自然语言驱动 GIMP 3 完成图像处理的 MCP 服务。

```
MCP 客户端（大模型）
    │ stdio（MCP 协议）
    ▼
本服务（Python，FastMCP）
    │ 工具调用 → 生成 Script-Fu → 发送执行 → 解析返回
    ▼ TCP（GIMP Script-Fu Server，127.0.0.1:10008）
GIMP 3（桌面实例，实时可见操作过程）
```

设计原则：**确定性操作走封装工具，长尾操作走万能出口（默认关闭），全程支持视觉/数值反馈闭环。**

## 环境要求

- Windows 11（其他平台未实测）
- GIMP 3.x（本仓库在 GIMP 3.2.6 上实测；Script-Fu 过程名以 3.x 为准，2.x 不可用）
- Python 3.12+（本仓库在 3.13 上实测）

## 安装

```bash
cd gimp-mcp
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## 启动步骤

### 1. 启动 GIMP 并开启 Script-Fu Server（三选一）

**方式 A（推荐，双击即用）**：双击项目根目录的 `start-gimp-mcp.bat`——它会打开 GIMP 界面并自动开启 Script-Fu Server，AI 的每一步操作你都能实时看到；脚本会先检测端口，已启动则不会重复拉起。无头模式：`start-gimp-mcp.bat -Headless`。

**方式 B（GUI 手动）**：启动 GIMP → 滤镜（Filters）→ Development → Script-Fu → Start Server，端口保持 10008。

**方式 C（命令行，无头）**：

```bash
gimp-console-3.2.exe --batch-interpreter=plug-in-script-fu-eval --batch "(plug-in-script-fu-server 1 \"127.0.0.1\" 10008 \"\")"
```

首次启动约需 10–15 秒。服务不代管 GIMP 进程，需保证 Script-Fu Server 先于本服务就绪。

> 注意：务必让 MCP 服务连接你**正在看**的那个 GIMP 实例。方式 A 启动的 GUI 实例自带 Server；若用方式 C 起了无头实例又另开 GUI，AI 操作的是看不见的无头实例。

### 2. 在 MCP 客户端注册本服务

以 Claude Desktop / Kimi Code 的 MCP 配置为例：

```json
{
  "mcpServers": {
    "gimp": {
      "command": "C:\\path\\to\\gimp-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\gimp-mcp\\server.py"],
      "cwd": "C:\\path\\to\\gimp-mcp"
    }
  }
}
```

将示例中的 `C:\path\to\gimp-mcp` 替换为你的实际克隆路径。

用 MCP Inspector 调试：

```bash
.venv\Scripts\mcp dev server.py
```

### 3. 验证

在 MCP 客户端调用 `ping`，返回 GIMP 版本号即链路打通。

## 配置（config.json）

| 键 | 默认值 | 说明 |
|---|---|---|
| `port` | 10008 | Script-Fu Server 端口（主机硬编码 127.0.0.1，不可配置） |
| `timeout_seconds` | 60 | 单次 GIMP 调用超时 |
| `reconnect_retries` / `reconnect_interval_seconds` | 3 / 2 | 断线重连次数与间隔 |
| `allowed_dirs` | `["workspace"]` | 文件路径白名单目录（相对项目根目录或绝对路径） |
| `allowed_export_extensions` | png/jpg/jpeg/webp/tiff/gif/xcf | 导出扩展名白名单 |
| `enable_scriptfu_escape_hatch` | false | 万能出口开关，见下方安全警告 |
| `preview_max_side` | 1024 | 预览图最长边 |
| `log_dir` | logs | 调用日志目录 |

## 工具一览（33 个）

- **连接**：`ping`、`get_image_info`、`list_fonts`（查询已安装字体名，供 `add_text` 使用）
- **文件**：`open_image`、`new_image`、`export_image`、`save_xcf`
- **几何**：`crop_to_rect`、`crop_to_aspect`、`scale_image`、`resize_canvas`、`rotate_image`、`flip_image`
- **选区**：`select_all`、`select_none`、`select_invert`、`select_rect`、`select_ellipse`、`fill_selection`
- **图层**：`add_layer`、`remove_layer`、`set_active_layer`、`duplicate_layer`
- **调色/滤镜**：`adjust_brightness_contrast`、`adjust_levels`、`adjust_hue_saturation`、`desaturate`、`gaussian_blur`、`unsharp_mask`（以上 6 个支持 `selection_only`）、`add_text`（文字图层，不支持 `selection_only`）
- **反馈回路**：`export_preview`（降采样预览图供多模态模型看图验收）、`get_histogram_stats`（均值/中位数/标准差/黑白场占比的数值反馈）
- **万能出口**：`run_scriptfu`（默认关闭）

所有工具返回统一结构 `{ok, result?, error?}`；GIMP 端失败时 `error` 原样带回 Script-Fu 错误文本，便于大模型自我纠正重试。

## ⚠️ 安全警告

1. **本服务只对本地负责**：socket 目标硬编码 `127.0.0.1`，无法也不应改为远程地址。
2. **文件操作被限制在白名单目录**（默认仅项目内 `workspace/`）。`open_image` / `export_image` / `save_xcf` 越界即拒绝。
3. **`run_scriptfu` 默认关闭**。把 `config.json` 的 `enable_scriptfu_escape_hatch` 改为 `true` 后，**等价于允许 AI 执行任意 Scheme 代码**——可读写当前用户有权限的任何文件、可调用任意 GIMP 插件。只在你信任所连接的 MCP 客户端与模型时开启。
4. 所有 Scheme 代码拼接处均做参数转义；如发现可注入路径请提 issue。

## 测试

```bash
# 无头单测（不需要 GIMP）
.venv\Scripts\pytest

# 无头 Scheme 合法性验证（需要 gimp-console，较慢）
.venv\Scripts\pytest -m headless

# live 集成测试（自动启动独立 GIMP，使用临时配置、端口和输出目录）
.venv\Scripts\pytest -m live

# 全套测试（unit + headless + live）
.venv\Scripts\pytest -m ""

# 端到端验收（仅对专用测试后端运行；会写 workspace/photo.jpg 等固定文件）
.venv\Scripts\python scripts\e2e_acceptance.py
```

## 已知事项

- **「当前图像」的口径**：一律指 `gimp-get-images` 首元素，即**最近创建/加载**的图像，不是 GIMP 界面焦点所在的那张。目前不支持在多张已打开图像之间切换，也没有关闭图像的工具——长时间会话里图像只增不减，建议处理完一张再开下一张。
- `get_histogram_stats` 在 200 万像素图像上约需 18 秒（GIMP 端 histogram 计算较慢）；3000 万像素级操作建议把 `timeout_seconds` 调大。直方图**受当前选区限制**，要看全图统计请先 `select_none`。
- 自动重试仅限于**尚未发送脚本时的连接建立失败**（默认重试 3 次、间隔 2 秒）。一旦开始发送，发送异常、响应断线、超时及协议错误均关闭连接且不重放；操作可能已经执行，请检查 GIMP 状态后再决定是否重试。
- `export_preview` 默认生成 JPEG，若扩展名白名单未允许 `jpg`，请显式传入已获允许的 `.png` 路径。默认路径同样检查目录联接/符号链接和扩展名白名单。
- `duplicate_layer` 将副本放在源层同一父级、紧邻源层上方并选中；不会把底层副本直接置于整个图像最前面。半透明或特殊混合模式图层被复制后仍可能改变合成效果。
- 日志初始化失败时不执行图像操作；操作完成后的日志记录异常不会将成功改报失败，返回值会附带 `warning`，不要因此重试图像操作。
- GIMP 本地化会影响自动生成的图层名（如副本后缀、导入图层名），按名称操作图层时以 `get_image_info` 返回为准。
- 协议与 PDB 过程名的实测依据见 `docs/protocol_notes.md`，逐工具进度见 `docs/progress.md`。

## 目录结构

```
gimp-mcp/
├── server.py            # MCP 服务入口（FastMCP）
├── gimp_client.py       # Script-Fu TCP 客户端（协议封装）
├── scheme.py            # Scheme 生成/转义/结果解析
├── config.py / config.json
├── tools/               # 按域分组的工具实现
├── tests/               # pytest（unit / headless / live）
├── scripts/             # 协议探针、冒烟、端到端验收脚本
├── workspace/           # 默认白名单目录
├── logs/                # 调用日志
└── docs/                # protocol_notes.md / progress.md
```
