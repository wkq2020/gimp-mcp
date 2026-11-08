"""配置加载：项目根目录下的 config.json。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass
class Config:
    port: int = 10008
    timeout_seconds: float = 60.0
    reconnect_retries: int = 3
    reconnect_interval_seconds: float = 2.0
    allowed_dirs: list[str] = field(default_factory=lambda: ["workspace"])
    allowed_export_extensions: list[str] = field(
        default_factory=lambda: ["png", "jpg", "jpeg", "webp", "tiff", "gif", "xcf"]
    )
    enable_scriptfu_escape_hatch: bool = False
    preview_max_side: int = 1024
    log_dir: str = "logs"

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        cfg_path = path or PROJECT_ROOT / "config.json"
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"config.json 含未知键: {sorted(unknown)}")
        cfg = cls(**data)
        cfg._check_types()
        return cfg

    def _check_types(self) -> None:
        """配置是手写文件，类型错了要在这里给出明确错误，而不是在深处炸。"""
        for name in ("allowed_dirs", "allowed_export_extensions"):
            value = getattr(self, name)
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise ValueError(
                    f"config.json 的 {name} 必须是字符串数组，例如 [\"workspace\"]；"
                    f"当前为 {value!r}（注意别漏方括号，否则字符串会被逐字符当成多个目录）"
                )
        if not isinstance(self.enable_scriptfu_escape_hatch, bool):
            raise ValueError("config.json 的 enable_scriptfu_escape_hatch 必须是 true/false")
        for name in ("port", "reconnect_retries", "preview_max_side"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"config.json 的 {name} 必须是整数，当前为 {value!r}")
        for name in ("timeout_seconds", "reconnect_interval_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"config.json 的 {name} 必须是数值，当前为 {value!r}")
        if not isinstance(self.log_dir, str):
            raise ValueError(f"config.json 的 log_dir 必须是字符串，当前为 {self.log_dir!r}")
        if not 1 <= self.port <= 65535:
            raise ValueError("config.json 的 port 必须在 1–65535 之间")
        if self.reconnect_retries < 0:
            raise ValueError("config.json 的 reconnect_retries 不能为负")
        if self.preview_max_side <= 0:
            raise ValueError("config.json 的 preview_max_side 必须为正")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("config.json 的 timeout_seconds 必须是有限正数")
        if not math.isfinite(self.reconnect_interval_seconds) or self.reconnect_interval_seconds < 0:
            raise ValueError("config.json 的 reconnect_interval_seconds 必须是有限非负数")

    def resolve_allowed_dirs(self) -> list[Path]:
        """白名单目录解析为绝对路径（相对路径相对项目根目录）。"""
        if not self.allowed_dirs:
            raise ValueError("allowed_dirs 配置为空：请在 config.json 中至少配置一个白名单目录")
        dirs = []
        for d in self.allowed_dirs:
            p = Path(d)
            dirs.append((PROJECT_ROOT / p).resolve() if not p.is_absolute() else p.resolve())
        return dirs

    def check_path_allowed(self, path: str | Path) -> Path:
        """校验路径在白名单内，返回解析后的绝对路径；否则抛 PermissionError。"""
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = (PROJECT_ROOT / resolved).resolve()
        else:
            resolved = resolved.resolve()
        for allowed in self.resolve_allowed_dirs():
            if resolved == allowed or allowed in resolved.parents:
                return resolved
        raise PermissionError(
            f"路径不在白名单目录内: {resolved}（白名单: "
            + ", ".join(str(d) for d in self.resolve_allowed_dirs()) + "）"
        )

    def check_export_extension(self, path: Path) -> str:
        """校验导出扩展名白名单，返回小写扩展名（不含点）。"""
        ext = path.suffix.lower().lstrip(".")
        if ext not in [e.lower() for e in self.allowed_export_extensions]:
            raise ValueError(
                f"不允许的导出扩展名: .{ext}（允许: {', '.join(self.allowed_export_extensions)}）"
            )
        return ext


CONFIG = Config.load()
