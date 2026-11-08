"""万能出口：直接执行任意 Script-Fu 代码。

安全开关控制，默认关闭（config.json 的 enable_scriptfu_escape_hatch）。
开启等价于允许 AI 执行任意 Scheme 代码，可读写用户有权限的任何文件——见 README 安全警告。
"""

from __future__ import annotations

from config import Config
from gimp_client import GimpClient


def run_scriptfu(client: GimpClient, cfg: Config, code: str) -> dict:
    """执行任意 Script-Fu 代码并返回响应文本。默认禁用。"""
    if not cfg.enable_scriptfu_escape_hatch:
        raise PermissionError(
            "run_scriptfu 已被安全开关禁用（config.json: enable_scriptfu_escape_hatch=false）。"
            "开启它等价于允许 AI 执行任意 Scheme 代码，请在了解风险后手动开启。"
        )
    if not code.strip():
        raise ValueError("code 不能为空")
    output = client.eval(code)
    return {"output": output.strip()}
