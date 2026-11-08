# 启动 GIMP 并让 Script-Fu Server 自动就绪（gimp-mcp 的前提环境）。
#
# 用法：
#   .\start-gimp-mcp.ps1              # 推荐：打开 GIMP 界面并自动开启 Server（可实时看到 AI 操作）
#   .\start-gimp-mcp.ps1 -Headless    # 只起无头 Server，不打开界面
#   .\start-gimp-mcp.ps1 -Port 10009  # 自定义端口（需与 config.json 一致）
#
# 双击启动请用同目录的 start-gimp-mcp.bat。

param(
    [switch]$Headless,
    [int]$Port = 10008
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$gimpBin = Join-Path $env:LOCALAPPDATA "Programs\GIMP 3\bin"

function Test-ServerPort([int]$p) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $p)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

if (Test-ServerPort $Port) {
    Write-Host "Script-Fu Server 已在 127.0.0.1:$Port 监听，无需重复启动。"
    exit 0
}

if (-not (Test-Path $gimpBin)) {
    Write-Host "未找到 GIMP 3 安装目录: $gimpBin" -ForegroundColor Red
    Write-Host "请先安装 GIMP 3（winget install GIMP.GIMP.3）"
    exit 1
}

if ($Headless) {
    $exe = Get-ChildItem $gimpBin -Filter "gimp-console-3.*.exe" |
           Where-Object { $_.Name -notmatch "debug|test" } |
           Sort-Object Name -Descending | Select-Object -First 1
} else {
    $exe = Get-ChildItem $gimpBin -Filter "gimp-3.*.exe" |
           Where-Object { $_.Name -notmatch "console|debug|test" } |
           Sort-Object Name -Descending | Select-Object -First 1
}
if (-not $exe) {
    Write-Host "在 $gimpBin 中未找到可执行文件" -ForegroundColor Red
    exit 1
}

# Start-Process 用空格拼接参数且不自动加引号，含引号的 --batch 参数必须手动按 CRT 规则（\"）转义
$argLine = '--batch-interpreter=plug-in-script-fu-eval --batch "(plug-in-script-fu-server 1 \"127.0.0.1\" ' + $Port + ' \"\")"'
Write-Host "启动 $($exe.Name) 并开启 Script-Fu Server（127.0.0.1:$Port）..."
Start-Process -FilePath $exe.FullName -ArgumentList $argLine

$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    if (Test-ServerPort $Port) {
        Write-Host "就绪：Script-Fu Server 正在监听 127.0.0.1:$Port" -ForegroundColor Green
        Write-Host "现在可以在 MCP 客户端里直接使用 gimp 工具了。关闭 GIMP 即停止服务。"
        exit 0
    }
}
Write-Host "等待超时（90 秒），请检查 GIMP 是否能正常启动。" -ForegroundColor Red
exit 1
