@echo off
rem ============================================================
rem  gimp-mcp 一键启动：打开 GIMP 并自动开启 Script-Fu Server
rem  双击运行即可；AI 的修图操作会实时显示在这个 GIMP 窗口里
rem  无头模式（不弹界面）：start-gimp-mcp.bat -Headless
rem ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-gimp-mcp.ps1" %*
pause
