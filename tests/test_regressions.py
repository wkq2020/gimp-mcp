"""解析、连接、配置与文件安全的回归测试（无头，不依赖 GIMP）。"""

from __future__ import annotations

import socket

import pytest

from config import Config
from gimp_client import GimpClient, GimpConnectionError, ScriptFuError, unwrap_scheme_string
from scheme import num
from tools.connection import get_image_info


class FakeClient:
    """按队列返回预置响应，用于验证解析逻辑。"""

    def __init__(self, responses):
        self.responses = list(responses)

    def eval_string(self, code):
        assert self.responses, f"多余的 eval_string 调用: {code[:80]}"
        return self.responses.pop(0)

    def eval(self, code):
        return self.eval_string(code)


class TestLayerNameDelimiters:
    """图层名含 , ; | = 等字符时 get_image_info 不得崩溃或截断。"""

    @pytest.mark.parametrize("name", [
        "Hello, world", "a;b", "a|b", "a=b", "Hello, world;|=混合",
        "©2026", "中文图层,带;分隔|符",
    ])
    def test_get_image_info(self, name):
        client = FakeClient([
            "1",  # require_image
            "width=100;height=60;base_type=0;layer_ids=10 11",  # 图像信息
            f"1|100.0|{name}",  # 第一层
            "0|50.0|bg",  # 第二层
        ])
        info = get_image_info(client)
        assert info["width"] == 100
        assert len(info["layers"]) == 2
        assert info["layers"][0]["name"] == name
        assert info["layers"][0]["visible"] is True
        assert info["layers"][0]["opacity"] == 100.0
        assert info["layers"][1]["name"] == "bg"
        assert info["layers"][1]["visible"] is False


class _ResponseSocket:
    def __init__(self, text="ok", magic=0x47, err_code=0):
        body = text.encode("utf-8")
        self.response = bytes([magic, err_code, len(body) >> 8, len(body) & 0xFF]) + body
        self.send_calls = 0
        self.recv_calls = 0
        self.closed = False

    def sendall(self, data):
        self.send_calls += 1

    def recv(self, n):
        self.recv_calls += 1
        chunk, self.response = self.response[:n], self.response[n:]
        return chunk

    def close(self):
        self.closed = True


class _TimeoutSocket(_ResponseSocket):
    def recv(self, n):
        raise socket.timeout("timed out")


class _ResetSocket(_ResponseSocket):
    def __init__(self, error):
        super().__init__()
        self.error = error
        self.sent_prefix = b""

    def sendall(self, data):
        super().sendall(data)
        # sendall 抛错并不表示零字节送达。
        self.sent_prefix = data[:5]
        raise self.error


class TestRetrySemantics:
    """只允许建连失败重试；一旦开始发送，任何通信失败都不得重放。"""

    def test_timeout_never_replays(self):
        client = GimpClient(reconnect_retries=3, reconnect_interval=0)
        sock = _TimeoutSocket()
        client._sock = sock
        connect_calls = []
        client.connect = lambda: connect_calls.append(1)  # type: ignore[method-assign]
        with pytest.raises(GimpConnectionError, match="超时"):
            client.eval("(+ 1 2)")
        assert sock.send_calls == 1, "超时后脚本被重发了"
        assert connect_calls == [], "超时后不应触发重连"
        assert sock.closed
        assert client._sock is None

    @pytest.mark.parametrize("error", [
        ConnectionRefusedError("connection refused"), socket.timeout("connect timed out"),
    ], ids=["refused", "timeout"])
    def test_connect_failure_retries(self, monkeypatch, error):
        client = GimpClient(reconnect_retries=2, reconnect_interval=0)
        sock = _ResponseSocket()
        connect_calls = []

        def fake_create_connection(address, timeout):
            connect_calls.append((address, timeout))
            if len(connect_calls) <= 2:
                raise error
            return sock

        monkeypatch.setattr(socket, "create_connection", fake_create_connection)
        assert client.eval("(+ 1 2)") == "ok"
        assert len(connect_calls) == 3
        assert sock.send_calls == 1
        assert not sock.closed

    @pytest.mark.parametrize("retries", [0, 2])
    @pytest.mark.parametrize("error", [
        ConnectionRefusedError("connection refused"), socket.timeout("connect timed out"),
    ], ids=["refused", "timeout"])
    def test_connect_failure_exhausts_retries(self, monkeypatch, error, retries):
        client = GimpClient(reconnect_retries=retries, reconnect_interval=0)
        connect_calls = []

        def fake_create_connection(address, timeout):
            connect_calls.append((address, timeout))
            raise error

        monkeypatch.setattr(socket, "create_connection", fake_create_connection)
        with pytest.raises(GimpConnectionError, match=f"重连 {retries} 次仍失败") as caught:
            client.eval("(+ 1 2)")
        assert len(connect_calls) == 1 + retries
        assert client._sock is None
        assert isinstance(caught.value.__cause__, GimpConnectionError)
        assert caught.value.__cause__.__cause__ is error

    def test_timeout_error_message_mentions_no_replay(self):
        client = GimpClient(reconnect_retries=3, reconnect_interval=0)
        client._sock = _TimeoutSocket()
        with pytest.raises(GimpConnectionError, match="操作状态不确定.*未自动重发"):
            client.eval("x")


class TestEmptyAllowedDirs:
    """allowed_dirs 为空时应给出明确配置错误而非 IndexError。"""

    def test_empty_allowed_dirs(self):
        cfg = Config(allowed_dirs=[])
        with pytest.raises(ValueError, match="allowed_dirs"):
            cfg.resolve_allowed_dirs()


# ---------- 发送开始后的连接失败与禁止重放 ----------


class _ResetAfterSendSocket(_ResponseSocket):
    """sendall 成功，读取响应头或正文时失败。"""

    def __init__(self, error, after_header):
        super().__init__()
        self.error = error
        self.after_header = after_header

    def recv(self, n):
        if self.after_header and self.recv_calls == 0:
            return super().recv(n)
        self.recv_calls += 1
        if self.error is None:
            return b""
        raise self.error


class TestNoReplayAfterSend:
    """sendall 开始后，无论发送还是接收失败，都不得自动重放。"""

    @pytest.mark.parametrize("after_header", [False, True], ids=["header", "body"])
    @pytest.mark.parametrize("error", [
        ConnectionResetError("connection reset"), socket.timeout("recv timed out"), None,
    ], ids=["reset", "timeout", "eof"])
    def test_no_replay_when_send_succeeded(self, error, after_header):
        client = GimpClient(reconnect_retries=3, reconnect_interval=0)
        sock = _ResetAfterSendSocket(error, after_header)
        client._sock = sock
        reconnects = []

        def fake_connect():
            reconnects.append(1)
            client._sock = _ResponseSocket()

        client.connect = fake_connect  # type: ignore[method-assign]
        with pytest.raises(GimpConnectionError, match="操作状态不确定.*未自动重发"):
            client.eval("(+ 1 2)")
        assert reconnects == [], "发送成功后断连不应触发重连"
        assert sock.send_calls == 1, "已上线的脚本被重发了"
        assert sock.closed
        assert client._sock is None

    @pytest.mark.parametrize("error", [
        ConnectionResetError("connection reset"), BrokenPipeError("broken pipe"),
        socket.timeout("send timed out"), OSError("send failed"),
    ], ids=["reset", "broken-pipe", "timeout", "os-error"])
    def test_send_failure_never_replays(self, error):
        """sendall 抛错时可能已有字节送达，必须断连并提示状态不确定。"""
        client = GimpClient(reconnect_retries=2, reconnect_interval=0)
        sock = _ResetSocket(error)
        client._sock = sock
        reconnects = []

        def fake_connect():
            reconnects.append(1)
            client._sock = _ResponseSocket()

        client.connect = fake_connect  # type: ignore[method-assign]
        with pytest.raises(GimpConnectionError, match="操作状态不确定.*未自动重发") as caught:
            client.eval("(+ 1 2)")
        assert reconnects == []
        assert sock.send_calls == 1
        assert sock.sent_prefix
        assert sock.closed
        assert client._sock is None
        assert caught.value.__cause__ is error


class TestResponseProtocol:
    """协议损坏后丢弃连接；正常的 Script-Fu 错误不得触发重试。"""

    def test_bad_magic_closes_without_replay(self):
        client = GimpClient(reconnect_retries=3, reconnect_interval=0)
        stale = _ResponseSocket("stale", magic=0x42)
        fresh = _ResponseSocket("fresh")
        client._sock = stale
        reconnects = []

        def fake_connect():
            reconnects.append(1)
            client._sock = fresh

        client.connect = fake_connect  # type: ignore[method-assign]
        with pytest.raises(GimpConnectionError, match="响应魔数异常.*未自动重发"):
            client.eval("first")
        assert stale.closed
        assert client._sock is None
        assert stale.send_calls == 1
        assert stale.recv_calls == 1, "发现魔数异常后不应继续读取正文"
        assert reconnects == []
        assert fresh.send_calls == 0

        assert client.eval("second") == "fresh"
        assert reconnects == [1]
        assert fresh.send_calls == 1
        assert stale.response == b"stale", "后续调用不应再读取旧连接的响应"

    def test_scriptfu_error_never_retries(self):
        client = GimpClient(reconnect_retries=3, reconnect_interval=0)
        sock = _ResponseSocket("bad script", err_code=1)
        client._sock = sock
        reconnects = []
        client.connect = lambda: reconnects.append(1)  # type: ignore[method-assign]
        with pytest.raises(ScriptFuError, match="bad script"):
            client.eval("invalid")
        assert reconnects == []
        assert sock.send_calls == 1
        assert not sock.closed
        assert client._sock is sock


class TestSchemeStringEscapes:
    """支持 TinyScheme 的回车和两位十六进制转义，保留未知转义。"""

    @pytest.mark.parametrize(("body", "expected"), [
        ("", ""),
        ("plain 中文", "plain 中文"),
        ('"plain 中文"', "plain 中文"),
        (r'"a\nb\tc\"d\\e"', 'a\nb\tc"d\\e'),
        (r'"a\rb"', "a\rb"),
        (r'"a\x01b"', "a\x01b"),
        (r'"中文\x01b"', "中文\x01b"),
        (r'"\x00\x07\x08\x0b\x0c\x1b\x1f\x7f"', "\x00\x07\x08\x0b\x0c\x1b\x1f\x7f"),
        (r'"\x0A\x0d\xAF"', "\n\r\xaf"),
        (r'"\x41f"', "Af"),
        (r'"a\qb"', r"a\qb"),
        (r'"\x"', r"\x"),
        (r'"\x1"', r"\x1"),
        (r'"\x1G"', r"\x1G"),
        (r'"\xGG"', r"\xGG"),
        (r'"\X41"', r"\X41"),
        (r'"\\x01"', r"\x01"),
        (r'"\\r"', r"\r"),
        (r'"trailing\"', "trailing\\"),
        ('  "中文\\n" \n', "中文\n"),
        (r"a\x01b", r"a\x01b"),
    ])
    def test_unwrap(self, body, expected):
        assert unwrap_scheme_string(body) == expected


class TestNumNonFinite:
    """inf/nan 必须在 Python 侧拒绝，科学计数法保持原有格式。"""

    @pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
    def test_rejected(self, bad):
        with pytest.raises(ValueError, match="有限"):
            num(bad)

    def test_scientific_notation_kept(self):
        assert num(1e-05) == "1e-05"

    def test_normal_values_unchanged(self):
        assert num(42) == "42"
        assert num(0.5) == "0.5"


class TestConfigTypes:
    """config.json 类型错误要在加载时给出明确错误。"""

    def _write(self, tmp_path, text):
        p = tmp_path / "config.json"
        p.write_text(text, encoding="utf-8")
        return p

    def test_allowed_dirs_string_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="allowed_dirs"):
            Config.load(self._write(tmp_path, '{"allowed_dirs": "workspace"}'))

    def test_port_string_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="port"):
            Config.load(self._write(tmp_path, '{"port": "10008"}'))

    def test_escape_hatch_must_be_bool(self, tmp_path):
        with pytest.raises(ValueError, match="enable_scriptfu_escape_hatch"):
            Config.load(self._write(tmp_path, '{"enable_scriptfu_escape_hatch": "yes"}'))

    def test_valid_config_loads(self, tmp_path):
        cfg = Config.load(self._write(
            tmp_path, '{"port": 10008, "allowed_dirs": ["workspace"], "timeout_seconds": 60}'))
        assert cfg.port == 10008
        assert cfg.allowed_dirs == ["workspace"]


class TestUnknownExportExtension:
    """白名单里配了没有导出实现的扩展名时，报错要可读，而不是裸 KeyError。"""

    def test_clear_value_error(self, tmp_path):
        from tools import files

        cfg = Config(allowed_dirs=[str(tmp_path)], allowed_export_extensions=["bmp"])
        with pytest.raises(ValueError, match="没有对应的导出实现"):
            files.export_image(None, cfg, str(tmp_path / "x.bmp"))


class TestLoggerRollover:
    """日志文件名要跟着当前日期走，跨零点后不能继续写前一天的文件。"""

    def test_switches_file_when_date_changes(self, tmp_path, monkeypatch):
        from datetime import datetime as real_datetime

        import server

        monkeypatch.setattr(server.CONFIG, "log_dir", str(tmp_path))

        def fake(y, m, d):
            class FakeDatetime:
                @staticmethod
                def now():
                    return real_datetime(y, m, d)

            return FakeDatetime

        monkeypatch.setattr(server, "datetime", fake(2026, 1, 1))
        monkeypatch.setattr(server, "_LOG_DATE", None)
        logger = server._get_logger()
        assert "20260101" in logger.handlers[0].baseFilename

        monkeypatch.setattr(server, "datetime", fake(2026, 1, 2))
        logger = server._get_logger()
        assert "20260102" in logger.handlers[0].baseFilename
        assert len(logger.handlers) == 1, "切换日期不应累积 handler"
        for h in list(logger.handlers):
            logger.removeHandler(h)
            h.close()
        monkeypatch.setattr(server, "_LOG_DATE", None)


class TestExportPolicy:
    @pytest.mark.parametrize("options", [
        {"format": "png"}, {"quality": 1000}, {"quality": 80},
    ])
    def test_xcf_validates_options_before_saving(self, tmp_path, options):
        from tools import files

        cfg = Config(allowed_dirs=[str(tmp_path)])
        with pytest.raises(ValueError):
            files.export_image(None, cfg, str(tmp_path / "x.xcf"), **options)

    def test_save_xcf_checks_allowed_extensions(self, tmp_path):
        from tools import files

        cfg = Config(allowed_dirs=[str(tmp_path)], allowed_export_extensions=["png"])
        with pytest.raises(ValueError, match="不允许的导出扩展名"):
            files.save_xcf(None, cfg, str(tmp_path / "x.xcf"))

    def test_default_preview_checks_allowed_extensions(self, tmp_path):
        from tools import feedback

        cfg = Config(allowed_dirs=[str(tmp_path)], allowed_export_extensions=["png"])
        with pytest.raises(ValueError, match="不允许的导出扩展名"):
            feedback.export_preview(FakeClient(["1"]), cfg)

    def test_default_preview_rejects_directory_link_escape(self, preview_link):
        from tools import feedback

        link, outside = preview_link
        cfg = Config(allowed_dirs=[str(link.parent)])
        with pytest.raises(PermissionError, match="白名单"):
            feedback.export_preview(FakeClient(["1"]), cfg)
        assert list(outside.iterdir()) == []


class TestExportArguments:
    @pytest.mark.parametrize(("extension", "quality", "suffix"), [
        ("png", None, " 0 FALSE 9 TRUE FALSE TRUE TRUE)"),
        ("jpg", 85, " 0 0.85)"),
        ("webp", 85, ' 0 "default" FALSE 85)'),
    ])
    def test_export_uses_correct_pdb_positions(self, tmp_path, monkeypatch, extension, quality, suffix):
        from tools import files

        target = tmp_path / f"output.{extension}"
        sent = []

        class Client:
            def eval(self, code):
                sent.append(code)
                target.write_bytes(b"exported")

        monkeypatch.setattr(files, "require_image", lambda client: 1)
        files.export_image(Client(), Config(allowed_dirs=[str(tmp_path)]), str(target), quality=quality)
        assert len(sent) == 1
        assert sent[0].endswith(suffix)

    def test_jpeg_preview_has_options_before_quality(self, tmp_path):
        from tools import feedback

        target = tmp_path / "preview.jpg"
        sent = []

        class Client(FakeClient):
            def eval(self, code):
                sent.append(code)
                if code.startswith("(file-jpeg-export "):
                    target.write_bytes(b"preview")

        client = Client(["1", "w=100;h=60", "2"])
        feedback.export_preview(client, Config(allowed_dirs=[str(tmp_path)]), str(target))
        assert any(code.startswith("(file-jpeg-export ") and code.endswith(" 0 0.85)") for code in sent)
        assert sent[-1] == "(gimp-image-delete 2)"


class TestLoggerFailures:
    def test_initialization_failure_prevents_operation(self, tmp_path, monkeypatch):
        import server

        blocked = tmp_path / "file"
        blocked.write_text("not a directory", encoding="utf-8")
        monkeypatch.setattr(server.CONFIG, "log_dir", str(blocked))
        monkeypatch.setattr(server, "_LOG_DATE", None)
        calls = []
        result = server._wrap("test", lambda: calls.append(1))
        assert not result["ok"]
        assert "操作未执行" in result["error"]
        assert calls == []

    @pytest.mark.parametrize("operation_fails", [False, True])
    def test_write_failure_preserves_operation_result(self, monkeypatch, operation_fails):
        import server

        class BrokenLogger:
            def info(self, entry):
                raise OSError("log write failed")

        calls = []

        def operation():
            calls.append(1)
            if operation_fails:
                raise ValueError("operation failed")
            return {"rotated": 90}

        monkeypatch.setattr(server, "_get_logger", lambda: BrokenLogger())
        result = server._wrap("test", operation)
        assert calls == [1]
        assert result["ok"] is not operation_fails
        assert "请勿因此重试" in result["warning"]
        if operation_fails:
            assert result["error"] == "operation failed"
        else:
            assert result["result"] == {"rotated": 90}


class TestConfigRanges:
    @pytest.mark.parametrize(("name", "value"), [
        ("port", 0), ("port", 65536), ("reconnect_retries", -1),
        ("preview_max_side", 0), ("timeout_seconds", 0), ("timeout_seconds", -1),
        ("timeout_seconds", float("inf")), ("timeout_seconds", float("nan")),
        ("reconnect_interval_seconds", -1), ("reconnect_interval_seconds", float("inf")),
        ("reconnect_interval_seconds", float("nan")),
    ])
    def test_invalid_ranges_fail_at_load(self, tmp_path, name, value):
        import json

        path = tmp_path / "config.json"
        path.write_text(json.dumps({name: value}), encoding="utf-8")
        with pytest.raises(ValueError, match=name):
            Config.load(path)


class TestImageScope:
    def test_cleanup_preserves_preexisting_images(self):
        from conftest import image_scope

        class Client:
            def __init__(self):
                self.images = {101}
                self.deleted = []

            def eval_string(self, code):
                return " ".join(map(str, self.images))

            def eval(self, code):
                image_id = int(code.removeprefix("(gimp-image-delete ").removesuffix(")"))
                self.deleted.append(image_id)
                self.images.remove(image_id)

        client = Client()
        scope = image_scope.__wrapped__(client)
        next(scope)
        client.images.add(202)
        with pytest.raises(StopIteration):
            next(scope)
        assert client.images == {101}
        assert client.deleted == [202]
