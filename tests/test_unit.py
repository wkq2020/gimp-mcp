"""无头单测：不依赖 GIMP，覆盖 Scheme 生成、转义、路径白名单、扩展名校验、结果解析。"""

from __future__ import annotations

import pytest

from config import Config
from gimp_client import unwrap_scheme_string
from scheme import esc, num, parse_kv


class TestEsc:
    def test_plain(self):
        assert esc("abc") == '"abc"'

    def test_quotes_and_backslash(self):
        assert esc('a"b\\c') == '"a\\"b\\\\c"'

    def test_newline(self):
        assert esc("a\nb") == '"a\\nb"'

    def test_chinese(self):
        assert esc("路径") == '"路径"'

    def test_injection_attempt(self):
        # 试图注入 Scheme 代码的字符串必须被完整转义
        payload = '") (gimp-quit 0) ("'
        assert esc(payload) == '"\\") (gimp-quit 0) (\\""'


class TestNum:
    def test_int(self):
        assert num(42) == "42"

    def test_float(self):
        assert num(0.5) == "0.5"

    def test_bool_rejected(self):
        with pytest.raises(TypeError):
            num(True)


class TestParseKv:
    def test_basic(self):
        assert parse_kv("a=1;b=x y") == {"a": "1", "b": "x y"}

    def test_empty(self):
        assert parse_kv("") == {}

    def test_value_with_equals(self):
        assert parse_kv("k=a=b") == {"k": "a=b"}


class TestUnwrapSchemeString:
    def test_quoted(self):
        assert unwrap_scheme_string('"hello"') == "hello"

    def test_escaped_quote(self):
        assert unwrap_scheme_string('"a\\"b"') == 'a"b'

    def test_unquoted_passthrough(self):
        assert unwrap_scheme_string("42") == "42"

    def test_chinese(self):
        assert unwrap_scheme_string('"路径测试"') == "路径测试"


class TestConfigWhitelist:
    def test_allowed(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        cfg = Config(allowed_dirs=[str(ws)])
        assert cfg.check_path_allowed(ws / "a.png") == (ws / "a.png").resolve()

    def test_relative_to_project_root(self):
        cfg = Config()
        resolved = cfg.check_path_allowed("workspace/a.png")
        assert resolved.name == "a.png"
        assert "workspace" in resolved.parts

    def test_reject_outside(self, tmp_path):
        cfg = Config(allowed_dirs=[str(tmp_path / "workspace")])
        with pytest.raises(PermissionError):
            cfg.check_path_allowed(r"C:\Windows\notepad.exe")

    def test_reject_traversal(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        cfg = Config(allowed_dirs=[str(ws)])
        with pytest.raises(PermissionError):
            cfg.check_path_allowed(str(ws / ".." / "evil.png"))

    def test_extension_whitelist(self):
        cfg = Config()
        from pathlib import Path

        assert cfg.check_export_extension(Path("a.PNG")) == "png"
        with pytest.raises(ValueError):
            cfg.check_export_extension(Path("a.exe"))

    def test_unknown_config_key(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text('{"bogus_key": 1}', encoding="utf-8")
        with pytest.raises(ValueError, match="未知键"):
            Config.load(p)


class TestValidation:
    """纯 Python 参数校验（不发任何网络请求）。"""

    def test_hex_color(self):
        from tools.selection import _norm_hex

        assert _norm_hex("FF0000") == "#ff0000"
        assert _norm_hex("#00ff00") == "#00ff00"
        with pytest.raises(ValueError):
            _norm_hex("red")

    def test_rotate_degrees(self):
        from tools.geometry import _ROTATE_MAP

        assert set(_ROTATE_MAP) == {90, 180, 270}
