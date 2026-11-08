"""Script-Fu Server TCP 客户端（协议封装）。

协议细节与 GIMP 3.2.6 兼容性说明见 docs/protocol.md：
  请求帧：0x47('G') + 2 字节大端长度 + UTF-8 脚本
  响应帧：0x47('G') + 1 字节错误码 + 2 字节大端长度 + UTF-8 文本
socket 目标硬编码为 127.0.0.1，仅允许连接本机 GIMP。
"""

from __future__ import annotations

import socket
import threading
import time

HOST = "127.0.0.1"  # 硬编码 localhost，禁止远程
MAGIC = 0x47
MAX_PAYLOAD = 0xFFFF


class ScriptFuError(Exception):
    """GIMP 端执行失败；消息为 Script-Fu 返回的错误原文。"""


class GimpConnectionError(Exception):
    """无法连接 GIMP Script-Fu Server（含重连失败）。"""


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("GIMP Script-Fu Server 关闭了连接")
        buf.extend(chunk)
    return bytes(buf)


def unwrap_scheme_string(body: str) -> str:
    """服务端把字符串结果打印成带引号的 Scheme 字面量，剥掉外层引号并反转义。"""
    body = body.strip()
    if len(body) >= 2 and body.startswith('"') and body.endswith('"'):
        inner = body[1:-1]
        escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
        out = []
        i = 0
        while i < len(inner):
            ch = inner[i]
            if ch == "\\" and i + 1 < len(inner):
                nxt = inner[i + 1]
                if (
                    nxt == "x"
                    and i + 3 < len(inner)
                    and all(c in "0123456789abcdefABCDEF" for c in inner[i + 2:i + 4])
                ):
                    # TinyScheme 的十六进制转义固定两位，后续字符即使是十六进制也不能吞掉。
                    out.append(chr(int(inner[i + 2:i + 4], 16)))
                    i += 4
                else:
                    out.append(escapes.get(nxt, "\\" + nxt))
                    i += 2
            else:
                out.append(ch)
                i += 1
        return "".join(out)
    return body


class GimpClient:
    """与 GIMP Script-Fu Server 的单连接客户端；调用串行化（内置锁）。"""

    def __init__(
        self,
        port: int = 10008,
        timeout: float = 60.0,
        reconnect_retries: int = 3,
        reconnect_interval: float = 2.0,
    ) -> None:
        self.port = port
        self.timeout = timeout
        self.reconnect_retries = reconnect_retries
        self.reconnect_interval = reconnect_interval
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()

    def connect(self) -> None:
        try:
            self._sock = socket.create_connection((HOST, self.port), timeout=self.timeout)
        except OSError as exc:
            raise GimpConnectionError(
                f"无法连接 GIMP Script-Fu Server（{HOST}:{self.port}）。"
                f"请确认 GIMP 已启动且 Script-Fu Server 已开启。原始错误: {exc}"
            ) from exc

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _ensure_connected(self) -> socket.socket:
        if self._sock is None:
            self.connect()
        assert self._sock is not None
        return self._sock

    def eval(self, code: str) -> str:
        """发送 Scheme 代码并返回响应文本；GIMP 报错抛 ScriptFuError，连接失败抛 GimpConnectionError。"""
        payload = code.encode("utf-8")
        if len(payload) > MAX_PAYLOAD:
            raise ValueError(f"脚本过长（{len(payload)} 字节），协议上限 {MAX_PAYLOAD}")
        with self._lock:
            return self._eval_locked(payload)

    def _eval_locked(self, payload: bytes) -> str:
        header = bytes([MAGIC, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF])
        last_exc: GimpConnectionError | None = None
        # 只重试建连失败；此时尚未尝试发送脚本。
        for attempt in range(1 + self.reconnect_retries):
            try:
                sock = self._ensure_connected()
                break
            except GimpConnectionError as exc:
                self.close()
                last_exc = exc
                if attempt < self.reconnect_retries:
                    time.sleep(self.reconnect_interval)
        else:
            raise GimpConnectionError(
                f"无法连接 GIMP，重连 {self.reconnect_retries} 次仍失败。原始错误: {last_exc}"
            ) from last_exc

        # sendall 即使抛错也可能已送达部分或全部字节；发送/接收阶段一律不能自动重放。
        try:
            sock.sendall(header + payload)
            resp = _recv_exact(sock, 4)
            magic, err_code, hi, lo = resp
            if magic != MAGIC:
                self.close()
                raise GimpConnectionError(
                    f"响应魔数异常: {magic:#x}。已断开连接，操作状态不确定，"
                    f"未自动重发；请检查 GIMP 状态后再决定是否重试。"
                )
            body = _recv_exact(sock, (hi << 8) | lo) if (hi or lo) else b""
            text = body.decode("utf-8", errors="replace")
            if err_code != 0:
                raise ScriptFuError(text.strip() or "GIMP 返回错误但无错误文本")
            return text
        except socket.timeout as exc:
            self.close()
            raise GimpConnectionError(
                f"与 GIMP 通信超时（{self.timeout}s）。操作状态不确定，可能已在 GIMP 端执行或仍在执行，"
                f"未自动重发以免重复应用；请检查 GIMP 状态后再决定是否重试。"
                f"原始错误: {exc}"
            ) from exc
        except OSError as exc:
            self.close()
            raise GimpConnectionError(
                f"发送或接收时与 GIMP 的连接中断。操作状态不确定，可能已在 GIMP 端执行，"
                f"未自动重发以免重复应用；请检查 GIMP 状态后再决定是否重试。"
                f"原始错误: {exc}"
            ) from exc

    def eval_string(self, code: str) -> str:
        """eval 并剥掉字符串结果的外层引号（约定：工具脚本以单一字符串作为最终表达式）。"""
        return unwrap_scheme_string(self.eval(code))
